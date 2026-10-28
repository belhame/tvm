"""One private in-app notice per real, canonical ready transition.

The operation ID identifies an immutable transition occurrence. No reminder
preference, provider connection, scheduled job or GET is needed to create it.
"""
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from .models import OperationEvent, ServiceRequest, User
from .notification_models import InAppNotification


READY_EVENT = 'ready_availability'
READY_TARGET = 'courier_ready_queue'
READY_SOURCES = ('application', 'followup')


def ready_audience(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.role == 'courier':
        return user.courier_kind == 'internal' and user.client_id is None
    return user.effective_role == 'admin'


def _transition(identifier):
    return OperationEvent.objects.filter(pk=identifier, kind='status_changed', status_after='ready_for_delivery',
        service_request__isnull=False, source__in=READY_SOURCES).exclude(status_before='ready_for_delivery').first()


def _latest_occurrence(record):
    return OperationEvent.objects.filter(service_request=record, kind='status_changed', status_after='ready_for_delivery', source__in=READY_SOURCES).exclude(
        status_before='ready_for_delivery').order_by('-pk').values_list('pk', flat=True).first()


def _eligible_record(event):
    from .courier_dispatch import ready_delivery_equipment
    record = ServiceRequest.objects.select_related('equipment__client', 'exchange_process__replacement_equipment').filter(
        pk=event.service_request_id, equipment_id=event.equipment_id, status='ready_for_delivery').first()
    if not record or _latest_occurrence(record) != event.pk:
        return None, None
    try:
        unit = ready_delivery_equipment(record)
    except (ValidationError, NotFound):
        return None, None
    if unit is None or unit.client_id != record.equipment.client_id:
        return None, None
    if unit.pk == record.equipment_id:
        from .disposition_models import DispositionProcess
        verified = DispositionProcess.objects.filter(service_request=record, outcome='repaired', tests_passed=True,
            tested_on__isnull=False, classified_at__isnull=False).exists()
        if not verified:
            return None, None
    return record, unit


@transaction.atomic
def notify_ready_availability(event_id):
    """Safe to retry concurrently for the same occurrence; never calls providers."""
    event = _transition(event_id)
    if event is None:
        return 0
    record, unit = _eligible_record(event)
    if record is None:
        return 0
    recipients = User.objects.select_for_update().filter(is_active=True).filter(
        Q(role='courier', courier_kind='internal', client__isnull=True) | Q(role='admin') | Q(is_superuser=True)).exclude(
            role='courier', courier_kind='client').order_by('pk')
    created = 0
    payload = {'event': READY_EVENT, 'readiness_event': event.pk, 'client_id': unit.client_id,
               'equipment': unit.pk, 'serial_number': unit.serial_number}
    for recipient in recipients.iterator():
        _, was_created = InAppNotification.objects.get_or_create(
            recipient=recipient, dedup_key=f'ready:{record.pk}:{event.pk}', defaults={
                'kind': InAppNotification.Kind.LOGISTICS, 'client_id': unit.client_id,
                'service_request': record, 'created_at': event.created_at,
                'local_date': timezone.localtime(event.created_at).date(), 'payload': payload})
        created += int(was_created)
    return created


def ready_notification_payload(item, user):
    """Availability is rechecked at read time; stored IDs confer no access."""
    unavailable = {'event': READY_EVENT, 'target': None, 'title': 'Disponibilité mise à jour',
                   'body': 'Cet onduleur n’est plus disponible dans la file des prêts à livrer.',
                   'details': {'available': False, 'request': None}}
    if not ready_audience(user):
        return unavailable
    identifier = item.payload.get('readiness_event')
    if type(identifier) is not int:
        return unavailable
    event = _transition(identifier)
    if not event or event.service_request_id != item.service_request_id:
        return unavailable
    record, unit = _eligible_record(event)
    if record is None or item.client_id != unit.client_id or item.payload.get('client_id') != unit.client_id or (
        item.payload.get('equipment') != unit.pk or item.payload.get('serial_number') != unit.serial_number):
        return unavailable
    public = {'id': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
              'client': {'id': unit.client_id, 'name': record.equipment.client.name}, 'equipment': unit.pk,
              'serial_number': unit.serial_number, 'brand': unit.brand, 'model': unit.model}
    return {'event': READY_EVENT, 'target': READY_TARGET, 'title': 'Onduleur prêt à livrer',
            'body': 'Un onduleur est prêt à être livré. Consultez la file des prêts à livrer pour voir son affectation.',
            'service_request': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
            'details': {'available': True, 'request': public}}


@receiver(post_save, sender=OperationEvent, dispatch_uid='notification_ready_availability_transition')
def ready_transition_notice(sender, instance, created, raw=False, **kwargs):
    if raw or not created or instance.source not in READY_SOURCES or instance.kind != 'status_changed' or instance.status_after != 'ready_for_delivery' or (
        instance.status_before == 'ready_for_delivery' or not instance.service_request_id):
        return
    event_id = instance.pk
    transaction.on_commit(lambda: notify_ready_availability(event_id), robust=True)


ASSIGNMENT_EVENT = 'outbound_assignment'
ASSIGNMENT_TARGET = 'courier_missions'


def assignment_audience(user):
    return ready_audience(user) and user.role == 'courier'


def _eligible_assignment(job, revision):
    from .courier_dispatch import ready_delivery_equipment
    from .logistics_service import canonical_outbound
    if job.assignment_revision != revision or not job.active or job.cancelled_at or job.handed_over_at:
        return None
    record = job.service_request
    if job.client_id != record.equipment.client_id or job.delivery_equipment.client_id != job.client_id:
        return None
    try:
        unit, kind = canonical_outbound(record)
        if kind != job.kind:
            return None
        if job.kind == 'delivery':
            unit = ready_delivery_equipment(record)
    except (ValidationError, NotFound):
        return None
    if unit.pk != job.delivery_equipment_id:
        return None
    return unit


@transaction.atomic
def notify_outbound_assignment(job_id, revision):
    """A private instruction to accept the currently assigned TVM mission."""
    from .courier_dispatch import outbound_is_accepted
    from .logistics_models import OutboundJob
    job = OutboundJob.objects.select_for_update(of=('self',)).select_related(
        'service_request__equipment__client', 'delivery_equipment').filter(pk=job_id).first()
    if job is None:
        return 0
    unit = _eligible_assignment(job, revision)
    if unit is None or outbound_is_accepted(job):
        return 0
    courier = User.objects.select_for_update().filter(pk=job.assigned_courier_id, role='courier',
        courier_kind='internal', client__isnull=True, is_active=True).first()
    if courier is None:
        return 0
    _, created = InAppNotification.objects.get_or_create(recipient=courier,
        dedup_key=f'outbound-assignment:{job.pk}:{revision}', defaults={
            'kind': InAppNotification.Kind.LOGISTICS, 'client_id': job.client_id,
            'service_request_id': job.service_request_id, 'created_at': job.assigned_at,
            'local_date': timezone.localtime(job.assigned_at).date(), 'payload': {
                'event': ASSIGNMENT_EVENT, 'job': job.pk, 'revision': revision,
                'client_id': job.client_id, 'equipment': unit.pk, 'serial_number': unit.serial_number}})
    return int(created)


def assignment_notification_payload(item, user):
    from .courier_dispatch import outbound_is_accepted
    from .logistics_models import OutboundJob
    unavailable = {'event': ASSIGNMENT_EVENT, 'target': None, 'title': 'Affectation mise à jour',
                   'body': 'Cette mission n’attend plus votre prise en charge.',
                   'details': {'available': False, 'job': None}}
    if not assignment_audience(user) or item.recipient_id != user.pk:
        return unavailable
    identifier, revision = item.payload.get('job'), item.payload.get('revision')
    if type(identifier) is not int or type(revision) is not int:
        return unavailable
    job = OutboundJob.objects.select_related('service_request__equipment__client', 'delivery_equipment').filter(
        pk=identifier, assigned_courier_id=user.pk, service_request_id=item.service_request_id).first()
    if job is None:
        return unavailable
    unit = _eligible_assignment(job, revision)
    if unit is None or item.client_id != job.client_id or item.payload.get('client_id') != job.client_id or (
        item.payload.get('equipment') != unit.pk or item.payload.get('serial_number') != unit.serial_number):
        return unavailable
    record = job.service_request
    public = {'id': job.pk, 'service_request': record.pk, 'call_number': record.reference,
              'client_reference': record.client_reference, 'client': {'id': job.client_id, 'name': record.equipment.client.name},
              'equipment': unit.pk, 'serial_number': unit.serial_number, 'brand': unit.brand, 'model': unit.model,
              'assignment_revision': job.assignment_revision, 'accepted': outbound_is_accepted(job)}
    return {'event': ASSIGNMENT_EVENT, 'target': ASSIGNMENT_TARGET, 'title': 'Livraison affectée',
            'body': 'Cette mission est prise en charge. Retrouvez-la dans vos missions.' if public['accepted'] else
                    'Une livraison vous est affectée. Confirmez votre prise en charge depuis vos missions.',
            'service_request': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
            'details': {'available': True, 'job': public}}


@receiver(post_save, sender=OperationEvent, dispatch_uid='notification_private_outbound_assignment')
def outbound_assignment_notice(sender, instance, created, raw=False, **kwargs):
    if raw or not created or instance.source not in READY_SOURCES or instance.kind not in ('outbound_assigned', 'outbound_auto_assigned') or not instance.service_request_id:
        return
    from .logistics_models import OutboundJob
    current = OutboundJob.objects.filter(service_request_id=instance.service_request_id).values_list('pk', 'assignment_revision').first()
    if current:
        identifier, revision = current
        transaction.on_commit(lambda: notify_outbound_assignment(identifier, revision), robust=True)
