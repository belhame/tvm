"""Transactional repair quotes; client opinions never rewrite performed work."""
from datetime import date
import hashlib
import json
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Count, F, Q, Window
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import AuditLog, ServiceRequest
from .repair_quote_models import RepairQuote, RepairQuoteBook, RepairQuoteDecision
from .request_assignment import assignment_is_accepted, require_accepted_assignment, technician_has_accepted_assignment
from .repair_quote_workflow import quote_status_transition
from .workflow_events import actor_context, append_event

MAX_REVISION = 9_223_372_036_854_775_807


class QuoteConflict(APIException):
    status_code = 409
    default_detail = 'Le devis ou la décision a changé. Rechargez avant de continuer.'


def _allowed(actor):
    if (not actor or not actor.is_active or actor.role == 'courier'
        or (actor.role == 'client' and actor.effective_role != 'client')
        or actor.effective_role not in ('admin', 'manager', 'technician', 'client')):
        raise PermissionDenied('Cet espace est réservé au SAV et au portail client.')
    return actor


def _fresh_actor(actor, *, staff=False, customer=False, service_request=None):
    actor = _allowed(get_user_model().objects.select_for_update(no_key=True).filter(pk=getattr(actor, 'pk', None)).first())
    if staff:
        if actor.effective_role not in ('admin', 'manager', 'technician'):
            raise PermissionDenied('Les devis sont préparés par l’administrateur, le responsable SAV ou le technicien affecté.')
        # Every mutation has already locked/reloaded its SAV. An old browser
        # capability or a reassigned author's draft never grants write access.
        actor = require_accepted_assignment(actor, service_request)
    if customer and actor.effective_role != 'client':
        raise PermissionDenied('La décision appartient au compte client connecté.')
    return actor


def can_prepare_quote(actor, record):
    """Read-only capability; mutations recheck the current accepted assignment."""
    try:
        actor = _allowed(actor)
    except PermissionDenied:
        return False
    return actor.effective_role in ('admin', 'manager') or technician_has_accepted_assignment(actor, record)


def quotes_for(actor):
    actor = _allowed(actor)
    query = RepairQuote.objects.select_related('book__service_request__equipment__client', 'book__current_decision', 'client').prefetch_related('decisions')
    if actor.effective_role == 'client':
        return query.filter(state='issued', client_id=actor.client_id, book__service_request__equipment__client_id=actor.client_id,
                            snapshot__client__id=actor.client_id)
    if actor.effective_role == 'technician':
        return query.filter(book__service_request__assigned_technician_id=actor.pk)
    return query


def visible_quote(actor, identifier):
    quote = quotes_for(actor).filter(pk=identifier).first()
    if quote is None:
        raise NotFound('Devis introuvable.')
    return quote


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({'request_key': 'Une clé UUID est obligatoire.'})


def _expected(value):
    if type(value) is not int or not 0 <= value < MAX_REVISION:
        raise ValidationError({'expected_revision': 'Une révision entière positive ou nulle est obligatoire.'})
    return value


def _key_lock(kind, key):
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [f'repair-quote-{kind}:{key}'])


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def _terms(value):
    if not isinstance(value, str) or len(value) > 10000 or '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValidationError({'terms': 'Les conditions publiques doivent être un texte de 10 000 caractères au maximum.'})
    return value.strip()


def _draft_values(data, previous=None):
    from .repair_quote_money import repair_quote_amounts
    allowed = {'lines', 'vat_rate', 'currency', 'discount_kind', 'discount_value', 'terms', 'valid_until'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValidationError({'detail': 'Champs de devis inconnus.'})
    old = previous.amounts if previous else {}
    lines = data.get('lines', [{k: row[k] for k in ('description', 'quantity', 'unit_ht')} for row in old.get('lines', [])])
    if 'vat_rate' not in data and 'vat_rate' not in old:
        raise ValidationError({'vat_rate': 'Le taux de TVA doit être explicitement renseigné, y compris zéro.'})
    amounts = repair_quote_amounts(lines, vat_rate=data.get('vat_rate', old.get('vat_rate')),
        currency=data.get('currency', old.get('currency', 'TND')), discount_kind=data.get('discount_kind', old.get('discount_kind', 'none')),
        discount_value=data.get('discount_value', old.get('discount_value', '0')))
    valid_until = data.get('valid_until', previous.valid_until if previous else None)
    if valid_until is not None and type(valid_until) is not date:
        try:
            valid_until = date.fromisoformat(valid_until) if type(valid_until) is str else None
        except ValueError:
            valid_until = None
        if valid_until is None:
            raise ValidationError({'valid_until': 'Une date ISO valide est requise.'})
    return {'amounts': amounts, 'terms': _terms(data.get('terms', previous.terms if previous else '')), 'valid_until': valid_until}


def _request_lock(identifier):
    record = ServiceRequest.objects.select_for_update(of=('self',)).select_related('equipment__client').filter(pk=identifier).first()
    if record is None:
        raise NotFound('Dossier SAV introuvable.')
    return record


def _quote_lock(identifier):
    source = RepairQuote.objects.filter(pk=identifier).values('book__service_request_id').first()
    if source is None:
        raise NotFound('Devis introuvable.')
    record = _request_lock(source['book__service_request_id'])
    book = RepairQuoteBook.objects.select_for_update().get(service_request=record)
    quote = RepairQuote.objects.select_for_update().get(pk=identifier, book=book)
    return record, book, quote


def _check_client(actor, record, quote):
    if (actor.client_id is None or record.equipment.client_id != actor.client_id or quote.client_id != actor.client_id
        or quote.snapshot.get('client', {}).get('id') != actor.client_id):
        raise NotFound('Devis introuvable.')


def _safe_phase(record):
    """Only commercial waiting states; any performed/financial/logistics fact wins."""
    from .disposition_models import DispositionProcess
    from .exchange_models import ExchangeProcess
    from .logistics_models import OutboundJob
    if record.status not in ('new', 'pending', 'quotation', 'quote_sent', 'to_repair', 'approved', 'rejected'):
        return False
    if record.interventions.filter(Q(performed_on__isnull=False) | Q(completed_at__isnull=False) | Q(status__in=['in_progress', 'testing', 'completed'])).exists():
        return False
    # A technician may explicitly return from an initial diagnostic to pricing.
    # Historic diagnostic statuses alone do not block that commercial phase.
    # Current technical work, actual performed visits and completed/handoff
    # history still win over a later client opinion.
    if record.operation_events.filter(Q(status_after__in=['resolved', 'ready_for_delivery', 'return_to_client', 'closed']) |
                                      Q(status_before__in=['resolved', 'ready_for_delivery', 'return_to_client', 'closed'])).exists():
        return False
    return not (ExchangeProcess.objects.filter(service_request=record).exists()
                or DispositionProcess.objects.filter(service_request=record).filter(Q(classified_at__isnull=False) | Q(finance_validated_at__isnull=False) | Q(requires_diagnostic_billing=True)).exists()
                or OutboundJob.objects.filter(service_request=record).exists())


def _status(record, status, actor):
    if record.status == status or not _safe_phase(record):
        return False
    record.status = status
    with actor_context(actor), quote_status_transition(record):
        record.save(update_fields=['status', 'updated_at'])
    return True


def _event(record, actor, kind, text):
    append_event(equipment=record.equipment, service_request=record, actor=actor, kind=kind,
                 summary=text, is_internal=False)


def _notice_on_commit(quote_id, event, occurrence):
    transaction.on_commit(lambda: send_quote_notices(quote_id, event, occurrence), robust=True)


@transaction.atomic
def create_draft(actor, *, service_request, request_key, **data):
    key = _uuid(request_key)
    values = _draft_values(data)
    fingerprint = _fingerprint({'service_request': service_request, 'amounts': values['amounts'], 'terms': values['terms'],
                                'valid_until': values['valid_until'].isoformat() if values['valid_until'] else None})
    _key_lock('create', key)
    record = _request_lock(service_request)
    actor = _fresh_actor(actor, staff=True, service_request=record)
    replay = RepairQuote.objects.filter(request_key=key).first()
    if replay:
        if replay.created_by_id != actor.pk or replay.create_hash != fingerprint:
            raise QuoteConflict('Cette clé de création désigne déjà un autre devis.')
        return visible_quote(actor, replay.pk), False
    # A draft may prepare the next price while the current issued agreement is
    # still valid. Diagnostic quotations remain in their separate workflow.
    book, _ = RepairQuoteBook.objects.get_or_create(service_request=record)
    book = RepairQuoteBook.objects.select_for_update().get(pk=book.pk)
    if book.quotes.filter(state='draft').exists():
        raise QuoteConflict('Un brouillon existe déjà pour ce dossier. Ouvrez-le pour le modifier.')
    if book.last_version >= 99999:
        raise ValidationError('Le nombre maximal de révisions a été atteint.')
    book.last_version += 1
    book.save(update_fields=['last_version'])
    quote = RepairQuote.objects.create(book=book, client=record.equipment.client, version=book.last_version,
        request_key=key, create_hash=fingerprint, created_by=actor, **values)
    AuditLog.objects.create(actor=actor, action='create_repair_quote', resource='repairquote', resource_id=str(quote.pk))
    return visible_quote(actor, quote.pk), True


@transaction.atomic
def edit_draft(actor, identifier, *, expected_revision, **data):
    expected = _expected(expected_revision)
    record, book, quote = _quote_lock(identifier)
    actor = _fresh_actor(actor, staff=True, service_request=record)
    if quote.state != 'draft' or quote.revision != expected:
        raise QuoteConflict()
    if quote.client_id != record.equipment.client_id:
        raise QuoteConflict('Le propriétaire du matériel a changé. Créez un nouveau dossier correctement rattaché.')
    values = _draft_values(data, quote)
    for key, value in values.items():
        setattr(quote, key, value)
    quote.revision += 1
    quote.save()
    return visible_quote(actor, quote.pk)


@transaction.atomic
def issue_quote(actor, identifier, *, request_key, expected_revision):
    key, expected = _uuid(request_key), _expected(expected_revision)
    _key_lock('issue', key)
    record, book, quote = _quote_lock(identifier)
    actor = _fresh_actor(actor, staff=True, service_request=record)
    replay = RepairQuote.objects.filter(issue_key=key).first()
    if replay:
        if replay.pk != quote.pk or replay.issue_revision != expected or replay.issued_by_id != actor.pk:
            raise QuoteConflict('Cette clé d’émission désigne déjà une autre opération.')
        return visible_quote(actor, quote.pk), False
    if quote.state != 'draft' or quote.revision != expected:
        raise QuoteConflict()
    if quote.client_id != record.equipment.client_id:
        raise QuoteConflict('Le propriétaire actuel ne correspond plus au brouillon.')
    if book.decision_revision >= MAX_REVISION:
        raise ValidationError('La révision de décision a atteint sa limite.')
    if quote.valid_until and quote.valid_until < timezone.localdate():
        raise ValidationError({'valid_until': 'La validité ne peut pas être antérieure à l’émission.'})
    # Lock the material identity while taking the immutable commercial snapshot.
    from .models import Equipment
    equipment = Equipment.objects.select_for_update(no_key=True).select_related('client').get(pk=record.equipment_id)
    if equipment.client_id != quote.client_id:
        raise QuoteConflict('Le propriétaire du matériel a changé.')
    client = equipment.client
    now = timezone.now()
    quote.reference = f'DR-{record.reference}-R{quote.version}'
    quote.snapshot = {'version': 1, 'reference': quote.reference, 'issued_on': timezone.localdate(now).isoformat(), 'issued_at': now.isoformat(),
        'valid_until': quote.valid_until.isoformat() if quote.valid_until else None,
        'service_request': {'call_number': record.reference, 'client_reference': record.client_reference},
        'equipment': {'serial_number': equipment.serial_number, 'model': equipment.model, 'brand': equipment.brand},
        'client': {field: getattr(client, field) for field in ('id', 'name', 'address', 'city', 'postal_code', 'country', 'tax_id', 'contact_name', 'email', 'phone')},
        'amounts': quote.amounts, 'terms': quote.terms}
    from .repair_quote_pdf import repair_quote_pdf
    quote.pdf_data = repair_quote_pdf(quote.snapshot)
    quote.pdf_sha256 = hashlib.sha256(quote.pdf_data).hexdigest()
    quote.state, quote.issued_at, quote.issued_by, quote.issue_key, quote.issue_revision = 'issued', now, actor, key, expected
    quote.revision += 1
    quote.save()
    book.current_quote, book.current_decision = quote, None
    book.decision_revision += 1
    book.save(update_fields=['current_quote', 'current_decision', 'decision_revision'])
    changed = _status(record, 'quote_sent', actor)
    _event(record, actor, 'repair_quote_issued', f'Devis de réparation {quote.reference} émis, révision {quote.version}. Accord client en attente.' +
           ('' if changed or record.status == 'quote_sent' else ' Les opérations déjà réalisées restent conservées.'))
    AuditLog.objects.create(actor=actor, action='issue_repair_quote', resource='repairquote', resource_id=str(quote.pk))
    _notice_on_commit(quote.pk, 'issued', quote.pk)
    return visible_quote(actor, quote.pk), True


@transaction.atomic
def decide_quote(actor, identifier, *, request_key, expected_revision, decision):
    key, expected = _uuid(request_key), _expected(expected_revision)
    if decision not in ('accepted', 'refused'):
        raise ValidationError({'decision': 'Choisissez accepted ou refused.'})
    _key_lock('decision', key)
    record, book, quote = _quote_lock(identifier)
    actor = _fresh_actor(actor, customer=True)
    from .models import Equipment
    record.equipment = Equipment.objects.select_for_update(no_key=True).select_related('client').get(pk=record.equipment_id)
    _check_client(actor, record, quote)
    replay = RepairQuoteDecision.objects.filter(request_key=key).first()
    if replay:
        if replay.quote_id != quote.pk or replay.actor_id != actor.pk or replay.expected_revision != expected or replay.decision != decision:
            raise QuoteConflict('Cette clé de décision a déjà été utilisée pour un autre avis.')
        return visible_quote(actor, quote.pk), False
    if quote.state != 'issued' or book.current_quote_id != quote.pk or book.decision_revision != expected:
        raise QuoteConflict('Ce devis ou votre avis a changé. Ouvrez la révision courante.')
    if book.decision_revision >= MAX_REVISION:
        raise ValidationError('La révision de décision a atteint sa limite.')
    changed = _status(record, 'to_repair' if decision == 'accepted' else 'rejected', actor)
    entry = RepairQuoteDecision.objects.create(quote=quote, revision=book.decision_revision + 1,
        request_key=key, expected_revision=expected, decision=decision, actor=actor,
        actor_label=actor.get_full_name() or actor.username, decided_at=timezone.now(), status_changed=changed)
    book.current_decision, book.decision_revision = entry, entry.revision
    book.save(update_fields=['current_decision', 'decision_revision'])
    label = 'accepté' if decision == 'accepted' else 'refusé'
    _event(record, actor, 'repair_quote_decision', f'Le client a {label} le devis de réparation {quote.reference}.' +
           ('' if changed else ' Avis enregistré ; les opérations et décisions financières déjà réalisées restent conservées.'))
    AuditLog.objects.create(actor=actor, action='decide_repair_quote', resource='repairquote', resource_id=str(quote.pk))
    _notice_on_commit(quote.pk, 'decision', entry.pk)
    return visible_quote(actor, quote.pk), True


def quote_payload(quote, actor):
    record, book = quote.book.service_request, quote.book
    current = book.current_quote_id == quote.pk and quote.state == 'issued'
    decisions = list(quote.decisions.all())
    decision = decisions[-1].decision if decisions else 'pending'
    author = can_prepare_quote(actor, record)
    source = quote.snapshot if quote.state == 'issued' else {}
    equipment = source.get('equipment') or {key: getattr(record.equipment, key) for key in ('serial_number', 'model', 'brand')}
    return {'id': quote.pk, 'service_request': record.pk, 'call_number': source.get('service_request', {}).get('call_number', record.reference),
        'client_reference': source.get('service_request', {}).get('client_reference', record.client_reference),
        'client': {'id': quote.client_id, 'name': source.get('client', {}).get('name', quote.client.name)}, 'equipment': equipment,
        'reference': quote.reference, 'version': quote.version, 'state': quote.state, 'is_current': current,
        'revision': quote.revision, 'decision_revision': book.decision_revision, 'decision': decision,
        'amounts': quote.amounts, **{field: quote.amounts[field] for field in ('lines', 'vat_rate', 'currency', 'discount_kind', 'discount_value')},
        'terms': quote.terms, 'valid_until': quote.valid_until.isoformat() if quote.valid_until else None,
        'issued_at': quote.issued_at.isoformat() if quote.issued_at else None, 'created_at': quote.created_at.isoformat(),
        'pdf_url': f'/api/repair-quotes/{quote.pk}/pdf/' if quote.state == 'issued' else None, 'pdf_sha256': quote.pdf_sha256,
        'history': [{'id': row.pk, 'decision': row.decision, 'revision': row.revision, 'decided_at': row.decided_at.isoformat(),
                     'actor_label': row.actor_label, 'status_changed': row.status_changed} for row in decisions],
        'can_edit': author and quote.state == 'draft', 'can_issue': author and quote.state == 'draft',
        'can_create_revision': author,
        'can_decide': bool(actor.is_active and actor.effective_role == 'client' and current and quote.client_id == actor.client_id == record.equipment.client_id)}


def pending_client_quotes(actor):
    """Exact own-account count, bounded current unanswered quote preview."""
    actor = _allowed(actor)
    if actor.effective_role != 'client':
        raise PermissionDenied('Cet accueil de devis est réservé au compte client connecté.')
    query = quotes_for(actor).filter(state='issued', pk=F('book__current_quote_id'), book__current_decision__isnull=True)
    # One statement counts before LIMIT, so an issue/reply committed between
    # two reads cannot disagree with the bounded home preview.
    rows = list(query.annotate(_pending_quote_count=Window(expression=Count('pk'))).order_by('-issued_at', '-pk')[:8])
    return {'count': rows[0]._pending_quote_count if rows else 0, 'results': [quote_payload(quote, actor) for quote in rows]}


def send_quote_notices(quote_id, event, occurrence):
    """Committed, deduplicated application notices; no external provider calls."""
    from .notification_models import InAppNotification
    quote = RepairQuote.objects.select_related('book__service_request__equipment').filter(pk=quote_id, state='issued').first()
    if quote is None:
        return
    record = quote.book.service_request
    if record.equipment.client_id != quote.client_id:
        return
    users = get_user_model().objects.filter(is_active=True).exclude(role='courier')
    if event == 'issued':
        users = users.filter(role='client', client_id=quote.client_id)
    else:
        recipients = Q(role__in=['admin', 'manager']) | Q(is_superuser=True)
        if assignment_is_accepted(record):
            recipients |= Q(pk=record.assigned_technician_id, role='technician')
        users = users.exclude(role='client').filter(recipients)
    now = timezone.now()
    for user in users.iterator():
        InAppNotification.objects.get_or_create(recipient=user, dedup_key=f'repair-quote:{event}:{occurrence}', defaults={
            'kind': 'repair_quote', 'local_date': timezone.localdate(now), 'client_id': quote.client_id, 'service_request': record,
            'created_at': now, 'payload': {'quote_id': quote.pk, 'event': event, 'occurrence': occurrence}})


def quote_notification_payload(item, actor):
    try:
        quote = visible_quote(actor, item.payload.get('quote_id'))
    except (PermissionDenied, NotFound):
        return {'title': 'Devis de réparation', 'body': 'Ce devis ne relève plus de votre compte.', 'target': None,
                'target_id': None, 'actionable': False, 'details': {}}
    data = quote_payload(quote, actor)
    title = 'Devis de réparation'
    body = f'Devis de réparation {quote.reference} disponible.'
    if item.payload.get('event') == 'decision':
        occurrence = item.payload.get('occurrence')
        # A historical notice describes that immutable opinion, even when the
        # current customer response subsequently changes again.
        entry = RepairQuoteDecision.objects.filter(pk=occurrence, quote=quote).first() if type(occurrence) is int and 0 < occurrence <= MAX_REVISION else None
        if entry:
            title = 'Devis accepté' if entry.decision == 'accepted' else 'Devis refusé'
            body = f'Devis {quote.reference} {"accepté" if entry.decision == "accepted" else "refusé"} par le client.'
        else:
            body = f'Le client a enregistré un nouvel avis pour {quote.reference}.'
    return {'title': title, 'body': body, 'target': 'repair_quote', 'target_id': quote.pk, 'actionable': True,
            'service_request': data['service_request'], 'call_number': data['call_number'], 'client_reference': data['client_reference'],
            'details': {'quote': quote.pk, 'reference': quote.reference, 'is_current': data['is_current'], 'state': quote.state, 'decision': data['decision']}}
