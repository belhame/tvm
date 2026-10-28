"""Minimal, private SAV reception; no visit, quotation or invoice is created."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import unicodedata

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueWarranty
from .catalogue_service import usable_code
from .models import AuditLog, Client, Equipment, Intervention, ServiceRequest, User, Warranty
from .serial_geometry import decode_profiles
from .serial_lookup import _computed, _coverage, _products, build_warranty_check, product_matches_equipment, warranty_matches
from .workflow_events import actor_context, append_event


class SimpleIntakeConflict(APIException):
    status_code = 409
    default_detail = 'Ce matériel ou cette réception ne peut pas être enregistré sous cette forme. Un responsable doit vérifier le dossier.'


def _allowed(actor):
    return bool(actor and actor.is_active and actor.role not in ('client',) and (
        actor.effective_role in ('admin', 'manager', 'technician') and actor.role != 'courier'
        or actor.role == 'courier' and actor.courier_kind == 'internal'))


def _actor(actor, *, lock=False):
    query = User.objects.select_for_update() if lock else User.objects.all()
    current = query.filter(pk=getattr(actor, 'pk', None)).first()
    if not _allowed(current):
        raise PermissionDenied('La réception SAV est réservée au personnel TVM et aux livreurs TVM actifs.')
    return current


def _serial(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(unicodedata.category(char).startswith('C') for char in value):
        raise ValidationError({'serial_number': 'Saisissez un numéro de série lisible de 120 caractères maximum.'})
    value = value.strip()
    return value.upper() if value.isascii() else value


def _name(actor):
    return actor.get_full_name() or actor.username


def _client(identifier, *, lock=False):
    query = Client.objects.select_for_update(no_key=True) if lock else Client.objects.all()
    company = query.filter(pk=identifier).first()
    if company is None:
        raise ValidationError({'client': 'Choisissez un client existant.'})
    return company


def _equipment(serial, client_id, *, lock=False):
    query = Equipment.objects.select_for_update(no_key=True).select_related('client') if lock else Equipment.objects.all()
    equipment = query.filter(serial_number__iexact=serial).first()
    if equipment is not None and equipment.client_id != client_id:
        raise SimpleIntakeConflict('Ce numéro de série ne peut pas être utilisé pour le client sélectionné. Contactez le responsable SAV.')
    return equipment


def intake_options(actor):
    actor = _actor(actor)
    couriers = User.objects.filter(role='courier', is_active=True).order_by('first_name', 'last_name', 'username', 'pk')
    return {'clients': list(Client.objects.order_by('name', 'pk').values('id', 'name')),
            'couriers': [] if actor.role == 'courier' else [{'id': user.pk, 'name': _name(user), 'courier_kind': user.courier_kind, 'client': user.client_id} for user in couriers],
            'courier_required': actor.role != 'courier',
            'actor_courier': {'id': actor.pk, 'name': _name(actor)} if actor.role == 'courier' else None}


def _coverage_result(status='unknown', *, provisional=True, source='unknown', start=None, end=None, warnings=None, scope='unspecified'):
    active = status == 'active'
    quotation = status in ('expired', 'no_coverage')
    return {'status': status, 'warranty_status': 'warranty' if active else 'quotation',
            'label': 'Garantie en cours' if active else 'Devis / facturable' if quotation else 'Garantie à vérifier',
            'provisional': provisional, 'source': source, 'scope': scope,
            'starts_on': start.isoformat() if isinstance(start, date) else start,
            'ends_on': end.isoformat() if isinstance(end, date) else end,
            'warnings': list(warnings or [])}


def _catalogue(serial):
    """Reuse documented decoding/calendar rules without loading SAV serializers."""
    result = {'product': None, 'model': 'À identifier', 'brand': '', 'manufactured_on': None,
              'coverage': _coverage_result(), 'warnings': [], 'identification': 'unknown',
              'snapshot': None, 'warranty_reference': None, 'computed_warranty': _computed(None),
              'manufacture_date_basis': {}}
    snapshot = CatalogueImport.objects.filter(is_active=True).first()
    result['snapshot'] = snapshot
    if snapshot is None:
        result['warnings'].append('Aucun catalogue actif ne permet une identification automatique ; le matériel sera enregistré À identifier.')
        return result
    geometries = decode_profiles(serial, snapshot.metadata.get('year_tables', []))
    if len(geometries) != 1:
        result['warnings'].append('La série ne détermine pas un profil unique ; aucune référence de modèle ou garantie n’est choisie automatiquement.')
        return result
    geometry = geometries[0]
    result['manufacture_date_basis'] = geometry['manufacture_date_basis']
    result['warnings'].extend(geometry['warnings'])
    products = list(_products(snapshot, geometry['profile'], geometry['segments'].get('product_code'))[:2])
    if len(products) != 1:
        result['warnings'].append('Aucun produit unique n’est établi par cette série ; le modèle reste À identifier sans bloquer la demande.')
        return result
    product = products[0]
    short = product.catalogue_number.strip()
    model = short if usable_code(short) and len(short) <= 120 else product.product_name if len(product.product_name) <= 120 else 'À identifier'
    result.update(product=product, model=model,
        brand=geometry['profile'] if geometry['profile'] in ('Eaton', 'Pulsar', 'Powerware') else '', identification='catalogue')
    if model == 'À identifier':
        result['warnings'].append('La désignation du catalogue dépasse le champ du modèle ; le personnel complétera son identification.')
    manufactured = geometry.get('manufactured_on')
    if manufactured and date.fromisoformat(manufactured) <= timezone.localdate():
        result['manufactured_on'] = date.fromisoformat(manufactured)
    elif manufactured:
        result['warnings'].append('La fabrication calculée est future ; aucune date de fabrication ou garantie active n’est retenue.')
        manufactured = None
    references = warranty_matches(product, CatalogueWarranty.objects.filter(snapshot=snapshot))
    if len(references) != 1 or references[0][1] == 'related_manual' or references[0][0].scope not in ('unspecified', 'electronics_and_batteries'):
        result['coverage']['warnings'].append('La portée globale ou la durée de garantie ne sont pas uniques ; une garantie de composant n’est pas étendue à tout l’onduleur.')
        return result
    reference, match_type = references[0]
    result['warranty_reference'] = {'scope': reference.scope, 'source_sheet': reference.source_sheet,
        'source_row': reference.source_row, 'match_type': match_type}
    computed = _computed(manufactured, {'id': reference.pk, 'duration_months': reference.duration_months})
    result['computed_warranty'] = computed
    status = computed['coverage_status']
    status = 'no_coverage' if status == 'not_covered' else status
    warnings = ['Orientation fondée sur le catalogue et la règle TVM ; la prise en charge commerciale reste à confirmer.']
    if match_type == 'generation_family':
        warnings.append('La génération ne possède pas de garantie distincte dans le fichier ; la durée de la gamme générale est une estimation à confirmer.')
    if geometry['manufacture_date_basis'].get('reconstructed'):
        warnings.append('La date de fabrication est reconstituée selon la règle documentée, sans certifier un jour réel de fabrication.')
    if reference.scope == 'unspecified' and status == 'active':
        warnings.append('Garantie en cours selon les dates enregistrées ; étendue de couverture à confirmer.')
    result['coverage'] = _coverage_result(status, provisional=status not in ('expired', 'no_coverage'), source='catalogue_estimate',
                                         start=computed['starts_on'], end=computed['ends_on'], warnings=warnings, scope=reference.scope)
    return result


def _recorded_coverage(equipment, suggestion):
    rows = list(Warranty.objects.filter(equipment=equipment))
    global_rows = [row for row in rows if row.scope in ('unspecified', 'electronics_and_batteries')]
    today = timezone.localdate()
    active = [row for row in global_rows if row.starts_on <= today <= row.ends_on]
    if active:
        explicit = [row for row in active if row.scope == 'electronics_and_batteries']
        candidates = explicit or active
        warnings = [] if explicit else ['Garantie en cours selon les dates enregistrées ; étendue de couverture à confirmer.']
        if len(candidates) > 1:
            warnings.append('Plusieurs périodes globales sont actives ; aucune durée maximale n’est choisie automatiquement.')
        return _coverage_result('active', provisional=not bool(explicit), source='recorded_global_warranty',
            start=candidates[0].starts_on if len(candidates) == 1 else None,
            end=candidates[0].ends_on if len(candidates) == 1 else None, warnings=warnings,
            scope='electronics_and_batteries' if explicit else 'unspecified')
    if global_rows:
        future = [row for row in global_rows if row.starts_on > today]
        if future:
            return _coverage_result('not_started', source='recorded_global_warranty',
                start=future[0].starts_on if len(future) == 1 else None, end=future[0].ends_on if len(future) == 1 else None,
                warnings=['La garantie enregistrée n’a pas encore commencé ; vérifiez la prise en charge à la date de réception.'])
        return _coverage_result('expired', provisional=False, source='recorded_global_warranty',
            start=global_rows[0].starts_on if len(global_rows) == 1 else None,
            end=global_rows[0].ends_on if len(global_rows) == 1 else None)
    if rows:
        return _coverage_result(warnings=['Les garanties enregistrées concernent des composants. Elles ne prouvent pas une garantie globale de tout l’onduleur.'])
    if equipment.warranty_until:
        status = _coverage(None, equipment.warranty_until, today)
        return _coverage_result(status, provisional=status == 'active', source='equipment_global_end', end=equipment.warranty_until,
            warnings=['Garantie en cours selon les dates enregistrées ; étendue de couverture à confirmer.'] if status == 'active' else [])
    product = suggestion['product']
    if product_matches_equipment(product, equipment, suggestion['model']):
        return suggestion['coverage']
    return _coverage_result(warnings=['Aucune date globale exploitable n’est enregistrée ; la garantie doit être vérifiée.'])


def _request_mini(record):
    return {'id': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
            'status': record.status, 'arrived_at': record.arrived_at.isoformat() if record.arrived_at else None,
            'return_flag': record.return_flag,
            'arrival_courier': {'id': record.arrival_courier_id, 'name': record.courier_name} if record.arrival_courier_id else None}


def _return_history(equipment, client_id):
    if equipment is None:
        return {'is_return': False, 'matches': [], 'truncated': False}
    from .exchange_models import ExchangeProcess
    direct = ServiceRequest.objects.filter(equipment=equipment, equipment__client_id=client_id)
    exchange_ids = ExchangeProcess.objects.filter(replacement_equipment=equipment, validated_at__isnull=False,
        service_request__equipment__client_id=client_id).values_list('service_request_id', flat=True)
    visit_ids = Intervention.objects.filter(kind='exchange', status='completed', replacement_equipment=equipment,
        service_request__equipment__client_id=client_id).values_list('service_request_id', flat=True)
    rows = ServiceRequest.objects.filter(Q(pk__in=direct.values('pk')) | Q(pk__in=exchange_ids) | Q(pk__in=visit_ids)).select_related('equipment').order_by('-created_at', '-pk')
    matches = []
    for record in rows[:21]:
        matches.append({'id': record.pk, 'call_number': record.reference, 'client_reference': record.client_reference,
            'created_at': record.created_at.isoformat(), 'arrived_at': record.arrived_at.isoformat() if record.arrived_at else None,
            'serial_number': record.equipment.serial_number, 'relation': 'same_equipment' if record.equipment_id == equipment.pk else 'replacement'})
    return {'is_return': bool(matches), 'matches': matches[:20], 'truncated': len(matches) > 20}


def _inspect(company, serial, equipment=None):
    suggestion = _catalogue(serial)
    history = _return_history(equipment, company.pk)
    coverage = _recorded_coverage(equipment, suggestion) if equipment else suggestion['coverage']
    warnings = list(suggestion['warnings']) if equipment is None else []
    warnings.extend(coverage['warnings'])
    if coverage['status'] == 'unknown':
        warnings.append('Garantie à vérifier : orientation Devis / facturable provisoire, sans émission de devis ni facture.')
    product = suggestion['product']
    identity_consistent = product_matches_equipment(product, equipment, suggestion['model'])
    if equipment and product and not identity_consistent:
        warnings.append('Le modèle enregistré diffère de la référence décodée. Vérifiez l’étiquette ; aucune référence catalogue ni garantie calculée n’est attribuée automatiquement au matériel réel.')
    product_data = {key: getattr(product, key) for key in ('range_name', 'product_name', 'version',
        'manufacturing_part_number', 'catalogue_number', 'source_sheet', 'source_row', 'structure')} if product else None
    summary_computed = {**suggestion['computed_warranty'], 'coverage_status': coverage['status'], 'scope': coverage['scope'],
        'starts_on': coverage['starts_on'], 'ends_on': coverage['ends_on']}
    recorded = coverage['source'] in ('recorded_global_warranty', 'equipment_global_end')
    if recorded or not identity_consistent:
        summary_computed['duration_months'] = None
    manufactured = equipment.manufactured_on if equipment and equipment.manufactured_on else suggestion['manufactured_on'] if identity_consistent else None
    manufacture_basis = {'type': 'recorded', 'precision': 'day', 'reconstructed': False,
        'source': 'Date enregistrée sur l’équipement.'} if equipment and equipment.manufactured_on else suggestion['manufacture_date_basis'] if identity_consistent else {}
    warranty_check = build_warranty_check(product=product_data, snapshot=suggestion['snapshot'],
        computed=summary_computed, manufactured_on=manufactured.isoformat() if manufactured else None,
        reference=suggestion['warranty_reference'] if identity_consistent else None, recorded=recorded,
        recorded_model=equipment.model if equipment else '', recorded_brand=equipment.brand if equipment else '',
        identity_consistent=identity_consistent, manufacture_date_basis=manufacture_basis, warnings=warnings)
    open_request = ServiceRequest.objects.filter(equipment=equipment).exclude(status='closed').first() if equipment else None
    return {'serial_number': serial, 'client': {'id': company.pk, 'name': company.name},
        'equipment': {'id': equipment.pk if equipment else None, 'serial_number': equipment.serial_number if equipment else serial,
            'brand': equipment.brand if equipment else suggestion['brand'], 'model': equipment.model if equipment else suggestion['model'],
            'known': equipment is not None, 'identification': 'recorded' if equipment else suggestion['identification']},
        'coverage': coverage, 'warranty_check': warranty_check, 'return_history': history,
        'open_request': _request_mini(open_request) if open_request else None, 'warnings': list(dict.fromkeys(warnings))}, suggestion


def lookup_intake(actor, *, client, serial_number):
    _actor(actor)
    company = _client(client)
    serial = _serial(serial_number)
    equipment = _equipment(serial, company.pk)
    result, _ = _inspect(company, serial, equipment)
    return result


def _digest(data):
    return hashlib.sha256(('simple-sav-intake-v1:' + json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)).encode()).hexdigest()


def _replay(record, actor, digest):
    saved = record.intake_data or {}
    if saved.get('kind') != 'simple_sav' or saved.get('actor_id') != actor.pk or saved.get('payload_hash') != digest:
        raise SimpleIntakeConflict('Cette clé de réception a déjà été utilisée. Rechargez le formulaire avant de créer une nouvelle demande.')
    result = deepcopy(saved['response'])
    result['created'] = False
    return result


def _open_conflict(record):
    error = SimpleIntakeConflict()
    # APIException normalizes nested values to ErrorDetail strings. This
    # authorized minimal projection must retain numeric IDs and booleans.
    error.detail = {'detail': 'Un appel SAV est déjà ouvert pour ce matériel. Consultez cet appel sans réinitialiser sa réception.', 'open_request': _request_mini(record)}
    raise error


@transaction.atomic
def _create(actor, data):
    from .logistics_service import _lock
    serial = _serial(data['serial_number'])
    _lock(f'courier-serial:{serial.casefold()}')
    _lock(f'simple-sav-key:{data["request_key"]}')
    actor = _actor(actor)
    # Replays are read-only and must not take request/account locks in the
    # opposite order to assignment or technical follow-up.
    previous = ServiceRequest.objects.filter(intake_key=data['request_key']).first()
    if previous:
        replay_courier = data.get('arrival_courier') or actor.pk
        replay_input = {'client': data['client'], 'serial_number': serial.casefold(), 'arrival_courier': replay_courier,
                        'client_reference': data.get('client_reference', ''), 'description': data.get('description', '')}
        return _replay(previous, actor, _digest(replay_input))
    company = _client(data['client'])
    equipment = _equipment(serial, company.pk, lock=True)
    if equipment:
        opened = ServiceRequest.objects.filter(equipment=equipment).exclude(status='closed').first()
        if opened:
            _actor(actor)  # Fresh authorization, without an account row lock.
            _open_conflict(opened)
    # Match the established advanced-intake order: equipment/client first,
    # account checks second. A missing unit has no equipment row to lock.
    company = equipment.client if equipment else _client(company.pk, lock=True)
    identifiers = {getattr(actor, 'pk', None), data.get('arrival_courier')}
    users = {user.pk: user for user in User.objects.select_for_update(no_key=True).filter(pk__in=identifiers).order_by('pk')}
    actor = users.get(getattr(actor, 'pk', None))
    if not _allowed(actor):
        raise PermissionDenied('La réception SAV est réservée aux utilisateurs TVM actifs.')
    supplied_courier = data.get('arrival_courier')
    if actor.role == 'courier':
        if supplied_courier is not None and supplied_courier != actor.pk:
            raise ValidationError({'arrival_courier': 'Le livreur connecté est automatiquement le livreur de cette réception.'})
        courier = actor
    else:
        courier = users.get(supplied_courier)
        if not courier or not courier.is_active or courier.role != 'courier' or (courier.courier_kind == 'client' and courier.client_id != company.pk):
            raise ValidationError({'arrival_courier': 'Choisissez un livreur TVM actif ou un livreur actif du client sélectionné.'})
    canonical = {'client': company.pk, 'serial_number': serial.casefold(), 'arrival_courier': courier.pk,
                 'client_reference': data.get('client_reference', ''), 'description': data.get('description', '')}
    digest = _digest(canonical)
    result, suggestion = _inspect(company, serial, equipment)
    if equipment is None:
        equipment = Equipment.objects.create(client=company, serial_number=serial, model=suggestion['model'],
            brand=suggestion['brand'], catalogue_product=suggestion['product'], manufactured_on=suggestion['manufactured_on'], status='maintenance')
    now = timezone.now()
    with actor_context(actor):
        record = ServiceRequest.objects.create(equipment=equipment, requested_by=actor,
            intake_key=data['request_key'], subject=f'Réception SAV — {serial}', description=canonical['description'],
            client_reference=canonical['client_reference'], arrived_at=now, status='new', assigned_technician=None,
            arrival_courier=courier, courier_name=_name(courier)[:150], delivered_by='courier', service_location='workshop',
            return_flag=result['return_history']['is_return'], warranty_status=result['coverage']['warranty_status'])
        append_event(equipment=equipment, service_request=record, actor=actor, kind='simple_sav_received',
            summary='Réception SAV simple enregistrée ; dossier non affecté.', is_internal=True)
        AuditLog.objects.create(actor=actor, action='simple_sav_intake', resource='servicerequest', resource_id=str(record.pk))
    result['equipment'].update(id=equipment.pk)
    response = {'created': True, 'request': _request_mini(record), **{key: result[key] for key in ('equipment', 'coverage', 'warranty_check', 'return_history', 'warnings')}}
    record.intake_data = {'kind': 'simple_sav', 'actor_id': actor.pk, 'payload_hash': digest,
        'summary': {'coverage': deepcopy(result['coverage']), 'return_history': deepcopy(result['return_history'])},
        'response': deepcopy(response)}
    record.save(update_fields=['intake_data'])
    return response


def create_intake(actor, data):
    _actor(actor)
    try:
        return _create(actor, data)
    except IntegrityError as exc:
        # A concurrent non-simple import can race on the unique serial/key.
        # The transaction is already rolled back; report only owned records.
        serial = _serial(data['serial_number'])
        equipment = _equipment(serial, data['client'])
        if equipment:
            opened = ServiceRequest.objects.filter(equipment=equipment).exclude(status='closed').first()
            if opened:
                _open_conflict(opened)
        raise SimpleIntakeConflict('Une réception concurrente a été enregistrée. Rechargez la fiche du matériel.') from exc
