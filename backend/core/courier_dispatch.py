"""Shared TVM readiness board, explicit claiming and current mission acceptance."""
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .logistics_models import OutboundJob
from .logistics_permissions import logistics_manager, logistics_operator
from .models import Intervention, OperationEvent, ServiceRequest, User
from .workflow_events import append_event


MAX_OUTBOUND_REVISION = 2147483647
_ACCEPT_TOKEN = object()
ACCEPT_FIELDS = {'accepted_at', 'accepted_by_id', 'accepted_revision'}
ASSIGNMENT_IDENTITY = {'assigned_courier_id', 'delivery_equipment_id', 'client_id', 'kind',
                       'delivery_address', 'contact_name', 'contact_phone', 'cancelled_at'}


class DispatchConflict(APIException):
    status_code = 409
    default_detail = 'La mission a changé ou a été réservée. Actualisez la file avant de confirmer.'


def expected_revision(value):
    if type(value) is not int or not 0 <= value <= MAX_OUTBOUND_REVISION:
        raise ValidationError({'expected_revision': 'Une révision entière positive ou nulle est obligatoire.'})
    return value


def outbound_is_accepted(job):
    return bool(job.accepted_at and job.accepted_by_id == job.assigned_courier_id
                and job.accepted_revision == job.assignment_revision)


def fresh_operator(actor, *, lock=True):
    query = User.objects.select_for_update() if lock and transaction.get_connection().in_atomic_block else User.objects.all()
    fresh = query.filter(pk=getattr(actor, 'pk', None)).first()
    if not logistics_operator(fresh):
        raise PermissionDenied('Cette action est réservée aux comptes logistiques actifs.')
    return fresh


def require_outbound_acceptance(actor, job):
    actor = fresh_operator(actor)
    if logistics_manager(actor):
        return actor
    if actor.role != 'courier' or job.assigned_courier_id != actor.pk or (actor.courier_kind == 'client' and actor.client_id != job.client_id):
        raise PermissionDenied('Cette mission n’est pas affectée à votre compte.')
    if not outbound_is_accepted(job):
        raise PermissionDenied('Confirmez votre prise en charge de cette mission avant de continuer.')
    return actor


def prepare_outbound_save(instance, update_fields=None):
    """Every assignment identity/revision change invalidates old acceptance."""
    fields = set(update_fields) if update_fields is not None else None
    old = OutboundJob.objects.select_for_update().filter(pk=instance.pk).first() if instance.pk and not instance._state.adding else None
    confirming = getattr(instance, '_outbound_accept_token', None) is _ACCEPT_TOKEN
    if old is None:
        if any(getattr(instance, name) is not None for name in ACCEPT_FIELDS):
            raise ValidationError({'acceptance': 'Confirmez la prise en charge après avoir créé la mission.'})
        return set()
    written = lambda name: fields is None or name in fields or name.removesuffix('_id') in fields
    changed = any(written(name) and getattr(instance, name) != getattr(old, name) for name in ASSIGNMENT_IDENTITY)
    revision_written = written('assignment_revision') and instance.assignment_revision != old.assignment_revision
    if changed or revision_written:
        if old.assignment_revision >= MAX_OUTBOUND_REVISION:
            raise ValidationError({'assignment_revision': 'La révision de la mission a atteint sa limite.'})
        if instance.assignment_revision not in (old.assignment_revision, old.assignment_revision + 1):
            raise DispatchConflict()
        instance.assignment_revision = old.assignment_revision + 1
        for name in ACCEPT_FIELDS:
            setattr(instance, name, None)
        return ACCEPT_FIELDS | {'assignment_revision'}
    for name in ACCEPT_FIELDS:
        if confirming:
            continue
        if written(name) and getattr(instance, name) != getattr(old, name):
            raise ValidationError({'acceptance': 'Utilisez la confirmation de la mission courante.'})
        setattr(instance, name, getattr(old, name))
    return set()


def ready_delivery_equipment(record):
    from .logistics_service import canonical_outbound
    if record.status != 'ready_for_delivery':
        raise ValidationError('Ce dossier n’est pas prêt à être livré.')
    job = getattr(record, 'outbound_job', None)
    if job and job.handed_over_at:
        raise ValidationError('La remise physique de ce matériel est déjà enregistrée.')
    unit, kind = canonical_outbound(record)
    if kind != 'delivery' or unit.client_id != record.equipment.client_id:
        raise ValidationError('Le matériel à livrer n’est plus cohérent avec ce dossier.')
    if unit.pk != record.equipment_id:
        process = record.exchange_process
        if unit.model != process.replacement_model or unit.brand != process.replacement_brand:
            raise ValidationError('L’identité du remplacement validé a changé.')
    return unit


def _board_actor(actor):
    if not logistics_manager(actor) and not (logistics_operator(actor) and actor.role == 'courier' and actor.courier_kind == 'internal'):
        raise PermissionDenied('La file partagée est réservée aux livreurs TVM et aux responsables.')


def ready_queue(actor, q=''):
    actor = fresh_operator(actor, lock=False)
    _board_actor(actor)
    records = ServiceRequest.objects.select_related('equipment__client', 'exchange_process__replacement_equipment', 'outbound_job__assigned_courier').filter(status='ready_for_delivery').annotate(
        _exchange_legacy=Exists(Intervention.objects.filter(service_request_id=OuterRef('pk'), kind='exchange')),
        _exchange_history=Exists(OperationEvent.objects.filter(service_request_id=OuterRef('pk'), status_after='exchange')),
    )
    if q:
        records = records.filter(Q(reference__icontains=q) | Q(client_reference__icontains=q) | Q(equipment__serial_number__icontains=q) | Q(equipment__client__name__icontains=q) | Q(exchange_process__replacement_serial_number__icontains=q))
    candidates = []
    for record in records.order_by('created_at', 'pk'):
        try:
            unit = ready_delivery_equipment(record)
        except ValidationError:
            continue
        candidates.append((record, unit))
    reservations = dict(OutboundJob.objects.filter(active=True, delivery_equipment_id__in={unit.pk for record, unit in candidates}).values_list('delivery_equipment_id', 'service_request_id'))
    result = []
    for record, unit in candidates:
        job = getattr(record, 'outbound_job', None)
        reserved = bool(job and job.active and not job.cancelled_at)
        elsewhere = unit.pk in reservations and reservations[unit.pk] != record.pk
        result.append({
            'id': record.pk, 'service_request': record.pk, 'job': job.pk if job else None,
            'expected_revision': job.assignment_revision if job else 0,
            'assignment_revision': job.assignment_revision if job else 0,
            'call_number': record.reference, 'client_reference': record.client_reference,
            'client': {'id': record.equipment.client_id, 'name': record.equipment.client.name},
            'equipment': unit.pk, 'serial_number': unit.serial_number, 'brand': unit.brand, 'model': unit.model,
            'status': record.status, 'kind': 'delivery', 'routing_status': 'reserved' if reserved or elsewhere else 'available',
            'assigned_courier': job.assigned_courier_id if reserved else None,
            'assigned_courier_name': (job.assigned_courier.get_full_name() or job.assigned_courier.username) if reserved else '',
            'assigned_courier_kind': job.assigned_courier.courier_kind if reserved else None,
            'accepted': outbound_is_accepted(job) if reserved else False,
            'accepted_at': job.accepted_at if reserved else None,
            'accepted_revision': job.accepted_revision if reserved else None,
            'can_claim': actor.role == 'courier' and actor.courier_kind == 'internal' and not reserved and not elsewhere,
            'blocking_reason': 'Matériel réservé dans une autre mission.' if elsewhere else '',
        })
    return result


def _set_accepted(job, actor):
    job.accepted_at = timezone.now()
    job.accepted_by = actor
    job.accepted_revision = job.assignment_revision
    job._outbound_accept_token = _ACCEPT_TOKEN
    try:
        job.save(update_fields=['accepted_at', 'accepted_by', 'accepted_revision'])
    finally:
        del job._outbound_accept_token
    append_event(equipment=job.service_request.equipment, service_request=job.service_request,
                 related_equipment=job.delivery_equipment if job.delivery_equipment_id != job.service_request.equipment_id else None,
                 actor=actor, kind='outbound_accepted', summary='Prise en charge de la livraison confirmée par le livreur affecté.', is_internal=True)


@transaction.atomic
def claim_ready(actor, identifier, revision):
    from .logistics_service import _locked_canonical, _notify_assignment
    actor = fresh_operator(actor, lock=False)
    if actor.role != 'courier' or actor.courier_kind != 'internal':
        raise PermissionDenied('Seul un livreur TVM actif peut prendre une livraison dans la file partagée.')
    revision = expected_revision(revision)
    record = ServiceRequest.objects.select_for_update().filter(pk=identifier).first()
    if record is None:
        raise NotFound()
    job = OutboundJob.objects.select_for_update().filter(service_request=record).first()
    if (job.assignment_revision if job else 0) != revision:
        raise DispatchConflict()
    if job and (job.handed_over_at or (job.active and not job.cancelled_at)):
        raise DispatchConflict('Cette mission est déjà réservée. Seul un responsable peut la réaffecter.')
    unit, kind = _locked_canonical(record)
    ready_delivery_equipment(record)
    actor = fresh_operator(actor)
    if actor.role != 'courier' or actor.courier_kind != 'internal':
        raise PermissionDenied('Seul un livreur TVM actif peut prendre une livraison dans la file partagée.')
    if OutboundJob.objects.filter(delivery_equipment_id=unit.pk, active=True).exclude(service_request_id=record.pk).exists():
        raise DispatchConflict('Cet onduleur est déjà réservé dans une autre mission.')
    values = {'client': record.equipment.client, 'delivery_equipment': unit, 'kind': kind,
              'assigned_courier': actor, 'assigned_by': actor, 'assigned_at': timezone.now(),
              'assignment_mode': 'manual', 'routing_source': 'manual', 'active': True,
              'cancelled_at': None, 'cancelled_by': None, 'cancellation_reason': ''}
    if job:
        for name, value in values.items():
            setattr(job, name, value)
        job.assignment_revision += 1
        job._dispatch_actor = actor
        job._dispatch_change_reason = 'La mission a été reprise dans la file partagée.'
        job.save()
    else:
        job = OutboundJob.objects.create(service_request=record, delivery_address=record.equipment.client.address,
            contact_name=record.contact_name or record.equipment.client.contact_name,
            contact_phone=record.contact_phone or record.equipment.client.phone, **values)
    _set_accepted(job, actor)
    append_event(equipment=record.equipment, service_request=record, actor=actor,
                 related_equipment=unit if unit.pk != record.equipment_id else None, kind='outbound_claimed',
                 summary='Livraison prise volontairement et confirmée par un livreur TVM.', is_internal=True)
    _notify_assignment(job)
    return job


@transaction.atomic
def accept_outbound(actor, identifier, revision, accept):
    from .logistics_service import _locked_canonical, outbound_for
    revision = expected_revision(revision)
    if type(accept) is not bool:
        raise ValidationError({'accept': 'Utilisez un vrai booléen JSON.'})
    request_id = outbound_for(actor).filter(pk=identifier).values_list('service_request_id', flat=True).first()
    if request_id is None:
        raise NotFound()
    record = ServiceRequest.objects.select_for_update().get(pk=request_id)
    job = OutboundJob.objects.select_for_update().get(pk=identifier)
    if job.assignment_revision != revision:
        raise DispatchConflict()
    if not job.active or job.handed_over_at or job.cancelled_at:
        raise ValidationError('Cette mission n’attend plus de prise en charge.')
    unit, kind = _locked_canonical(record)
    actor = fresh_operator(actor)
    if actor.role != 'courier' or job.assigned_courier_id != actor.pk or (actor.courier_kind == 'client' and actor.client_id != job.client_id):
        raise PermissionDenied('Seul le livreur actuellement affecté peut confirmer cette mission.')
    if unit.pk != job.delivery_equipment_id or kind != job.kind or job.client_id != record.equipment.client_id:
        raise ValidationError('La préparation du dossier a changé. Faites vérifier la mission.')
    if not accept or outbound_is_accepted(job):
        return job
    _set_accepted(job, actor)
    return job
