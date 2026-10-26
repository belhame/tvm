"""Only in-app delivery is implemented; WhatsApp has no transport or outbox."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .notification_models import DailyReminderPreferences, InAppNotification


def _zone(name):
    return ZoneInfo(name or settings.TIME_ZONE)


def _next_run(now, zone):
    local = timezone.localtime(now, zone)
    scheduled = datetime.combine(local.date(), time(8), tzinfo=zone)
    if local >= scheduled:
        scheduled = datetime.combine(local.date() + timedelta(days=1), time(8), tzinfo=zone)
    return scheduled


def logistics_workload(user):
    """Filled from logistics assignments, never from the full customer directory."""
    if not user.is_active or user.effective_role not in ('courier', 'admin'):
        return {'pickups': [], 'deliveries': []}
    from .logistics_service import outbound_for, pickups_for
    pickups = pickups_for(user).filter(assigned_courier=user, status__in=['assigned', 'collected']).order_by('requested_at', 'id')
    outbound = outbound_for(user).filter(assigned_courier=user, active=True, handed_over_at__isnull=True,
        service_request__status__in=['ready_for_delivery', 'return_to_client']).select_related('service_request__equipment__client', 'client', 'delivery_equipment').order_by('assigned_at', 'id')
    return {
        'pickups': [{'id': row.pk, 'client_name': row.client.name, 'client_reference': row.client_reference,
                     'call_number': row.service_request.reference if row.service_request_id else '',
                     'serial_number': row.serial_number, 'model': row.model, 'address': row.pickup_address,
                     'contact_name': row.contact_name, 'contact_phone': row.contact_phone, 'status': row.status}
                    for row in pickups],
        'deliveries': [{'id': row.pk, 'kind': row.kind, 'service_request': row.service_request_id,
                        'call_number': row.service_request.reference, 'client_reference': row.service_request.client_reference,
                        'client_name': row.client.name,
                        'serial_number': row.delivery_equipment.serial_number, 'model': row.delivery_equipment.model,
                        'address': row.delivery_address or row.client.address,
                        'contact_name': row.contact_name or row.client.contact_name,
                        'contact_phone': row.contact_phone or row.client.phone}
                       for row in outbound],
    }


def preferences_payload(user, *, now=None):
    now = now or timezone.now()
    preferences = DailyReminderPreferences.objects.filter(user=user).first()
    zone = _zone(preferences.timezone if preferences else '')
    enabled = bool(preferences and preferences.enabled)
    nominal_run = _next_run(now, zone)
    local = timezone.localtime(now, zone)
    catch_up = bool(enabled and local.time().replace(tzinfo=None) >= time(8) and not InAppNotification.objects.filter(
        recipient=user, kind=InAppNotification.Kind.DAILY, local_date=local.date()).exists())
    next_run = (now if catch_up else nominal_run) if enabled else None
    workload = logistics_workload(user)
    text = (f'Rappel TVM à 08:00 : {len(workload["pickups"])} récupération(s) et '
            f'{len(workload["deliveries"])} remise(s) affectées. Consultez vos missions dans TVM.')
    return {'enabled': enabled, 'hour': 8, 'minute': 0, 'timezone': zone.key,
            'next_run_at': next_run, 'editable': True,
            'schedule_mode': 'disabled' if not enabled else 'catch_up_today' if catch_up else 'next_08',
            'pickup_count': len(workload['pickups']), 'delivery_count': len(workload['deliveries']),
            'in_app_status': 'enabled' if enabled else 'disabled',
            'channel_status': 'requires_credentials', 'whatsapp_connected': False, 'whatsapp_can_send': False,
            'whatsapp_preview': {'text': text, 'scheduled_for': next_run or nominal_run, 'timezone': zone.key,
                                 'status': 'preview_only', 'outbound_sent': False}}


def notification_payload(item, user):
    base = {'id': item.pk, 'kind': item.kind, 'created_at': item.created_at, 'read_at': item.read_at,
            'local_date': item.local_date, 'channel': 'in_app', 'channel_status': 'available',
            'service_request': None, 'call_number': '', 'client_reference': '', 'details': {}}
    if item.kind == InAppNotification.Kind.DAILY:
        workload = logistics_workload(user) if user.effective_role in ('courier', 'admin') else {'pickups': [], 'deliveries': []}
        pickup_ids = set(item.payload.get('pickup_ids', []))
        delivery_ids = set(item.payload.get('delivery_ids', []))
        details = {'pickups': [row for row in workload['pickups'] if row['id'] in pickup_ids],
                   'deliveries': [row for row in workload['deliveries'] if row['id'] in delivery_ids]}
        base.update(title='Vos missions du jour',
                    body=(f'Rappel interne de 08:00 : {len(details["pickups"])} récupération(s) et '
                          f'{len(details["deliveries"])} remise(s) encore affectées.'), details=details)
    else:
        record = item.service_request
        # Notifications never confer access after a change of company or role.
        visible = bool(record and user.effective_role == 'client' and record.equipment.client_id == user.client_id)
        if visible:
            base.update(service_request=record.pk, call_number=record.reference, client_reference=record.client_reference)
        received = item.kind == InAppNotification.Kind.RECEIVED
        delivered_body = ('Le livreur a enregistré une remise pour ce dossier.' if item.payload.get('recorded_by_role') == 'courier'
                          else 'L’équipe TVM a enregistré une remise pour ce dossier.')
        base.update(title='Matériel reçu' if received else 'Remise enregistrée',
                    body=('La réception de votre matériel a été enregistrée par TVM.' if received else delivered_body) if visible else 'Ce dossier ne relève plus de votre compte.')
    return base


def run_daily_reminders(*, now=None):
    """Get-or-create and two SQL constraints make concurrent workers idempotent."""
    now = now or timezone.now()
    created = 0
    preferences = DailyReminderPreferences.objects.select_related('user').filter(enabled=True, user__is_active=True).filter(
        Q(user__role__in=['courier', 'admin']) | Q(user__is_superuser=True))
    for preference in preferences.iterator():
        try:
            zone = _zone(preference.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        local = timezone.localtime(now, zone)
        if local.time().replace(tzinfo=None) < time(8):
            continue
        workload = logistics_workload(preference.user)
        _, was_created = InAppNotification.objects.get_or_create(
            recipient=preference.user, dedup_key=f'daily:{local.date().isoformat()}',
            defaults={'kind': InAppNotification.Kind.DAILY, 'local_date': local.date(), 'created_at': now,
                      'payload': {'pickup_ids': [row['id'] for row in workload['pickups']],
                                  'delivery_ids': [row['id'] for row in workload['deliveries']]}})
        created += int(was_created)
    return created


def _client_notice(record, *, kind, dedup_key, recorded_at, payload=None):
    from .models import User
    local_date = timezone.localtime(recorded_at).date()
    created = 0
    for user in User.objects.filter(role='client', is_active=True, client_id=record.equipment.client_id).iterator():
        _, was_created = InAppNotification.objects.get_or_create(recipient=user, dedup_key=dedup_key,
            defaults={'kind': kind, 'local_date': local_date, 'service_request': record,
                      'created_at': recorded_at, 'payload': payload or {}})
        created += int(was_created)
    return created


def notify_received(request_id):
    """Call on commit after an actual reception; no customer acknowledgment."""
    from .models import ServiceRequest
    record = ServiceRequest.objects.select_related('equipment').filter(pk=request_id).first()
    if not record or not record.arrived_at:
        return 0
    return _client_notice(record, kind=InAppNotification.Kind.RECEIVED,
                          dedup_key=f'received:{record.pk}', recorded_at=timezone.now())


def notify_delivered(delivery_id):
    """Notify only a persisted first handoff; a job assignment is no proof."""
    from .logistics_models import OutboundJob
    job = OutboundJob.objects.select_related('service_request__equipment', 'handed_over_by').filter(pk=delivery_id).first()
    if not job or not job.handed_over_at or job.client_id != job.service_request.equipment.client_id:
        return 0
    return _client_notice(job.service_request, kind=InAppNotification.Kind.DELIVERED,
                          dedup_key=f'delivered:{job.pk}', recorded_at=job.handed_over_at,
                          payload={'recorded_by_role': job.handed_over_actor_role or job.handed_over_by.effective_role})
