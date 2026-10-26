"""Human test results, diagnostic quotations and authorized return clearance."""
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .disposition_models import DiagnosticQuote, DiagnosticQuoteSequence, DispositionProcess
from .exchange_workflow import _editable, _manager, get_process as get_exchange, is_exchange_case, recorded_handoff
from .models import AuditLog, Equipment, ServiceRequest
from .permissions import can_validate_billing
from .workflow_events import append_event, current_actor


def disposition_related(queryset):
    return queryset.select_related('disposition_process__current_quote', 'disposition_process__classified_by', 'disposition_process__finance_validated_by')


def get_disposition(service_request):
    try:
        return service_request.disposition_process
    except ObjectDoesNotExist:
        return None


def _diagnostic_case(service_request, previous_status=None):
    process = get_disposition(service_request)
    return bool((process and process.requires_diagnostic_billing) or service_request.status == 'return_to_client' or previous_status == 'return_to_client' or service_request.operation_events.filter(status_after='return_to_client').exists())


def _financial_evidence(process):
    if not process or not process.finance_validated_at or not process.current_quote_id:
        return False
    quote = process.current_quote
    if quote.process_id != process.pk or quote.snapshot.get('fee_mode') != process.fee_mode:
        return False
    if process.fee_mode == 'free':
        return bool(process.finance_free_reason.strip() and not process.invoice_reference and process.invoiced_on is None and Decimal(quote.snapshot['amounts']['amount_ht']) == 0)
    return bool(process.invoice_reference.strip() and process.invoiced_on and Decimal(quote.snapshot['amounts']['amount_ht']) > 0)


def guard_disposition_update(instance, update_fields, previous_status):
    """Status selectors, timeline and admin cannot manufacture test/fee evidence."""
    old = ServiceRequest.objects.filter(pk=instance.pk).only('status', 'equipment_id').first() if instance.pk and not instance._state.adding else None
    process = get_disposition(old) if old else None
    if old and old.equipment_id != instance.equipment_id and process:
        raise ValidationError({'equipment': 'Le matériel d’origine d’une qualification SAV reste lié à son dossier.'})
    if update_fields is not None and 'status' not in update_fields:
        return
    if previous_status == instance.status:
        return  # Legacy state reads and unrelated edits never invent evidence.
    service_transition = getattr(instance, '_disposition_transition', False)
    if instance.status == 'ready_for_delivery':
        exchange = get_exchange(old) if old else None
        exchange_ready = bool(getattr(instance, '_exchange_transition', False) and exchange and exchange.validated_at and exchange.ready_at)
        repaired = bool(service_transition and process and process.outcome == 'repaired' and process.tests_passed and process.tested_on and process.classified_at)
        if not (exchange_ready or repaired):
            raise ValidationError({'status': 'Confirmez les tests de réparation ou utilisez la validation du remplacement avant de mettre cet onduleur prêt à être livré.'})
    if instance.status == 'return_to_client' and not service_transition:
        raise ValidationError({'status': 'Utilisez la qualification Non réparable avec son diagnostic pour préparer un retour client.'})
    if old and _diagnostic_case(old, previous_status):
        if instance.status == 'closed':
            if not _financial_evidence(process):
                raise ValidationError({'status': 'Confirmez la facture de diagnostic, ou faites approuver sa gratuité, avant de clôturer ce retour.'})
            actor = current_actor()
            if actor and not _manager(actor) and not can_validate_billing(actor):
                raise PermissionDenied('La clôture du retour est réservée aux responsables autorisés.')
        elif process and process.finance_validated_at and not service_transition:
            raise ValidationError({'status': 'La décision financière de ce diagnostic est conservée. Utilisez sa clôture dédiée.'})


def register_disposition_request(service_request, previous_status):
    if service_request.status == 'return_to_client' or previous_status == 'return_to_client':
        process, _ = DispositionProcess.objects.get_or_create(service_request_id=service_request.pk)
        if not process.requires_diagnostic_billing:
            process.requires_diagnostic_billing = True
            process.save(update_fields=['requires_diagnostic_billing', 'updated_at'])
        service_request._state.fields_cache.pop('disposition_process', None)


def _actor_name(actor):
    return (actor.get_full_name() or actor.username) if actor else ''


def _price(value, currency):
    if value is None:
        return None
    quantum = Decimal('.001') if currency == 'TND' else Decimal('.01')
    if value != value.quantize(quantum):
        return str(value)  # Invalid legacy draft is visible, never silently rounded.
    return format(value.quantize(quantum), 'f')


def quote_payload(quote):
    if not quote:
        return None
    amounts = quote.snapshot['amounts']
    return {'id': quote.pk, 'number': quote.number, 'issued_at': quote.issued_at,
            'price_ht': amounts['amount_ht'], 'vat_rate': amounts['vat_rate'], 'vat_amount': amounts['vat_amount'],
            'total_ttc': amounts['total_ttc'], 'currency': amounts['currency'],
            'pdf_url': f'/api/diagnostic-quotes/{quote.pk}/pdf/'}


def disposition_payload(service_request, actor):
    process = get_disposition(service_request)
    if not process:
        if is_exchange_case(service_request):
            return None
        # A readable pending form is not a persisted diagnosis or test result.
        process = DispositionProcess(service_request=service_request)
    internal = bool(actor and actor.effective_role != 'client')
    manager = _manager(actor)
    editable = _editable(actor, service_request)
    closed = service_request.status == 'closed'
    quote = process.current_quote
    finance = _financial_evidence(process)
    handed_over = recorded_handoff(service_request)
    if closed:
        state = 'closed'
    elif finance:
        state = 'free_approved' if process.fee_mode == 'free' else 'invoiced'
    elif process.requires_diagnostic_billing:
        state = 'awaiting_quote' if not quote else 'awaiting_free_approval' if process.fee_mode == 'free' else 'awaiting_invoice'
    else:
        state = 'ready_for_delivery' if process.outcome == 'repaired' and service_request.status == 'ready_for_delivery' else 'pending'
    can_edit = not closed and editable and process.requires_diagnostic_billing and not quote and not process.finance_validated_at
    result = {'outcome': process.outcome, 'state': state, 'diagnosis': process.diagnosis,
        'tests_passed': process.tests_passed, 'tested_on': process.tested_on, 'classified_at': process.classified_at,
        'fee_mode': process.fee_mode, 'currency': process.currency, 'requires_diagnostic_billing': process.requires_diagnostic_billing,
        'quote': quote_payload(quote), 'finance_validated_at': process.finance_validated_at,
        'can_mark_repaired': not closed and editable and not is_exchange_case(service_request) and not quote and not process.finance_validated_at and service_request.status in ('testing', 'resolved') and not handed_over,
        'can_mark_nonrepairable': not closed and editable and not is_exchange_case(service_request) and not quote and not process.finance_validated_at and not handed_over,
        'can_edit_quote': can_edit, 'can_issue_quote': can_edit,
        'can_confirm_invoice': not closed and bool(quote) and not finance and process.fee_mode == 'billable' and can_validate_billing(actor),
        'can_approve_free': not closed and bool(quote) and not finance and process.fee_mode == 'free' and can_validate_billing(actor),
        'can_close': not closed and bool(process.classified_at or service_request.status == 'ready_for_delivery') and (manager or (process.requires_diagnostic_billing and can_validate_billing(actor))) and (not process.requires_diagnostic_billing or finance),
        'can_reset': not closed and bool(process.pk and process.classified_at) and manager and not quote and not process.finance_validated_at and not handed_over,
    }
    if internal:
        result.update({'price_ht': _price(process.price_ht, process.currency), 'vat_rate': str(process.vat_rate) if process.vat_rate is not None else None,
            'free_reason': process.free_reason, 'quote_notes': process.quote_notes,
            'classified_by': process.classified_by_id, 'classified_by_name': _actor_name(process.classified_by),
            'finance_validated_by': process.finance_validated_by_id, 'finance_validated_by_name': _actor_name(process.finance_validated_by),
            'invoice_reference': process.invoice_reference, 'invoiced_on': process.invoiced_on,
            'billing_notes': process.billing_notes, 'finance_free_reason': process.finance_free_reason})
    elif quote:
        result.update({'price_ht': quote.snapshot['amounts']['amount_ht'], 'vat_rate': quote.snapshot['amounts']['vat_rate'],
                       'currency': quote.snapshot['amounts']['currency']})
    return result


def guard_disposition_equipment_update(instance, update_fields=None):
    fields = {'serial_number', 'model', 'brand', 'client', 'client_id'}
    if update_fields is not None and not fields.intersection(update_fields):
        return
    previous = Equipment.objects.filter(pk=instance.pk).values('serial_number', 'model', 'brand', 'client_id').first()
    if not previous or all(previous[field] == getattr(instance, field) for field in previous):
        return
    linked = DispositionProcess.objects.filter(service_request__equipment_id=instance.pk)
    if previous['client_id'] != instance.client_id and linked.exists():
        raise ValidationError({'client': 'Un équipement qualifié conserve son client d’origine et ses documents.'})
    if linked.filter(Q(current_quote__isnull=False) | ~Q(outcome='pending')).exists():
        raise ValidationError({'equipment': 'L’identité du matériel qualifié ou cité dans un devis émis est conservée. Reprenez sa qualification avant toute correction autorisée.'})


def dispatch_kind(service_request):
    exchange = get_exchange(service_request)
    if exchange and exchange.validated_at:
        return 'exchange'
    disposition = get_disposition(service_request)
    if disposition and disposition.outcome == 'repaired' and disposition.tests_passed:
        return 'repair'
    if disposition and disposition.requires_diagnostic_billing:
        return 'return'
    return 'legacy_ready' if service_request.status == 'ready_for_delivery' else None


def _locked(identifier):
    request = ServiceRequest.objects.select_for_update().get(pk=identifier)
    if is_exchange_case(request):
        raise ValidationError('Ce dossier relève du parcours Échange. Sa facturation ne peut pas être remplacée par une gratuité de diagnostic.')
    return request


def _process(service_request):
    process, _ = DispositionProcess.objects.get_or_create(service_request=service_request)
    return DispositionProcess.objects.select_for_update().get(pk=process.pk)


def _mutable(service_request, process):
    if service_request.status == 'closed':
        raise ValidationError('Un dossier clôturé reste conservé. Rouvrez-le avant une nouvelle qualification.')
    if process.current_quote_id or process.finance_validated_at:
        raise ValidationError('Un devis émis ou une décision financière est conservé. Ajoutez une observation pour tracer une correction ; cette action ne réécrit pas le devis.')


def _edit_allowed(actor, service_request):
    if not _editable(actor, service_request):
        raise PermissionDenied('Cette opération est réservée au responsable ou au technicien affecté au dossier.')


def _technical_change_allowed(service_request):
    from .logistics_models import OutboundJob
    if OutboundJob.objects.filter(service_request_id=service_request.pk, handed_over_at__isnull=False).exists():
        raise ValidationError('La remise de ce matériel est déjà enregistrée. La qualification technique reste conservée ; les décisions financières et la clôture restent possibles.')


def _event(service_request, actor, kind, summary, *, observation='', private=False):
    return append_event(equipment=service_request.equipment, service_request=service_request, actor=actor,
                        kind=kind, summary=summary, observation=observation, is_internal=private)


def _audit(process, actor, action):
    AuditLog.objects.create(actor=actor, action=action, resource='dispositionprocess', resource_id=str(process.pk))


@transaction.atomic
def mark_repaired(identifier, data, *, actor):
    service_request = _locked(identifier)
    _edit_allowed(actor, service_request)
    process = _process(service_request)
    _mutable(service_request, process)
    if service_request.status not in ('testing', 'resolved'):
        if service_request.status == 'ready_for_delivery' and process.outcome == 'repaired' and process.tests_passed and process.diagnosis == data['diagnosis'] and process.tested_on == data['tested_on']:
            return service_request
        raise ValidationError({'status': 'Placez le dossier En test ou Traité avant de confirmer que la réparation a passé ses tests.'})
    if data['tests_passed'] is not True:
        raise ValidationError({'tests_passed': 'Confirmez explicitement que les tests sont réussis.'})
    _technical_change_allowed(service_request)
    service_request.equipment = Equipment.objects.select_for_update(no_key=True).get(pk=service_request.equipment_id)
    process.outcome = 'repaired'
    process.diagnosis = data['diagnosis']
    process.tests_passed = True
    process.tested_on = data['tested_on']
    process.classified_at = timezone.now()
    process.classified_by = actor
    process.save()
    service_request._disposition_transition = True
    service_request.status = 'ready_for_delivery'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, actor, 'repair_tests_passed', 'Réparation confirmée après tests réussis. Onduleur prêt à être livré.', observation=process.diagnosis)
    _audit(process, actor, 'repair_ready')
    return service_request


@transaction.atomic
def mark_nonrepairable(identifier, data, *, actor):
    service_request = _locked(identifier)
    _edit_allowed(actor, service_request)
    process = _process(service_request)
    _mutable(service_request, process)
    if process.outcome == 'nonrepairable' and process.diagnosis == data['diagnosis'] and process.fee_mode == data.get('fee_mode', process.fee_mode) and process.free_reason == data.get('free_reason', process.free_reason) and service_request.status == 'return_to_client':
        return service_request
    _technical_change_allowed(service_request)
    service_request.equipment = Equipment.objects.select_for_update(no_key=True).get(pk=service_request.equipment_id)
    process.outcome = 'nonrepairable'
    process.diagnosis = data['diagnosis']
    process.tests_passed = False
    process.tested_on = None
    process.classified_at = timezone.now()
    process.classified_by = actor
    process.requires_diagnostic_billing = True
    process.fee_mode = data.get('fee_mode', process.fee_mode)
    process.free_reason = data.get('free_reason', process.free_reason)
    process.save()
    service_request._disposition_transition = True
    service_request.status = 'return_to_client'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, actor, 'diagnostic_nonrepairable', 'Onduleur déclaré non réparable, à retourner au client. Diagnostic à traiter avant clôture.', observation=process.diagnosis)
    if process.fee_mode == 'free':
        _event(service_request, actor, 'diagnostic_free_proposed', 'Gratuité du diagnostic proposée, en attente de validation financière.', observation=process.free_reason, private=True)
    _audit(process, actor, 'diagnostic_return')
    return service_request


@transaction.atomic
def edit_quote_draft(identifier, data, *, actor):
    service_request = _locked(identifier)
    _edit_allowed(actor, service_request)
    process = _process(service_request)
    _mutable(service_request, process)
    if not process.requires_diagnostic_billing:
        raise ValidationError('Déclarez d’abord le diagnostic du retour avant de préparer son devis.')
    if all(getattr(process, field) == value for field, value in data.items()):
        return service_request
    for field, value in data.items():
        setattr(process, field, value)
    process.save()
    _event(service_request, actor, 'diagnostic_quote_prepared', 'Brouillon du devis de diagnostic mis à jour.', private=True)
    _audit(process, actor, 'diagnostic_draft')
    return service_request


def _quote_number():
    year = timezone.localdate().year
    DiagnosticQuoteSequence.objects.get_or_create(year=year)
    sequence = DiagnosticQuoteSequence.objects.select_for_update().get(year=year)
    if sequence.last_value >= 99999:
        raise ValidationError('La séquence annuelle des devis de diagnostic est épuisée.')
    sequence.last_value += 1
    sequence.save(update_fields=['last_value'])
    return f'DIAG-{year % 100:02d}-{sequence.last_value:05d}'


@transaction.atomic
def issue_quote(identifier, *, actor):
    from .diagnostic_quote import quote_amounts, validate_quote_snapshot
    service_request = _locked(identifier)
    _edit_allowed(actor, service_request)
    process = _process(service_request)
    if process.current_quote_id:
        return service_request
    _mutable(service_request, process)
    if not process.requires_diagnostic_billing or not process.diagnosis.strip():
        raise ValidationError('Un diagnostic de retour est requis pour émettre son devis.')
    if process.price_ht is None or process.vat_rate is None:
        raise ValidationError('Renseignez le montant HT et le taux de TVA applicable, y compris 0 si ce taux est applicable.')
    if process.fee_mode == 'billable' and process.price_ht <= 0:
        raise ValidationError({'price_ht': 'Un diagnostic facturable exige un montant HT strictement positif.'})
    if process.fee_mode == 'free' and (process.price_ht != 0 or not process.free_reason.strip()):
        raise ValidationError('Une gratuité proposée exige un devis à zéro et un motif avant sa validation financière.')
    amounts = quote_amounts(process.price_ht, process.vat_rate, process.currency)
    unit = Equipment.objects.select_for_update(no_key=True).select_related('client').get(pk=service_request.equipment_id)
    client = unit.client
    now = timezone.now()
    number = _quote_number()
    snapshot = {'version': 1, 'reference': number, 'issued_on': timezone.localtime(now).date().isoformat(),
        'service_request': {'id': service_request.pk, 'call_number': service_request.reference, 'client_reference': service_request.client_reference, 'subject': service_request.subject},
        'equipment': {key: getattr(unit, key) for key in ('id', 'serial_number', 'model', 'brand')},
        'client': {key: getattr(client, key) for key in ('id', 'name', 'contact_name', 'email', 'phone', 'address', 'city', 'postal_code', 'country', 'tax_id')},
        'diagnosis': process.diagnosis, 'amounts': amounts, 'fee_mode': process.fee_mode,
        'free_status': 'proposed' if process.fee_mode == 'free' else None, 'quote_notes': process.quote_notes}
    validate_quote_snapshot(snapshot)
    quote = DiagnosticQuote.objects.create(number=number, process=process, issued_at=now, issued_by=actor, snapshot=snapshot)
    process.current_quote = quote
    process.save(update_fields=['current_quote', 'updated_at'])
    _event(service_request, actor, 'diagnostic_quote_issued', f'Devis de diagnostic {number} émis et conservé dans son état initial.')
    _audit(process, actor, 'diagnostic_quote_issue')
    return service_request


@transaction.atomic
def confirm_diagnostic_invoice(identifier, data, *, actor):
    service_request = _locked(identifier)
    if not can_validate_billing(actor):
        raise PermissionDenied('Une autorisation de validation de la facturation est requise.')
    process = _process(service_request)
    if not process.current_quote_id or process.fee_mode != 'billable' or process.current_quote.snapshot['fee_mode'] != 'billable':
        raise ValidationError('Émettez le devis de diagnostic facturable avant de confirmer sa facture.')
    if process.finance_validated_at:
        if process.invoice_reference == data['invoice_reference'] and process.invoiced_on == data['invoiced_on'] and process.billing_notes == data.get('billing_notes', ''):
            return service_request
        raise ValidationError('La facture de diagnostic confirmée ne peut pas être remplacée par cette action.')
    if service_request.status == 'closed':
        raise ValidationError('Ce retour est déjà clôturé.')
    process.invoice_reference = data['invoice_reference']
    process.invoiced_on = data['invoiced_on']
    process.billing_notes = data.get('billing_notes', '')
    process.finance_validated_at = timezone.now()
    process.finance_validated_by = actor
    process.save()
    _event(service_request, actor, 'diagnostic_invoiced', 'Facturation du diagnostic confirmée. La clôture du retour est autorisée.')
    _event(service_request, actor, 'diagnostic_invoice_details', f'Facture {process.invoice_reference} du {process.invoiced_on.isoformat()}.', observation=process.billing_notes, private=True)
    _audit(process, actor, 'diagnostic_invoice')
    return service_request


@transaction.atomic
def approve_free_diagnostic(identifier, *, actor, reason):
    service_request = _locked(identifier)
    if not can_validate_billing(actor):
        raise PermissionDenied('La gratuité du diagnostic exige une autorisation de validation financière.')
    process = _process(service_request)
    if not process.current_quote_id or process.fee_mode != 'free' or process.current_quote.snapshot['fee_mode'] != 'free' or Decimal(process.current_quote.snapshot['amounts']['amount_ht']) != 0:
        raise ValidationError('Émettez d’abord un devis de diagnostic à zéro avec sa proposition de gratuité.')
    if process.finance_validated_at:
        if process.finance_free_reason == reason:
            return service_request
        raise ValidationError('La décision de gratuité déjà confirmée reste conservée.')
    if service_request.status == 'closed':
        raise ValidationError('Ce retour est déjà clôturé.')
    process.finance_free_reason = reason
    process.finance_validated_at = timezone.now()
    process.finance_validated_by = actor
    process.save()
    _event(service_request, actor, 'diagnostic_free_approved', 'Gratuité du diagnostic approuvée. La clôture du retour est autorisée.')
    _event(service_request, actor, 'diagnostic_free_reason', 'Motif de la gratuité approuvée.', observation=reason, private=True)
    _audit(process, actor, 'diagnostic_free')
    return service_request


@transaction.atomic
def close_disposition(identifier, *, actor):
    service_request = _locked(identifier)
    process = _process(service_request)
    if not _manager(actor) and not (process.requires_diagnostic_billing and can_validate_billing(actor)):
        raise PermissionDenied('La clôture est réservée aux responsables autorisés.')
    if process.requires_diagnostic_billing and not _financial_evidence(process):
        raise ValidationError('Confirmez la facture du diagnostic ou approuvez sa gratuité avant de clôturer le retour.')
    if service_request.status == 'closed':
        return service_request
    service_request._disposition_transition = True
    service_request.status = 'closed'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, actor, 'disposition_closed', 'Dossier clôturé après validation des étapes applicables. Aucun transport ou paiement n’est enregistré automatiquement.')
    _audit(process, actor, 'disposition_close')
    return service_request


@transaction.atomic
def reset_disposition(identifier, *, actor, reason):
    service_request = _locked(identifier)
    if not _manager(actor):
        raise PermissionDenied('Le responsable SAV ou un administrateur reprend la qualification.')
    _technical_change_allowed(service_request)
    process = _process(service_request)
    _mutable(service_request, process)
    process.outcome = 'pending'
    process.tests_passed = False
    process.tested_on = process.classified_at = process.classified_by = None
    process.save()
    service_request._disposition_transition = True
    service_request.status = 'testing'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, actor, 'disposition_reset', 'Qualification reprise. Les tests et la situation du diagnostic doivent être revérifiés.')
    _event(service_request, actor, 'disposition_reset_reason', 'Motif de reprise de la qualification.', observation=reason, private=True)
    _audit(process, actor, 'disposition_reset')
    return service_request
