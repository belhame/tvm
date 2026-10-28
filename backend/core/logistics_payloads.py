"""Minimal projections for logistics; no generic SAV serializer is used."""
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .logistics_models import OutboundJob
from .logistics_permissions import external_courier, logistics_manager, logistics_operator, logistics_receiver
from .logistics_service import canonical_outbound, outbound_for, pickups_for, recommended_courier, _manager, _name
from .models import Client, ServiceRequest, User


def _client(client):
    return {'id': client.pk, 'name': client.name}


def request_payload(record):
    unit = record.equipment
    return {'id': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
            'serial_number': unit.serial_number, 'brand': unit.brand, 'model': unit.model,
            'equipment_type': 'ups', 'equipment_name': unit.catalogue_product.product_name if unit.catalogue_product_id else f'Onduleur {unit.model}',
            'client': _client(unit.client), 'arrived_at': record.arrived_at, 'status': record.status}


def receipt_payload(receipt):
    return {'receipt_id': receipt.pk, 'created_request': receipt.created_request, 'created_equipment': receipt.created_equipment,
            'already_received': receipt.already_received, 'request': request_payload(receipt.service_request)}


def pickup_payload(pickup, actor):
    manager = logistics_manager(actor)
    courier = actor.role == 'courier' and pickup.assigned_courier_id == actor.pk
    client = actor.effective_role == 'client' and pickup.client_id == actor.client_id
    return {'id': pickup.pk, 'status': pickup.status, 'client': _client(pickup.client), 'equipment': pickup.equipment_id,
        'serial_number': pickup.serial_number, 'brand': pickup.brand, 'model': pickup.model,
        'pickup_scope': pickup.pickup_scope, 'end_customer_name': pickup.end_customer_name, 'assignment_revision': pickup.assignment_revision,
        'client_reference': pickup.client_reference, 'fault_description': pickup.fault_description,
        'pickup_address': pickup.pickup_address, 'contact_name': pickup.contact_name, 'contact_phone': pickup.contact_phone,
        'assigned_courier': pickup.assigned_courier_id,
        'assigned_courier_name': _name(pickup.assigned_courier) if pickup.assigned_courier_id else '',
        'requested_at': pickup.requested_at, 'collected_at': pickup.collected_at, 'received_at': pickup.received_at,
        'service_request': pickup.service_request_id, 'call_number': pickup.service_request.reference if pickup.service_request_id else '',
        'can_assign': manager and pickup.status in ('requested', 'assigned'),
        'can_collect': (manager or courier) and pickup.status == 'assigned',
        'can_receive': (manager or courier) and pickup.status == 'collected',
        'can_cancel': (manager or client) and pickup.status in ('requested', 'assigned')}


def outbound_payload(job, actor):
    from .courier_dispatch import outbound_is_accepted
    manager = logistics_manager(actor)
    courier = actor.role == 'courier' and job.assigned_courier_id == actor.pk
    accepted = outbound_is_accepted(job)
    blocking = None
    if job.active:
        try:
            unit, kind = canonical_outbound(job.service_request)
            if unit.pk != job.delivery_equipment_id or kind != job.kind:
                blocking = 'La préparation a changé ; un responsable doit vérifier la mission.'
        except ValidationError:
            blocking = 'Le dossier ne permet plus une remise ; un responsable doit vérifier la mission.'
    unit = job.delivery_equipment
    return {'id': job.pk, 'kind': job.kind, 'status': 'completed' if job.handed_over_at else 'cancelled' if job.cancelled_at else 'assigned',
        'active': job.active, 'assignment_mode': job.assignment_mode, 'routing_source': job.routing_source,
        'accepted': accepted, 'accepted_at': job.accepted_at, 'accepted_revision': job.accepted_revision,
        'accepted_by': job.accepted_by_id if actor.effective_role != 'client' else None,
        'can_accept': courier and actor.is_active and job.active and not job.handed_over_at and not job.cancelled_at and not blocking and not accepted,
        'assignment_revision': job.assignment_revision, 'assigned_courier_kind': job.assigned_courier.courier_kind, 'service_request': job.service_request_id, 'call_number': job.service_request.reference,
        'client_reference': job.service_request.client_reference, 'client': _client(job.client), 'equipment': unit.pk,
        'serial_number': job.handed_over_serial if job.handed_over_at else unit.serial_number,
        'brand': job.handed_over_brand if job.handed_over_at else unit.brand,
        'model': job.handed_over_model if job.handed_over_at else unit.model,
        'delivery_address': job.delivery_address, 'contact_name': job.contact_name, 'contact_phone': job.contact_phone,
        'recipient_name': job.recipient_name, 'handed_over_at': job.handed_over_at,
        'handed_over_by_name': job.handed_over_actor_name, 'handed_over_by_role': job.handed_over_actor_role,
        'assigned_courier': job.assigned_courier_id, 'assigned_courier_name': _name(job.assigned_courier),
        'cancelled_at': job.cancelled_at, 'can_handoff': (manager or (courier and accepted)) and job.active and not blocking,
        'can_assign': manager and job.active, 'can_cancel': manager and job.active,
        'blocking_reason': blocking}


def bootstrap_payload(actor, q=''):
    if not logistics_operator(actor):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied()
    clients = Client.objects.filter(pk=actor.client_id) if external_courier(actor) else Client.objects.all()
    if q:
        clients = clients.filter(name__icontains=q)
    missions = outbound_for(actor).filter(active=True)
    return {'user': {'id': actor.pk, 'username': actor.username, 'first_name': actor.first_name, 'last_name': actor.last_name,
                     'email': actor.email, 'role': actor.effective_role, 'courier_kind': actor.courier_kind, 'client': actor.client_id, 'can_validate_billing': actor.can_validate_billing},
            'capabilities': {'can_receive': logistics_receiver(actor), 'can_lookup': logistics_receiver(actor), 'can_pickups': logistics_receiver(actor), 'can_ready_queue': logistics_manager(actor) or (actor.role == 'courier' and actor.courier_kind == 'internal')},
            'clients': list(clients.values('id', 'name')),
            'couriers': [{'id': user.pk, 'name': _name(user), 'courier_kind': user.courier_kind, 'client': user.client_id} for user in User.objects.filter(role='courier', is_active=True).order_by('username')] if logistics_manager(actor) else [],
            'metrics': {'pickups': pickups_for(actor).filter(status__in=['requested', 'assigned', 'collected']).count(),
                        'ready': missions.filter(kind='delivery').count(), 'returns': missions.filter(kind='return').count()}}


def dispatch_candidates(actor, q=''):
    _manager(actor)
    records = ServiceRequest.objects.select_related('equipment__client', 'exchange_process__replacement_equipment', 'disposition_process').filter(
        status__in=['ready_for_delivery', 'return_to_client']).filter(Q(outbound_job__isnull=True) | Q(outbound_job__handed_over_at__isnull=True))
    if q:
        records = records.filter(Q(reference__icontains=q) | Q(client_reference__icontains=q) | Q(equipment__serial_number__icontains=q) | Q(equipment__client__name__icontains=q))
    rows = []
    for record in records:
        try:
            unit, kind = canonical_outbound(record)
        except ValidationError:
            continue
        courier, source = recommended_courier(record.equipment.client)
        active_job = OutboundJob.objects.filter(service_request=record, active=True).first()
        recommendation = {'id': courier.pk, 'name': _name(courier), 'courier_kind': courier.courier_kind, 'client': courier.client_id} if courier else None
        rows.append({'recommended_courier': recommendation, 'routing_source': active_job.routing_source if active_job else source,
                     'routing_status': 'assigned' if active_job else 'unassigned', 'id': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
                     'client': _client(record.equipment.client), 'equipment': unit.pk, 'serial_number': unit.serial_number,
                     'brand': unit.brand, 'model': unit.model, 'kind': kind, 'status': record.status, 'arrived_at': record.arrived_at})
    return rows
