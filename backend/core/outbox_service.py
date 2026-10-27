"""Opt-in delivery, frozen event identity, current recipient and explicit review."""
import hashlib
import json
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .outbox_adapters import DeliveryFailure, deliver_email, deliver_whatsapp
from .outbox_models import ExternalNotification


EVENT_LABELS = {
    'transport_assigned': 'Transport affecté', 'pickup_created': 'Nouvelle demande de collecte',
    'pickup_requested': 'Nouvelle demande de collecte',
    'pickup_assigned': 'Collecte affectée à un livreur', 'pickup_collected': 'Collecte prise en charge',
    'pickup_cancelled': 'Collecte annulée', 'pickup_received': 'Collecte reçue à l’atelier',
}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _clean(value, limit=1000):
    return ' '.join(str(value or '').split())[:limit]


def channel_status(channel):
    if channel == 'email':
        enabled = settings.TVM_EMAIL_ENABLED
        configured = bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD and
            settings.DEFAULT_FROM_EMAIL and settings.EMAIL_USE_TLS != settings.EMAIL_USE_SSL)
        try:
            validate_email(settings.DEFAULT_FROM_EMAIL)
        except DjangoValidationError:
            configured = False
    else:
        enabled = settings.TVM_WHATSAPP_ENABLED
        configured = bool(settings.TVM_WHATSAPP_TOKEN and re.fullmatch(r'[0-9]{5,30}', settings.TVM_WHATSAPP_PHONE_ID) and
            re.fullmatch(r'v[0-9]{1,2}\.[0-9]{1,2}', settings.TVM_WHATSAPP_API_VERSION) and
            re.fullmatch(r'[a-z0-9_]{1,512}', settings.TVM_WHATSAPP_TEMPLATE) and
            re.fullmatch(r'[a-z]{2,3}(?:_[A-Z]{2})?', settings.TVM_WHATSAPP_LANGUAGE))
    return {'enabled': bool(enabled), 'configured': bool(configured), 'operational': bool(enabled and configured),
            'status': 'disabled' if not enabled else 'ready' if configured else 'requires_credentials'}


def _recipient(client, channel):
    value = (client.email if channel == 'email' else client.phone).strip()
    if channel == 'email':
        try:
            validate_email(value)
        except DjangoValidationError:
            return ''
        return value
    value = re.sub(r'[\s().-]', '', value)
    return value if re.fullmatch(r'\+[1-9][0-9]{7,14}', value) else ''


def _redact(value, channel):
    if not value:
        return ''
    if channel == 'email':
        local, domain = value.rsplit('@', 1)
        return f'{local[:1]}***@{domain}'[:180]
    return f'{value[:3]}***{value[-2:]}'


def _source_context(item):
    """A centre remains the owner; an end-customer contact is never the recipient."""
    from .logistics_models import OutboundJob, PickupRequest
    if item.outbound_id:
        source = OutboundJob.objects.select_related('client', 'service_request__equipment', 'delivery_equipment', 'assigned_courier').filter(pk=item.outbound_id).first()
        if not source or source.client_id != item.client_id or source.delivery_equipment.client_id != item.client_id or source.service_request.equipment.client_id != item.client_id:
            return None, 'company_changed'
        if not source.active or source.handed_over_at or source.service_request.status not in ('ready_for_delivery', 'return_to_client'):
            return None, 'event_superseded'
        courier = source.assigned_courier
        if not courier.is_active or courier.role != 'courier' or (courier.courier_kind == 'client' and courier.client_id != item.client_id):
            return None, 'courier_unavailable'
        from .logistics_service import canonical_outbound
        try:
            unit, kind = canonical_outbound(source.service_request)
        except ValidationError:
            return None, 'event_superseded'
        if unit.pk != source.delivery_equipment_id or kind != source.kind:
            return None, 'event_superseded'
        record = source.service_request
        fields = {'source': 'outbound', 'id': source.pk, 'revision': source.assignment_revision, 'event': item.event,
                  'client_id': source.client_id, 'call_number': record.reference, 'client_reference': record.client_reference,
                  'serial_number': source.delivery_equipment.serial_number, 'address': source.delivery_address,
                  'assigned_at': source.assigned_at, 'courier': source.assigned_courier_id}
    else:
        source = PickupRequest.objects.select_related('client', 'equipment', 'service_request__equipment', 'assigned_courier').filter(pk=item.pickup_id).first()
        if not source or source.client_id != item.client_id or (source.equipment_id and source.equipment.client_id != item.client_id):
            return None, 'company_changed'
        if source.service_request_id and (not source.equipment_id or source.service_request.equipment_id != source.equipment_id or source.service_request.equipment.client_id != item.client_id):
            return None, 'company_changed'
        courier = source.assigned_courier
        if courier and (not courier.is_active or courier.role != 'courier' or courier.courier_kind != 'internal'):
            return None, 'courier_unavailable'
        fields = {'source': 'pickup', 'id': source.pk, 'revision': source.assignment_revision, 'event': item.event,
                  'client_id': source.client_id, 'call_number': source.service_request.reference if source.service_request_id else '',
                  'client_reference': source.client_reference, 'serial_number': source.serial_number,
                  'address': source.pickup_address, 'status': source.status, 'assigned_at': source.assigned_at,
                  'courier': source.assigned_courier_id, 'end_customer_name': getattr(source, 'end_customer_name', '')}
    if fields['revision'] != item.revision:
        return None, 'event_superseded'
    client = source.client
    label = EVENT_LABELS.get(item.event, 'Mise à jour logistique')
    courier_name = _clean(courier.get_full_name() or courier.username, 80) if courier else ''
    courier_description = (f'{courier_name} ({"TVM" if courier.courier_kind == "internal" else "livreur de votre société"})'
                           if courier else 'En attente d’affectation')
    assigned = fields.get('assigned_at')
    stamp = timezone.localtime(assigned).strftime('%d/%m/%Y %H:%M %Z') if assigned else 'Non affecté'
    call, client_ref, serial, address = (_clean(fields.get(key)) for key in ('call_number', 'client_reference', 'serial_number', 'address'))
    subject = _clean(f'TVM — {label} — {call or client_ref or serial}', 200)
    text = (f'Bonjour {_clean(client.contact_name, 150) or "Madame, Monsieur"},\n\n{label}.\n'
            f'N° d’appel TVM : {call or "Non attribué"}\nVotre référence : {client_ref or "Non renseignée"}\n'
            f'Numéro de série : {serial}\nAdresse : {address or "À préciser"}\n'
            f'Affectation : {stamp}\nLivreur : {courier_description}\nCréneau de passage : à convenir.\n\nL’équipe TVM')
    return {'client': client, 'fingerprint': _hash(fields), 'subject': subject, 'text': text,
            'call_number': call, 'client_reference': client_ref, 'serial_number': serial,
            'template_values': [_clean(label + ' — ' + stamp + ' · ' + courier_description, 200), call or '-', client_ref or '-', serial or '-', address or 'À préciser'],
            'service_request': record.pk if item.outbound_id else source.service_request_id}, ''


def _block_reason(item, context):
    channel = channel_status(item.channel)
    if not getattr(context['client'], f'notify_{item.channel}', False):
        return 'client_opt_out'
    if not channel['enabled']:
        return 'channel_disabled'
    if not channel['configured']:
        return 'requires_credentials'
    if not _recipient(context['client'], item.channel):
        return 'invalid_or_missing_recipient'
    return ''


@transaction.atomic
def _enqueue(kind, identifier, event, revision=None):
    from .logistics_models import OutboundJob, PickupRequest
    model = OutboundJob if kind == 'outbound' else PickupRequest
    source = model.objects.select_related('client').filter(pk=identifier).first()
    if not source:
        return 0
    revision = source.assignment_revision if revision is None else revision
    item = ExternalNotification(client=source.client, event=event, revision=revision,
        **{f'{kind}_id': identifier})
    context, reason = _source_context(item)
    if not context:
        return 0
    event_key = f'{kind}:{identifier}:{event}:{revision}'
    created = 0
    for channel in ExternalNotification.Channel.values:
        item.channel = channel
        recipient = _recipient(source.client, channel)
        reason = _block_reason(item, context)
        _, was_created = ExternalNotification.objects.get_or_create(event_key=event_key, channel=channel, defaults={
            'client': source.client, f'{kind}_id': identifier, 'event': event, 'revision': revision,
            'context_hash': context['fingerprint'], 'recipient_hash': _hash(recipient),
            'recipient_redacted': _redact(recipient, channel), 'state': 'blocked' if reason else 'pending',
            'blocked_reason': reason, 'authorized_at': None if reason else timezone.now(),
            'next_attempt_at': None if reason else timezone.now()})
        created += int(was_created)
    _centre_in_app(source, kind, event, event_key, context)
    return created


def _centre_in_app(source, kind, event, event_key, context):
    from .models import User
    from .notification_models import InAppNotification
    for user in User.objects.filter(role='client', is_active=True, client_id=source.client_id):
        InAppNotification.objects.get_or_create(recipient=user, dedup_key=f'event:{event_key}', defaults={
            'kind': 'logistics_update', 'client_id': source.client_id, 'local_date': timezone.localdate(),
            'service_request_id': context['service_request'],
            'payload': {'source': kind, 'source_id': source.pk, 'event': event}})


def notify_transport_assignment(outbound_id, revision=None):
    return _enqueue('outbound', outbound_id, 'transport_assigned', revision)


def notify_pickup_event(pickup_id, event, revision=None):
    event = event if event.startswith('pickup_') else f'pickup_{event}'
    if event not in EVENT_LABELS:
        return 0
    return _enqueue('pickup', pickup_id, event, revision)


def logistics_in_app_payload(item, user):
    from .logistics_models import OutboundJob, PickupRequest
    kind, identifier = item.payload.get('source'), item.payload.get('source_id')
    model = OutboundJob if kind == 'outbound' else PickupRequest if kind == 'pickup' else None
    source = model.objects.filter(pk=identifier, client_id=user.client_id).first() if model and user.effective_role == 'client' else None
    if not source or item.client_id != user.client_id:
        return {'title': 'Information logistique', 'body': 'Ce dossier ne relève plus de votre compte.'}
    return {'title': EVENT_LABELS.get(item.payload.get('event'), 'Information logistique'),
            'body': f'{EVENT_LABELS.get(item.payload.get("event"), "Mise à jour logistique")} pour votre centre. Consultez vos enlèvements et transports dans TVM.'}


def outbox_payload(item):
    return {'id': item.pk, 'client': {'id': item.client_id, 'name': item.client.name}, 'channel': item.channel,
        'event': item.event, 'state': item.state, 'blocked_reason': item.blocked_reason, 'attempts': item.attempts,
        'next_attempt_at': item.next_attempt_at, 'sent_at': item.sent_at, 'provider_status': item.provider_status,
        'recipient_redacted': item.recipient_redacted, 'created_at': item.created_at,
        'can_retry': item.state in ('blocked', 'failed', 'uncertain')}


def preview(item, actor):
    context, reason = _source_context(item)
    warnings = [reason] if reason else []
    token = None
    public = {}
    if context:
        recipient = _recipient(context['client'], item.channel)
        public = {key: context[key] for key in ('subject', 'text', 'call_number', 'client_reference', 'serial_number')}
        public['recipient_redacted'] = _redact(recipient, item.channel)
        token = signing.dumps({'id': item.pk, 'actor': actor.pk, 'context': context['fingerprint'],
            'recipient': _hash(recipient), 'content': _hash(public)}, salt='tvm-outbox-preview')
        reason = _block_reason(item, context)
        if reason:
            warnings.append(reason)
        if context['fingerprint'] != item.context_hash:
            warnings.append('event_superseded')
            token = None
    if item.state == 'uncertain':
        warnings.append('provider_may_have_accepted_before_interruption')
    return {'notification': outbox_payload(item), 'preview': public, 'preview_token': token, 'warnings': warnings}


@transaction.atomic
def retry_notification(identifier, actor, token, *, confirm_uncertain=False):
    item = ExternalNotification.objects.select_for_update().select_related('client').get(pk=identifier)
    if item.state not in ('blocked', 'failed', 'uncertain'):
        raise ValidationError('Cette notification ne peut pas être relancée.')
    if item.state == 'uncertain' and not confirm_uncertain:
        raise ValidationError('Confirmez le risque de doublon après vérification chez le fournisseur.')
    try:
        signed = signing.loads(token, salt='tvm-outbox-preview', max_age=600)
    except signing.BadSignature:
        raise ValidationError({'preview_token': 'Prévisualisez à nouveau cette notification.'}) from None
    context, reason = _source_context(item)
    if not context or context['fingerprint'] != item.context_hash:
        raise ValidationError('Cet événement a changé. Consultez la mission actuelle.')
    recipient = _recipient(context['client'], item.channel)
    public = {key: context[key] for key in ('subject', 'text', 'call_number', 'client_reference', 'serial_number')}
    public['recipient_redacted'] = _redact(recipient, item.channel)
    expected = {'id': item.pk, 'actor': actor.pk, 'context': context['fingerprint'], 'recipient': _hash(recipient), 'content': _hash(public)}
    if signed != expected:
        raise ValidationError({'preview_token': 'Le destinataire ou le contenu a changé. Prévisualisez à nouveau.'})
    reason = _block_reason(item, context)
    item.state, item.blocked_reason = ('blocked', reason) if reason else ('pending', '')
    item.recipient_hash, item.recipient_redacted = _hash(recipient), _redact(recipient, item.channel)
    item.authorized_at = timezone.now() if not reason else None
    item.next_attempt_at = timezone.now() if not reason else None
    item.claimed_at = item.claim_token = None
    item.save()
    return item


@transaction.atomic
def _claim(now):
    item = ExternalNotification.objects.select_for_update(skip_locked=True).filter(state='pending', next_attempt_at__lte=now).order_by('next_attempt_at', 'id').first()
    if not item:
        return None
    item.state, item.claimed_at, item.claim_token = 'processing', now, uuid.uuid4()
    item.attempts += 1
    item.save()
    return item


def _finish(item, **values):
    ExternalNotification.objects.filter(pk=item.pk, state='processing', claim_token=item.claim_token).update(
        **values, claim_token=None, claimed_at=None, updated_at=timezone.now())


def process_outbox(*, limit=20, now=None):
    now = now or timezone.now()
    # Never reclaim a timed-out sender: the provider may already have accepted.
    ExternalNotification.objects.filter(state='processing', claimed_at__lt=now - timedelta(minutes=5)).update(
        state='uncertain', blocked_reason='processing_interrupted', provider_status='acceptance_unknown',
        claim_token=None, claimed_at=None, next_attempt_at=None)
    handled = 0
    for _ in range(min(max(limit, 1), 100)):
        item = _claim(now)
        if not item:
            break
        handled += 1
        context, reason = _source_context(item)
        if not context or context['fingerprint'] != item.context_hash:
            _finish(item, state='cancelled', blocked_reason=reason or 'event_superseded', next_attempt_at=None)
            continue
        recipient = _recipient(context['client'], item.channel)
        reason = _block_reason(item, context)
        if _hash(recipient) != item.recipient_hash:
            reason = 'recipient_changed'
        if not item.authorized_at or now - item.authorized_at > timedelta(hours=24):
            reason = 'review_expired'
        if reason:
            _finish(item, state='blocked', blocked_reason=reason, next_attempt_at=None)
            continue
        try:
            provider_id = (deliver_email if item.channel == 'email' else deliver_whatsapp)(recipient, context, item.delivery_key)
        except DeliveryFailure as exc:
            state = 'uncertain' if exc.uncertain else 'pending' if exc.retryable and item.attempts < 5 else 'failed'
            _finish(item, state=state, blocked_reason=exc.code, provider_status='acceptance_unknown' if exc.uncertain else 'rejected',
                    next_attempt_at=now + timedelta(seconds=min(3600, 60 * 2 ** min(item.attempts, 6))) if state == 'pending' else None)
        except Exception:
            # Do not expose credentials/provider response bodies; uncertain is
            # deliberately manual even if a process fails after acceptance.
            _finish(item, state='uncertain', blocked_reason='delivery_interrupted', provider_status='acceptance_unknown', next_attempt_at=None)
        else:
            _finish(item, state='sent', blocked_reason='', provider_status='accepted', provider_message_id=provider_id,
                    sent_at=timezone.now(), next_attempt_at=None)
    return handled
