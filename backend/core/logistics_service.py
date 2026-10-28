"""Physical logistics evidence, separate from technical and financial decisions."""
import hashlib
import json
import unicodedata

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .logistics_models import CourierReceipt, OutboundJob, PickupRequest
from .logistics_permissions import external_courier, logistics_manager, logistics_operator, logistics_receiver
from .models import Client, Equipment, ServiceRequest, User
from .workflow_events import append_event


def _operator(actor):
    if not logistics_operator(actor):
        raise PermissionDenied('Cette action est réservée à la réception et aux livreurs autorisés.')


def _manager(actor):
    if not logistics_manager(actor):
        raise PermissionDenied('L’affectation des missions est réservée aux responsables SAV.')


def _participant(actor):
    if not logistics_operator(actor) and not (actor.is_authenticated and actor.is_active and actor.effective_role == 'client'):
        raise PermissionDenied('Cet espace est réservé aux clients et à la logistique.')


def _serial(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120 or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValidationError({'serial_number': 'Saisissez une série lisible de 120 caractères maximum.'})
    serial = value.strip()
    return serial.upper() if serial.isascii() else serial


def _hash(data):
    return hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != 'request_key'}, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _lock(value):
    if connection.vendor == 'postgresql':
        key = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [key])


def _courier(identifier, *, client_id=None, internal_only=False):
    courier = User.objects.select_for_update().filter(pk=identifier, role='courier', is_active=True).first()
    if not courier:
        raise ValidationError({'courier': 'Choisissez un compte livreur actif.'})
    if internal_only and courier.courier_kind != 'internal':
        raise ValidationError({'courier': 'Les collectes sont assurées uniquement par un livreur TVM.'})
    if courier.courier_kind == 'client' and courier.client_id != client_id:
        raise ValidationError({'courier': 'Ce livreur client est lié à une autre société.'})
    return courier


def _client(identifier):
    client = Client.objects.filter(pk=identifier).first()
    if not client:
        raise ValidationError({'client': 'Choisissez un client existant.'})
    return client


def _name(user):
    return user.get_full_name() or user.username


def pickups_for(actor):
    _participant(actor)
    records = PickupRequest.objects.select_related('client', 'equipment', 'assigned_courier', 'service_request').filter(
        Q(service_request__isnull=True) | Q(service_request__equipment_id=F('equipment_id'), service_request__equipment__client_id=F('client_id')))
    if actor.effective_role == 'client':
        return records.filter(client_id=actor.client_id).filter(Q(equipment__isnull=True) | Q(equipment__client_id=actor.client_id))
    if external_courier(actor):
        return records.none()
    if actor.role == 'courier':
        return records.filter(assigned_courier=actor).filter(Q(equipment__isnull=True) | Q(equipment__client_id=F('client_id')))
    return records


def outbound_for(actor):
    _participant(actor)
    records = OutboundJob.objects.select_related('client', 'service_request__equipment__client', 'delivery_equipment', 'assigned_courier', 'handed_over_by')
    # A mission never confers access after either unit is moved to another company.
    from django.db.models import F
    records = records.filter(client_id=F('service_request__equipment__client_id'), client_id__exact=F('delivery_equipment__client_id'))
    if actor.effective_role == 'client':
        return records.filter(client_id=actor.client_id)
    if actor.role == 'courier':
        records = records.filter(assigned_courier=actor)
        if external_courier(actor):
            records = records.filter(client_id=actor.client_id)
        return records
    return records


def _open_requests(equipment):
    return ServiceRequest.objects.filter(equipment=equipment).exclude(status='closed').exclude(outbound_job__handed_over_at__isnull=False)


def _candidate(item, import_id):
    return {'product_id': item['id'], 'catalogue_import_id': item.get('import_id') or item.get('snapshot') or import_id,
            'profile': item.get('structure', ''), 'brand': 'Eaton',
            'model': item.get('short_model') or '', 'equipment_name': item.get('product_name', '')}


def lookup(serial_number, **selection):
    serial = _serial(serial_number)
    equipment = Equipment.objects.select_related('client', 'catalogue_product').filter(serial_number__iexact=serial).first()
    result = {'status': 'unknown', 'serial_number': serial, 'equipment': None, 'suggested': None,
              'candidates': [], 'profile_options': [], 'open_requests': [], 'warnings': []}
    if equipment:
        result.update(status='known', equipment={'id': equipment.pk, 'client': {'id': equipment.client_id, 'name': equipment.client.name},
            'brand': equipment.brand, 'model': equipment.model, 'equipment_type': 'ups',
            'equipment_name': equipment.catalogue_product.product_name if equipment.catalogue_product_id else f'Onduleur {equipment.model}'})
        result['open_requests'] = [{'id': row.pk, 'call_number': row.reference, 'client_reference': row.client_reference,
                                    'arrived_at': row.arrived_at, 'status': row.status} for row in _open_requests(equipment)]
        return result
    from .serial_lookup import lookup_serial
    options = {key: selection.get(key) for key in ('profile', 'catalogue_import_id') if selection.get(key)}
    base = lookup_serial(serial, **options)
    candidates = base['product_candidates']
    selected_id = selection.get('product_id')
    if selected_id:
        if selected_id not in {item['id'] for item in candidates}:
            raise ValidationError({'product_id': 'Ce produit n’est pas un candidat compatible avec la série. Utilisez une identification manuelle justifiée.'})
        raw = lookup_serial(serial, product_id=selected_id, **options)
    else:
        raw = base
    result['candidates'] = [_candidate(item, raw['catalogue_import_id']) for item in candidates]
    result['profile_options'] = raw['detection']['profile_options']
    result['warnings'] = raw['warnings']
    selected = raw.get('selected_product')
    if selected and not raw['detection']['requires_profile_choice'] and selected.get('short_model'):
        result['status'] = 'catalogue_match'
        result['suggested'] = {**_candidate(selected, raw['catalogue_import_id']), 'equipment_type': 'ups'}
    elif candidates or raw['detection']['requires_profile_choice']:
        result['status'] = 'ambiguous'
    return result


def _event(record, actor, kind, summary, *, observation='', internal=False, related=None):
    return append_event(equipment=record.equipment, service_request=record, related_equipment=related,
                        actor=actor, kind=kind, summary=summary, observation=observation, is_internal=internal)


def _pickup_event(pickup, actor, kind, summary):
    identifier, revision = pickup.pk, pickup.assignment_revision
    def notify():
        from .outbox_service import notify_pickup_event
        notify_pickup_event(identifier, kind, revision=revision)
    transaction.on_commit(notify, robust=True)
    if pickup.equipment_id:
        append_event(equipment=pickup.equipment, service_request=pickup.service_request, actor=actor,
                     kind=kind, summary=summary, is_internal=False)


@transaction.atomic
def create_pickup(actor, data):
    _participant(actor)
    if actor.role == 'courier':
        raise PermissionDenied('Le client ou le responsable enregistre une demande d’enlèvement.')
    if actor.effective_role == 'client':
        if data.get('client') and data['client'] != actor.client_id:
            raise ValidationError({'client': 'La demande doit concerner votre société.'})
        client = _client(actor.client_id)
    else:
        client = _client(data.get('client'))
    if data.get('pickup_scope', 'direct') == 'end_customer' and not data.get('end_customer_name', '').strip():
        raise ValidationError({'end_customer_name': 'Indiquez le client final chez lequel récupérer le matériel.'})
    digest = _hash(data)
    _lock(f'pickup-key:{actor.pk}:{data["request_key"]}')
    previous = PickupRequest.objects.filter(requested_by=actor, request_key=data['request_key']).first()
    if previous:
        if previous.payload_hash != digest:
            raise ValidationError({'request_key': 'Cette clé a déjà été utilisée pour une autre demande.'})
        if previous.client_id != client.pk:
            raise PermissionDenied('Cette demande ne relève plus de votre société.')
        return previous
    equipment = None
    if data.get('equipment'):
        equipment = Equipment.objects.filter(pk=data['equipment'], client=client).first()
        if not equipment:
            raise NotFound('Équipement indisponible pour cette société.')
        if data.get('serial_number') and _serial(data['serial_number']).casefold() != equipment.serial_number.casefold():
            raise ValidationError({'serial_number': 'La série doit correspondre au matériel sélectionné.'})
        serial = equipment.serial_number
    else:
        serial = _serial(data.get('serial_number'))
        equipment = Equipment.objects.filter(serial_number__iexact=serial).first()
        if equipment and equipment.client_id != client.pk:
            raise ValidationError({'serial_number': 'Cette série n’est pas disponible pour votre société.'})
    if not data.get('fault_description', '').strip() or not data.get('pickup_address', '').strip() or not data.get('contact_name', '').strip():
        raise ValidationError('Renseignez la panne, l’adresse de collecte et le contact.')
    _lock(f'pickup-serial:{serial.casefold()}')
    if PickupRequest.objects.filter(client=client, serial_number__iexact=serial, status__in=['requested', 'assigned', 'collected']).exists():
        raise ValidationError({'serial_number': 'Un enlèvement est déjà en cours pour ce matériel.'})
    pickup = PickupRequest.objects.create(client=client, equipment=equipment, serial_number=serial,
        brand=equipment.brand if equipment else data.get('brand', ''), model=equipment.model if equipment else data.get('model', ''),
        pickup_scope=data.get('pickup_scope', 'direct'), end_customer_name=data.get('end_customer_name', ''),
        client_reference=data.get('client_reference', ''), fault_description=data['fault_description'], pickup_address=data['pickup_address'],
        contact_name=data['contact_name'], contact_phone=data.get('contact_phone', ''), requested_by=actor,
        request_key=data['request_key'], payload_hash=digest)
    _pickup_event(pickup, actor, 'pickup_requested', 'Enlèvement demandé par le client.' if actor.effective_role == 'client' else 'Enlèvement demandé par TVM.')
    return pickup


@transaction.atomic
def assign_pickup(actor, pk, data):
    _manager(actor)
    pickup = pickups_for(actor).select_for_update(of=('self',)).filter(pk=pk).first()
    if not pickup:
        raise NotFound()
    if pickup.status not in ('requested', 'assigned'):
        raise ValidationError('Cette collecte ne peut plus être réaffectée.')
    courier = _courier(data['courier'], client_id=pickup.client_id, internal_only=True)
    if pickup.status == 'assigned' and pickup.assigned_courier_id == courier.pk:
        return pickup
    pickup.assignment_revision += 1
    pickup.assigned_courier = courier
    pickup.assigned_by = actor
    pickup.assigned_at = timezone.now()
    pickup.status = 'assigned'
    pickup.save()
    _pickup_event(pickup, actor, 'pickup_assigned', 'Enlèvement affecté à un livreur.')
    return pickup


@transaction.atomic
def collect_pickup(actor, pk):
    _operator(actor)
    if not logistics_receiver(actor):
        raise PermissionDenied('Les collectes sont assurées par les livreurs TVM.')
    pickup = pickups_for(actor).select_for_update(of=('self',)).filter(pk=pk).first()
    if not pickup:
        raise NotFound()
    if pickup.status == 'collected':
        return pickup
    if pickup.status != 'assigned' or not pickup.assigned_courier_id:
        raise ValidationError('La collecte doit être affectée à un livreur avant son enlèvement.')
    pickup.status = 'collected'
    pickup.collected_at = timezone.now()
    pickup.collected_by = actor
    pickup.save()
    _pickup_event(pickup, actor, 'pickup_collected', 'Matériel collecté chez le client ; réception à l’atelier encore à confirmer.')
    return pickup


@transaction.atomic
def cancel_pickup(actor, pk, data):
    _participant(actor)
    if actor.role == 'courier':
        raise PermissionDenied('L’annulation relève du client ou du responsable.')
    pickup = pickups_for(actor).select_for_update(of=('self',)).filter(pk=pk).first()
    if not pickup:
        raise NotFound()
    reason = data.get('reason', '').strip()
    if not reason:
        raise ValidationError({'reason': 'Indiquez le motif de l’annulation.'})
    if pickup.status == 'cancelled':
        return pickup
    if pickup.status not in ('requested', 'assigned'):
        raise ValidationError('Un matériel déjà collecté ne peut pas être annulé dans cette liste.')
    pickup.status = 'cancelled'
    pickup.cancelled_at = timezone.now()
    pickup.cancellation_reason = reason
    pickup.save()
    _pickup_event(pickup, actor, 'pickup_cancelled', 'Demande d’enlèvement annulée.')
    return pickup


@transaction.atomic
def receive(actor, data):
    _operator(actor)
    if not logistics_receiver(actor):
        raise PermissionDenied('La réception à l’atelier est réservée aux livreurs TVM.')
    serial = _serial(data['serial_number'])
    digest = _hash(data)
    _lock(f'courier-serial:{serial.casefold()}')
    _lock(f'receipt-key:{actor.pk}:{data["request_key"]}')
    receipt = CourierReceipt.objects.select_related('service_request__equipment__client').filter(actor=actor, request_key=data['request_key']).first()
    if receipt:
        if receipt.payload_hash != digest:
            raise ValidationError({'request_key': 'Cette clé de réception correspond à un autre contenu.'})
        if receipt.service_request.equipment.client_id != data['client'] or receipt.service_request.equipment.serial_number.casefold() != serial.casefold():
            raise PermissionDenied('Cette réception ne relève plus de cette société.')
        return receipt
    client = _client(data['client'])
    pickup = None
    if data.get('pickup'):
        pickup = pickups_for(actor).select_for_update(of=('self',)).filter(pk=data['pickup']).first()
        if not pickup:
            raise NotFound('Collecte indisponible.')
        if pickup.client_id != client.pk or pickup.serial_number.casefold() != serial.casefold():
            raise ValidationError({'pickup': 'La collecte, le client et la série doivent correspondre.'})
        if pickup.status == 'received':
            if not pickup.service_request_id:
                raise ValidationError('Cette réception historique doit être vérifiée par un responsable.')
        elif pickup.status != 'collected' and not (logistics_manager(actor) and pickup.status in ('requested', 'assigned')):
            raise ValidationError({'pickup': 'Confirmez d’abord la collecte chez le client.'})
        if pickup.client_reference and data.get('client_reference') and pickup.client_reference != data['client_reference']:
            raise ValidationError({'client_reference': 'Conservez le numéro d’appel transmis dans la collecte.'})
    equipment = Equipment.objects.select_related('client', 'catalogue_product').filter(serial_number__iexact=serial).first()
    created_equipment = False
    if equipment and equipment.client_id != client.pk:
        raise ValidationError({'client': 'Le client choisi ne correspond pas au matériel enregistré.'})
    if not equipment:
        found = lookup(serial, **{key: data.get(key) for key in ('profile', 'product_id', 'catalogue_import_id')})
        suggested = found['suggested']
        if data.get('manual_model'):
            if not data.get('manual_reason', '').strip():
                raise ValidationError({'manual_reason': 'Justifiez l’identification manuelle du modèle.'})
            model, brand, catalogue_id = data['manual_model'].strip(), data.get('manual_brand', '').strip(), None
        elif suggested:
            model, brand, catalogue_id = suggested['model'], suggested['brand'], suggested['product_id']
        else:
            raise ValidationError({'manual_model': 'La série ne détermine pas un modèle unique. Choisissez le produit ou saisissez le modèle avec un motif.'})
        equipment = Equipment.objects.create(client=client, serial_number=serial, model=model, brand=brand,
            catalogue_product_id=catalogue_id, status='maintenance')
        created_equipment = True
    open_cases = _open_requests(equipment).select_for_update(of=('self',))
    if pickup and pickup.status == 'received':
        record = ServiceRequest.objects.select_for_update().get(pk=pickup.service_request_id)
        if record.equipment_id != equipment.pk:
            raise ValidationError({'pickup': 'La collecte et son dossier historique ne correspondent plus. Un responsable doit les vérifier.'})
        if data.get('service_request') and record.pk != data['service_request']:
            raise ValidationError({'service_request': 'Cette collecte est déjà liée à un autre dossier.'})
    elif data.get('service_request'):
        record = open_cases.filter(pk=data['service_request']).first()
        if not record:
            raise ValidationError({'service_request': 'Choisissez un dossier ouvert de ce matériel encore présent à l’atelier.'})
    else:
        rows = list(open_cases[:2])
        if len(rows) > 1:
            raise ValidationError({'service_request': 'Plusieurs appels sont ouverts pour cette série. Choisissez le bon appel.'})
        record = rows[0] if rows else None
    # Lock after the dossier, then re-read ownership/identity before writing.
    # NO KEY UPDATE permits existing FK checks while serializing model saves.
    equipment = Equipment.objects.select_for_update(no_key=True).get(pk=equipment.pk)
    if equipment.client_id != client.pk or equipment.serial_number.casefold() != serial.casefold():
        raise ValidationError({'serial_number': 'L’identité ou le propriétaire du matériel a changé. Relisez sa série avant de confirmer.'})
    if record:
        record.equipment = equipment
    now = timezone.now()
    created_request = record is None
    already_received = bool(record and record.arrived_at)
    if record:
        if not record.arrived_at:
            if record.status != 'new' or record.assigned_technician_id:
                raise ValidationError('Ce dossier a déjà été traité. Un responsable doit vérifier sa réception.')
            incoming_reference = pickup.client_reference if pickup else data.get('client_reference', '')
            if record.client_reference and incoming_reference and record.client_reference != incoming_reference:
                raise ValidationError({'client_reference': 'Ce numéro d’appel client ne correspond pas au dossier sélectionné.'})
            if not record.client_reference:
                record.client_reference = incoming_reference
            if pickup and pickup.pickup_scope == 'end_customer':
                if record.end_customer and record.end_customer != pickup.end_customer_name:
                    raise ValidationError({'pickup': 'Le client final ne correspond pas au dossier sélectionné.'})
                record.end_customer = pickup.end_customer_name
            record.arrived_at = now
            record.delivered_by = 'courier'
            record.courier_name = _name(actor)[:150]
            record.save(update_fields=['arrived_at', 'delivered_by', 'courier_name', 'client_reference', 'end_customer'])
    else:
        record = ServiceRequest.objects.create(equipment=equipment, requested_by=actor, arrived_at=now,
            subject=data.get('subject') or 'Réception d’un onduleur pour réparation',
            description=data.get('fault_description') or (pickup.fault_description if pickup else ''),
            client_reference=(pickup.client_reference if pickup else data.get('client_reference', '')),
            contact_name=pickup.contact_name if pickup else '', contact_phone=pickup.contact_phone if pickup else '',
            end_customer=pickup.end_customer_name if pickup and pickup.pickup_scope == 'end_customer' else '',
            status='new', service_location='workshop', delivered_by='courier', courier_name=_name(actor)[:150])
    if pickup and pickup.status != 'received':
        pickup.status = 'received'
        pickup.equipment = equipment
        pickup.service_request = record
        pickup.received_at = now
        pickup.received_by = actor
        pickup.save()
        _pickup_event(pickup, actor, 'pickup_received', 'Collecte réceptionnée à l’atelier.')
    receipt = CourierReceipt.objects.create(actor=actor, request_key=data['request_key'], payload_hash=digest,
        service_request=record, pickup=pickup, created_request=created_request, created_equipment=created_equipment,
        already_received=already_received, source=data.get('source', 'manual'))
    if not already_received:
        _event(record, actor, 'courier_received', 'Réception physique à l’atelier enregistrée. Dossier non affecté.')
        if created_equipment and data.get('manual_model'):
            _event(record, actor, 'courier_identified', 'Identification manuelle du matériel reçu.',
                   observation=data['manual_reason'], internal=True)
        from .notification_service import notify_received
        transaction.on_commit(lambda: notify_received(record.pk), robust=True)
    return receipt


def canonical_outbound(record):
    """Return the unit physically eligible now; never manufacture technical proof."""
    from .exchange_workflow import get_process, is_exchange_case
    if record.status == 'ready_for_delivery':
        if is_exchange_case(record):
            process = get_process(record)
            if not process or not process.validated_at or not process.ready_at or not process.replacement_equipment_id:
                raise ValidationError('Le remplacement doit être validé et prêt à livrer.')
            unit = process.replacement_equipment
            if unit.client_id != record.equipment.client_id or unit.serial_number != process.replacement_serial_number:
                raise ValidationError('Le matériel validé ne correspond plus au dossier.')
            return unit, 'delivery'
        return record.equipment, 'delivery'
    if record.status == 'return_to_client':
        from .disposition_models import DispositionProcess
        process = DispositionProcess.objects.filter(service_request=record, outcome='nonrepairable').first()
        if not process or not process.diagnosis.strip():
            raise ValidationError('Le retour exige un diagnostic non réparable enregistré.')
        return record.equipment, 'return'
    raise ValidationError('Seuls les dossiers prêts à livrer ou à retourner au client sont affectables.')


def _locked_canonical(record):
    unit, _kind = canonical_outbound(record)
    list(Equipment.objects.select_for_update(no_key=True).filter(pk__in={record.equipment_id, unit.pk}).order_by('pk'))
    record.equipment = Equipment.objects.select_related('client').get(pk=record.equipment_id)
    record._state.fields_cache.pop('exchange_process', None)
    return canonical_outbound(record)


@transaction.atomic
def assign_outbound(actor, data, pk=None):
    _manager(actor)
    if pk:
        identifier = outbound_for(actor).filter(pk=pk).values_list('service_request_id', flat=True).first()
        if not identifier:
            raise NotFound()
    else:
        identifier = data['service_request']
    record = ServiceRequest.objects.select_for_update(of=('self',)).select_related('equipment__client').filter(pk=identifier).first()
    if not record:
        raise NotFound()
    unit, kind = _locked_canonical(record)
    job = OutboundJob.objects.select_for_update().filter(service_request=record).first()
    if job and job.handed_over_at:
        raise ValidationError('Cette mission possède déjà une remise physique. Son historique est conservé.')
    if OutboundJob.objects.filter(delivery_equipment=unit, active=True).exclude(service_request=record).exists():
        raise ValidationError('Cet onduleur est déjà réservé dans une autre mission active.')
    courier = _courier(data['courier'], client_id=record.equipment.client_id)
    values = dict(client=record.equipment.client, delivery_equipment=unit, kind=kind, assigned_courier=courier,
        assigned_by=actor, assigned_at=timezone.now(),
        delivery_address=data.get('delivery_address', job.delivery_address if job else record.equipment.client.address),
        contact_name=data.get('contact_name', job.contact_name if job else record.contact_name or record.equipment.client.contact_name),
        contact_phone=data.get('contact_phone', job.contact_phone if job else record.contact_phone or record.equipment.client.phone))
    if job and job.active and not job.cancelled_at and job.assignment_mode == 'manual' and all(
        getattr(job, key + '_id') == value.pk if key in ('client', 'delivery_equipment', 'assigned_courier') else getattr(job, key) == value
        for key, value in values.items() if key not in ('assigned_by', 'assigned_at')):
        return job
    if job:
        job.assignment_revision += 1
        job.active = True
        job.cancelled_at = None
        job.cancelled_by = None
        job.cancellation_reason = ''
        for key, value in values.items():
            setattr(job, key, value)
        job.save()
    else:
        job = OutboundJob.objects.create(service_request=record, **values)
    job.assignment_mode = 'manual'
    job.routing_source = 'manual'
    job.save(update_fields=['assignment_mode', 'routing_source'])
    _notify_assignment(job)
    _event(record, actor, 'outbound_assigned', 'Retour au client affecté à un livreur.' if kind == 'return' else 'Livraison affectée à un livreur.', related=unit if unit.pk != record.equipment_id else None)
    return job


@transaction.atomic
def handoff(actor, pk, data):
    _operator(actor)
    identifier = outbound_for(actor).filter(pk=pk).values_list('service_request_id', flat=True).first()
    if not identifier:
        raise NotFound()
    record = ServiceRequest.objects.select_for_update(of=('self',)).select_related('equipment__client').get(pk=identifier)
    job = outbound_for(actor).select_for_update(of=('self',)).get(pk=pk)
    recipient = data.get('recipient_name', '').strip()
    if not recipient:
        raise ValidationError({'recipient_name': 'Indiquez le nom de la personne ayant reçu l’onduleur.'})
    if job.handed_over_at:
        if job.recipient_name != recipient:
            raise ValidationError({'recipient_name': 'La remise est déjà enregistrée. Son destinataire ne peut pas être remplacé.'})
        return job
    if not job.active or job.cancelled_at:
        raise ValidationError('Cette mission a été annulée.')
    unit, kind = _locked_canonical(record)
    if job.delivery_equipment_id != unit.pk or job.kind != kind or job.client_id != record.equipment.client_id:
        raise ValidationError('La préparation du dossier a changé. Un responsable doit vérifier la mission avant remise.')
    job.recipient_name = recipient
    job.handed_over_at = timezone.now()
    job.handed_over_by = actor
    job.handed_over_actor_name = _name(actor)
    job.handed_over_actor_role = actor.effective_role
    job.handed_over_serial = unit.serial_number
    job.handed_over_model = unit.model
    job.handed_over_brand = unit.brand
    job.active = False
    job.save()
    _event(record, actor, 'courier_handoff', f'Remise physique enregistrée par TVM à {recipient}.', related=unit if unit.pk != record.equipment_id else None)
    from .notification_service import notify_delivered
    transaction.on_commit(lambda: notify_delivered(job.pk), robust=True)
    return job


@transaction.atomic
def cancel_outbound(actor, pk, data):
    _manager(actor)
    identifier = outbound_for(actor).filter(pk=pk).values_list('service_request_id', flat=True).first()
    if not identifier:
        raise NotFound()
    ServiceRequest.objects.select_for_update().get(pk=identifier)
    job = outbound_for(actor).select_for_update(of=('self',)).get(pk=pk)
    reason = data.get('reason', '').strip()
    if not reason:
        raise ValidationError({'reason': 'Indiquez le motif de l’annulation.'})
    if job.handed_over_at:
        raise ValidationError('Une remise physique déjà enregistrée ne peut pas être annulée.')
    if job.cancelled_at:
        return job
    job.cancelled_at = timezone.now()
    job.cancelled_by = actor
    job.cancellation_reason = reason
    job.active = False
    job.save()
    _event(job.service_request, actor, 'outbound_cancelled', 'Mission logistique annulée avant remise.', observation=reason, internal=True,
           related=job.delivery_equipment if job.delivery_equipment_id != job.service_request.equipment_id else None)
    return job


def guard_logistics_equipment_update(instance, update_fields=None):
    protected = {'serial_number', 'model', 'brand', 'client', 'client_id'}
    if update_fields is not None and not protected.intersection(update_fields):
        return
    previous = Equipment.objects.select_for_update().filter(pk=instance.pk).values('serial_number', 'model', 'brand', 'client_id').first()
    if not previous or not any(previous[field] != getattr(instance, field) for field in previous):
        return
    if OutboundJob.objects.filter(Q(delivery_equipment_id=instance.pk) | Q(service_request__equipment_id=instance.pk), handed_over_at__isnull=False).exists():
        raise ValidationError({'serial_number': 'L’identité d’un matériel déjà remis reste liée à la preuve physique. Créez un nouveau matériel pour une nouvelle identité.'})


def guard_logistics_request_update(instance, update_fields=None):
    if not instance.pk or instance._state.adding:
        return
    previous = ServiceRequest.objects.select_for_update().filter(pk=instance.pk).values('equipment_id', 'status').first()
    if not previous or not OutboundJob.objects.filter(service_request_id=instance.pk, handed_over_at__isnull=False).exists():
        return
    if (update_fields is None or {'equipment', 'equipment_id'}.intersection(update_fields)) and previous['equipment_id'] != instance.equipment_id:
        raise ValidationError({'equipment': 'Le matériel d’un dossier déjà remis reste lié à sa preuve physique.'})
    if (update_fields is None or 'status' in update_fields) and previous['status'] != instance.status and instance.status != 'closed':
        raise ValidationError({'status': 'Une remise physique est déjà enregistrée. Conservez ce dossier et créez un nouvel appel pour une nouvelle opération.'})


def validate_client_routing(instance, update_fields=None):
    """Validate new choices under the same user lock as account conversion."""
    names = {'default_courier', 'internal_courier'}
    if update_fields is not None and not (names | {name + '_id' for name in names}).intersection(update_fields):
        return
    previous = Client.objects.select_for_update().filter(pk=instance.pk).values('default_courier_id', 'internal_courier_id').first() if instance.pk else None
    for field, kind in [('default_courier', 'client'), ('internal_courier', 'internal')]:
        identifier = getattr(instance, field + '_id')
        if not identifier or (previous and previous[field + '_id'] == identifier):
            continue
        courier = User.objects.select_for_update().filter(pk=identifier, role='courier', courier_kind=kind, is_active=True).first()
        if not courier or (kind == 'client' and courier.client_id != instance.pk):
            raise ValidationError({field: 'Choisissez un livreur client actif de cette société.' if kind == 'client' else 'Choisissez un livreur TVM actif.'})


def guard_courier_identity_update(instance, update_fields=None):
    if not instance.pk or instance._state.adding:
        return
    protected = {'role', 'courier_kind', 'client', 'client_id'}
    if update_fields is not None and not protected.intersection(update_fields):
        return
    previous = User.objects.select_for_update().filter(pk=instance.pk).values('role', 'courier_kind', 'client_id').first()
    if not previous or not any(previous[field] != getattr(instance, field) for field in previous):
        return
    referenced = Client.objects.filter(Q(default_courier_id=instance.pk) | Q(internal_courier_id=instance.pk)).exists()
    history = (OutboundJob.objects.filter(Q(assigned_courier_id=instance.pk) | Q(handed_over_by_id=instance.pk)).exists()
               or PickupRequest.objects.filter(Q(assigned_courier_id=instance.pk) | Q(collected_by_id=instance.pk)).exists()
               or CourierReceipt.objects.filter(actor_id=instance.pk).exists()
               or ServiceRequest.objects.filter(arrival_courier_id=instance.pk).exists())
    if referenced or (previous['role'] == 'courier' and history):
        raise ValidationError({'courier_kind': 'Ce livreur est lié à des référents clients ou à des missions conservées. Retirez les référents ; pour changer son type ou sa société après une mission, désactivez ce compte et créez-en un nouveau.'})


def recommended_courier(client, *, lock=False):
    """A live routing suggestion; it does not write a mission on a GET."""
    for field, kind in [('default_courier', 'client'), ('internal_courier', 'internal')]:
        identifier = getattr(client, field + '_id')
        if not identifier:
            continue
        query = User.objects.select_for_update() if lock else User.objects.all()
        query = query.filter(pk=identifier, role='courier', courier_kind=kind, is_active=True)
        query = query.filter(client_id=client.pk) if kind == 'client' else query.filter(client__isnull=True)
        courier = query.first()
        if courier:
            return courier, field
    return None, ''


def _notify_assignment(job):
    identifier, revision = job.pk, job.assignment_revision
    def notify():
        from .outbox_service import notify_transport_assignment
        notify_transport_assignment(identifier, revision=revision)
    transaction.on_commit(notify, robust=True)


@transaction.atomic
def auto_assign_ready(identifier, *, actor=None, reassign_automatic=False):
    record = ServiceRequest.objects.select_for_update().select_related(None).filter(pk=identifier, status='ready_for_delivery').first()
    if not record:
        return None
    job = OutboundJob.objects.select_for_update().filter(service_request=record).first()
    if job and (job.handed_over_at or job.cancelled_at or job.assignment_mode == 'manual' or not reassign_automatic):
        return None
    try:
        unit, kind = _locked_canonical(record)
        client = Client.objects.select_for_update().get(pk=record.equipment.client_id)
        courier, source = recommended_courier(client, lock=True)
        if not courier:
            return None
        if OutboundJob.objects.filter(delivery_equipment=unit, active=True).exclude(service_request=record).exists():
            return None
        if job and job.assigned_courier_id == courier.pk and job.delivery_equipment_id == unit.pk and job.routing_source == source:
            return None
        values = {'client': client, 'delivery_equipment': unit, 'kind': kind, 'assigned_courier': courier,
                  'assigned_by': actor, 'assigned_at': timezone.now(), 'assignment_mode': 'automatic', 'routing_source': source}
        if job:
            for key, value in values.items():
                setattr(job, key, value)
            job.assignment_revision += 1
            job.save()
        else:
            job = OutboundJob.objects.create(service_request=record, delivery_address=client.address,
                contact_name=record.contact_name or client.contact_name, contact_phone=record.contact_phone or client.phone, **values)
        _event(record, actor, 'outbound_auto_assigned', 'Livraison affectée automatiquement selon le référent de la société.', related=unit if unit.pk != record.equipment_id else None)
        _notify_assignment(job)
        return job
    except ValidationError:
        # A technical result remains valid when logistics cannot reserve a unit.
        # The actual ready dossier stays in the manager's unassigned queue.
        return None


def reconcile_ready(actor, data):
    _manager(actor)
    records = ServiceRequest.objects.filter(status='ready_for_delivery')
    if data.get('client'):
        _client(data['client'])
        records = records.filter(equipment__client_id=data['client'])
    result = {'created': [], 'reassigned': [], 'skipped': [], 'errors': []}
    for identifier in records.values_list('pk', flat=True).order_by('pk'):
        previous = OutboundJob.objects.filter(service_request_id=identifier).exists()
        try:
            job = auto_assign_ready(identifier, actor=actor, reassign_automatic=data.get('reassign_automatic', False))
            if job:
                result['reassigned' if previous else 'created'].append(job.pk)
            else:
                result['skipped'].append(identifier)
        except ValidationError as exc:
            result['errors'].append({'service_request': identifier, 'detail': str(exc.detail)})
    return result


def reconcile_dispatch(actor, *, client_id=None, reassign_automatic=False):
    return reconcile_ready(actor, {'client': client_id, 'reassign_automatic': reassign_automatic})
