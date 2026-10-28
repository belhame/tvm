"""Explicit exchange preparation, technical approval, readiness and billing.

All writes lock the dossier first. A serial is reserved once, and remains tied
to the original equipment; no stock movement, delivery or ERP invoice is faked.
"""
import hashlib
import unicodedata

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .exchange_models import ExchangeProcess
from .models import AuditLog, Equipment, Intervention, OperationEvent, ServiceRequest
from .permissions import can_validate_billing
from .request_assignment import require_accepted_assignment
from .workflow import technician_can_write
from .workflow_events import append_event, current_actor


def exchange_related(queryset):
    from .logistics_models import OutboundJob
    return queryset.select_related(
        'exchange_process__replacement_equipment', 'exchange_process__validated_by',
        'exchange_process__ready_by', 'exchange_process__billing_validated_by',
    ).annotate(
        _exchange_legacy=Exists(Intervention.objects.filter(service_request_id=OuterRef('pk'), kind='exchange')),
        _exchange_history=Exists(OperationEvent.objects.filter(service_request_id=OuterRef('pk'), status_after='exchange')),
        _logistics_handed_over=Exists(OutboundJob.objects.filter(service_request_id=OuterRef('pk'), handed_over_at__isnull=False)),
    )


def workflow_permission_hints(queryset, actor):
    """Capabilities now use the current accepted assignment, never old visits."""
    return queryset


def get_process(service_request):
    try:
        return service_request.exchange_process
    except ObjectDoesNotExist:
        return None


def is_exchange_case(service_request, previous_status=None):
    if service_request.status == 'exchange' or previous_status == 'exchange':
        return True
    if get_process(service_request) is not None:
        return True
    if hasattr(service_request, '_exchange_legacy') and hasattr(service_request, '_exchange_history'):
        return service_request._exchange_legacy or service_request._exchange_history
    return service_request.interventions.filter(kind='exchange').exists() or service_request.operation_events.filter(status_after='exchange').exists()


def register_exchange_request(service_request, previous_status=None):
    if service_request.status == 'exchange' or previous_status == 'exchange':
        ExchangeProcess.objects.get_or_create(service_request_id=service_request.pk)
        service_request._state.fields_cache.pop('exchange_process', None)
    if service_request.status == 'closed':
        ExchangeProcess.objects.filter(service_request_id=service_request.pk, reservation_active=True).update(reservation_active=False)
        service_request._state.fields_cache.pop('exchange_process', None)


def guard_request_update(instance, update_fields=None):
    """Model-level guard also covers timeline and admin writes, never old reads."""
    old = None
    if instance.pk and not instance._state.adding:
        old = ServiceRequest.objects.select_for_update().filter(pk=instance.pk).only('status', 'equipment_id').first()
    old_status = old.status if old else None
    if old and old.equipment_id != instance.equipment_id and is_exchange_case(old):
        raise ValidationError({'equipment': 'Le matériel d’origine d’un échange reste lié à son dossier.'})
    status_written = update_fields is None or 'status' in update_fields
    if not status_written or old_status == instance.status:
        return old_status
    candidate = old or instance
    case = is_exchange_case(candidate, old_status) if candidate.pk and not candidate._state.adding else instance.status == 'exchange'
    if not case:
        return old_status
    process = get_process(candidate)
    actor = current_actor()
    workflow_transition = getattr(instance, '_exchange_transition', False)
    if process and process.billing_validated_at and old_status == 'closed' and instance.status != 'closed':
        raise ValidationError({'status': 'Un échange facturé et clôturé reste conservé. Créez un nouveau dossier pour une nouvelle opération.'})
    if instance.status == 'ready_for_delivery' and not workflow_transition:
        raise ValidationError({'status': 'Validez le remplacement puis utilisez l’action Prêt à être livré dans la rubrique Échange.'})
    if instance.status == 'closed':
        if not process or not process.billing_validated_at:
            raise ValidationError({'status': 'La facturation de cet échange doit être confirmée avant sa clôture.'})
        _valid_identity(candidate, process)
        if actor and actor.effective_role not in ('admin', 'manager') and not can_validate_billing(actor):
            raise PermissionDenied('La clôture après facturation est réservée aux responsables autorisés.')
    elif process and process.validated_at and not workflow_transition:
        raise ValidationError({'status': 'Cet échange est validé. Utilisez ses actions dédiées, ou annulez sa validation avec un motif avant de reprendre sa préparation.'})
    return old_status


def guard_equipment_update(instance, update_fields=None):
    protected = {'serial_number', 'model', 'brand', 'client', 'client_id'}
    if update_fields is not None and not protected.intersection(update_fields):
        return
    previous = Equipment.objects.select_for_update().filter(pk=instance.pk).values('serial_number', 'model', 'brand', 'client_id').first()
    if not previous or all(previous[field] == getattr(instance, field) for field in previous):
        return
    validated = ExchangeProcess.objects.filter(validated_at__isnull=False).filter(
        Q(replacement_equipment_id=instance.pk) | Q(service_request__equipment_id=instance.pk)
    ).exists()
    if validated:
        raise ValidationError({'equipment': 'L’identité d’un matériel lié à un échange validé est conservée. Annulez d’abord la validation si la facturation n’est pas encore confirmée.'})


def _manager(actor):
    return bool(actor and actor.is_active and actor.effective_role in ('admin', 'manager'))


def _editable(actor, service_request):
    return _manager(actor) or bool(actor and actor.is_active and actor.effective_role == 'technician' and technician_can_write(actor, service_request))


def _name(user):
    return (user.get_full_name() or user.username) if user else ''


def recorded_handoff(service_request):
    """Read-only capability hint; mutation guards always query under the lock."""
    if hasattr(service_request, '_logistics_handed_over'):
        return service_request._logistics_handed_over
    from .logistics_models import OutboundJob
    return OutboundJob.objects.filter(service_request_id=service_request.pk, handed_over_at__isnull=False).exists()


def exchange_payload(service_request, actor):
    process = get_process(service_request)
    if not is_exchange_case(service_request):
        return None
    validated = bool(process and process.validated_at)
    ready = bool(process and process.ready_at)
    invoiced = bool(process and process.billing_validated_at)
    closed = service_request.status == 'closed'
    state = 'closed' if closed else 'invoiced' if invoiced else 'ready_for_delivery' if ready else 'validated' if validated else 'pending_validation' if process and process.prepared_at else 'awaiting_preparation'
    internal = bool(actor and actor.effective_role != 'client')
    manager = _manager(actor)
    active_exchange = service_request.status == 'exchange'
    handed_over = recorded_handoff(service_request)
    writable = not closed and not validated and active_exchange and not handed_over
    visible_replacement = bool(process and (internal or validated))
    result = {
        'state': state,
        'replacement_serial_number': process.replacement_serial_number if visible_replacement else '',
        'replacement_model': process.replacement_model if visible_replacement else '',
        'replacement_brand': process.replacement_brand if visible_replacement else '',
        'replacement_equipment': process.replacement_equipment_id if visible_replacement else None,
        'validated_at': process.validated_at if validated else None,
        'ready_at': process.ready_at if ready else None,
        'billing_validated_at': process.billing_validated_at if invoiced else None,
        'is_validated': validated, 'is_ready': ready, 'is_invoiced': invoiced,
        'can_prepare': writable and _editable(actor, service_request),
        'can_validate': writable and manager,
        'can_mark_ready': not closed and active_exchange and validated and not ready and manager and not handed_over,
        'can_validate_billing': not closed and service_request.status == 'ready_for_delivery' and ready and validated and not invoiced and can_validate_billing(actor),
        'can_close': not closed and invoiced and (manager or can_validate_billing(actor)),
        'can_reset': not closed and not invoiced and manager and bool(process and (process.prepared_at or validated)) and not handed_over,
    }
    if internal:
        result.update({
            'prepared_at': process.prepared_at if process else None,
            'validated_by': process.validated_by_id if process else None,
            'validated_by_name': _name(process.validated_by) if process else '',
            'ready_by': process.ready_by_id if process else None,
            'ready_by_name': _name(process.ready_by) if process else '',
            'invoice_reference': process.invoice_reference if process else '',
            'invoiced_on': process.invoiced_on if process else None,
            'billing_validated_by': process.billing_validated_by_id if process else None,
            'billing_validated_by_name': _name(process.billing_validated_by) if process else '',
            'billing_notes': process.billing_notes if process else '',
        })
    return result


def _locked_request(identifier):
    return ServiceRequest.objects.select_for_update().get(pk=identifier)


def _locked_process(service_request):
    process, _ = ExchangeProcess.objects.get_or_create(service_request=service_request)
    return ExchangeProcess.objects.select_for_update().get(pk=process.pk)


def _not_handed_over(service_request):
    from .logistics_models import OutboundJob
    if OutboundJob.objects.filter(service_request_id=service_request.pk, handed_over_at__isnull=False).exists():
        raise ValidationError('La remise de ce matériel est déjà enregistrée. Sa préparation et sa validation restent conservées ; utilisez un nouveau dossier pour une nouvelle opération.')


def _active(service_request):
    _not_handed_over(service_request)
    if service_request.status != 'exchange':
        raise ValidationError({'status': 'Placez le dossier au statut Échange avant de préparer ou valider son remplacement.'})


def _audit(actor, process, action):
    AuditLog.objects.create(actor=actor, action=action, resource='exchangeprocess', resource_id=str(process.pk))


def _event(service_request, process, actor, *, kind, summary, observation='', private=False):
    return append_event(equipment=service_request.equipment, related_equipment=process.replacement_equipment,
                        service_request=service_request, actor=actor, kind=kind,
                        summary=summary, observation=observation, is_internal=private)


def _valid_identity(service_request, process):
    replacement = process.replacement_equipment
    if not replacement or replacement.pk == service_request.equipment_id or replacement.client_id != service_request.equipment.client_id:
        raise ValidationError({'replacement_serial_number': 'Le remplacement validé doit être un autre équipement du même client.'})
    if replacement.serial_number != process.replacement_serial_number or replacement.model != process.replacement_model or replacement.brand != process.replacement_brand:
        raise ValidationError({'replacement_serial_number': 'Le matériel a changé depuis sa validation. Une nouvelle vérification est nécessaire.'})


@transaction.atomic
def prepare_exchange(identifier, data, *, actor):
    service_request = _locked_request(identifier)
    actor = require_accepted_assignment(actor, service_request)
    if not _editable(actor, service_request):
        raise PermissionDenied('La préparation est réservée au responsable ou au technicien affecté au dossier.')
    _active(service_request)
    process = _locked_process(service_request)
    if process.validated_at:
        raise ValidationError('Le remplacement est déjà validé. Annulez sa validation avec un motif avant de le modifier.')
    values = {field: data.get(field, getattr(process, field)) for field in ('replacement_serial_number', 'replacement_model', 'replacement_brand')}
    selected = data.get('replacement_equipment')
    if selected is not None:
        equipment = Equipment.objects.filter(pk=selected, client_id=service_request.equipment.client_id).first()
        if not equipment:
            raise ValidationError({'replacement_equipment': 'Ce matériel ne peut pas être sélectionné pour ce dossier.'})
        if data.get('replacement_serial_number') and values['replacement_serial_number'].casefold() != equipment.serial_number.casefold():
            raise ValidationError({'replacement_serial_number': 'Le numéro saisi ne correspond pas au matériel sélectionné.'})
        values = {'replacement_serial_number': equipment.serial_number, 'replacement_model': equipment.model, 'replacement_brand': equipment.brand}
    else:
        equipment = Equipment.objects.filter(serial_number__iexact=values['replacement_serial_number']).first() if values['replacement_serial_number'] else None
        if equipment and equipment.client_id != service_request.equipment.client_id:
            raise ValidationError({'replacement_serial_number': 'Ce numéro de série ne peut pas être utilisé pour ce dossier.'})
    unchanged = all(getattr(process, field) == value for field, value in values.items()) and process.replacement_equipment_id == (equipment.pk if equipment else None) and process.prepared_at is not None
    if unchanged:
        return service_request
    for field, value in values.items():
        setattr(process, field, value)
    process.replacement_equipment = equipment
    process.prepared_by = actor
    process.prepared_at = timezone.now()
    process.save()
    _event(service_request, process, actor, kind='exchange_prepared', summary='Préparation du remplacement enregistrée, en attente de validation.',
           observation=f"S/N proposé : {process.replacement_serial_number or 'non renseigné'} ; modèle : {process.replacement_model or 'non renseigné'}.", private=True)
    _audit(actor, process, 'exchange_prepare')
    return service_request


@transaction.atomic
def validate_exchange(identifier, *, actor):
    service_request = _locked_request(identifier)
    if not _manager(actor):
        raise PermissionDenied('Le responsable SAV ou un administrateur valide le remplacement.')
    process = _locked_process(service_request)
    if process.validated_at:
        _valid_identity(service_request, process)
        return service_request
    _active(service_request)
    serial = process.replacement_serial_number.strip()
    if not serial:
        raise ValidationError({'replacement_serial_number': 'Renseignez le numéro de série du produit de remplacement.'})
    if connection.vendor == 'postgresql':
        lock = int.from_bytes(hashlib.sha256(serial.casefold().encode()).digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock])
    candidate_id = Equipment.objects.filter(serial_number__iexact=serial).values_list('pk', flat=True).first()
    # Identity edits take the same row locks. Lock both units in primary-key
    # order so two simultaneous exchanges cannot deadlock while crossing units.
    locked = list(Equipment.objects.select_for_update(no_key=True).filter(pk__in={service_request.equipment_id, candidate_id, process.replacement_equipment_id} - {None}).order_by('pk'))
    original = next(unit for unit in locked if unit.pk == service_request.equipment_id)
    service_request.equipment = original
    replacement = next((unit for unit in locked if unit.pk == candidate_id and unit.serial_number.casefold() == serial.casefold()), None)
    if process.replacement_equipment_id:
        selected = next((unit for unit in locked if unit.pk == process.replacement_equipment_id), None)
        if not selected or selected.serial_number.casefold() != serial.casefold() or (process.replacement_model and selected.model != process.replacement_model) or (process.replacement_brand and selected.brand != process.replacement_brand):
            raise ValidationError({'replacement_equipment': 'L’identité du matériel sélectionné a changé depuis la préparation. Relisez sa fiche et préparez à nouveau le remplacement.'})
    if serial.casefold() == original.serial_number.casefold():
        raise ValidationError({'replacement_serial_number': 'Le produit de remplacement doit être différent de l’onduleur reçu en SAV.'})
    if replacement and replacement.client_id != service_request.equipment.client_id:
        raise ValidationError({'replacement_serial_number': 'Ce numéro de série ne peut pas être utilisé pour ce dossier.'})
    if replacement:
        if process.replacement_model and process.replacement_model != replacement.model:
            raise ValidationError({'replacement_model': 'Le modèle saisi ne correspond pas au matériel déjà enregistré.'})
        if process.replacement_brand and process.replacement_brand != replacement.brand:
            raise ValidationError({'replacement_brand': 'La marque saisie ne correspond pas au matériel déjà enregistré.'})
    else:
        if not process.replacement_model.strip():
            raise ValidationError({'replacement_model': 'Renseignez le modèle du nouveau produit de remplacement.'})
        replacement = Equipment.objects.create(client_id=service_request.equipment.client_id, serial_number=serial,
                                               model=process.replacement_model, brand=process.replacement_brand)
    if ExchangeProcess.objects.filter(replacement_equipment=replacement, reservation_active=True).exclude(pk=process.pk).exists():
        raise ValidationError({'replacement_serial_number': 'Ce produit est déjà réservé pour un autre échange non clôturé.'})
    process.replacement_equipment = replacement
    process.replacement_serial_number = replacement.serial_number
    process.replacement_model = replacement.model
    process.replacement_brand = replacement.brand
    process.validated_at = timezone.now()
    process.validated_by = actor
    process.reservation_active = True
    process.save()
    _event(service_request, process, actor, kind='exchange_validated',
           summary=f'Échange validé : onduleur reçu S/N {service_request.equipment.serial_number} ; produit de remplacement S/N {replacement.serial_number} — {replacement.model}.')
    _audit(actor, process, 'exchange_validate')
    return service_request


@transaction.atomic
def ready_exchange(identifier, *, actor):
    service_request = _locked_request(identifier)
    if not _manager(actor):
        raise PermissionDenied('Le responsable SAV ou un administrateur autorise le passage Prêt à être livré.')
    process = _locked_process(service_request)
    if not process.validated_at:
        raise ValidationError('Validez le numéro de série du remplacement avant de préparer sa livraison.')
    _valid_identity(service_request, process)
    if process.ready_at:
        return service_request
    _active(service_request)
    process.ready_at = timezone.now()
    process.ready_by = actor
    process.save()
    service_request._exchange_transition = True
    service_request.status = 'ready_for_delivery'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, process, actor, kind='exchange_ready', summary='Échange prêt à être livré. La livraison effective et la facturation restent distinctes.')
    _audit(actor, process, 'exchange_ready')
    return service_request


@transaction.atomic
def bill_exchange(identifier, data, *, actor):
    service_request = _locked_request(identifier)
    if not can_validate_billing(actor):
        raise PermissionDenied('Une autorisation de validation de la facturation est requise.')
    process = _locked_process(service_request)
    if process.billing_validated_at:
        if process.invoice_reference != data['invoice_reference'] or process.invoiced_on != data['invoiced_on'] or process.billing_notes != data.get('billing_notes', ''):
            raise ValidationError('La facturation confirmée est conservée. Ses justificatifs ne peuvent pas être remplacés dans cette action.')
        return service_request
    if not process.validated_at or not process.ready_at or service_request.status != 'ready_for_delivery':
        raise ValidationError('Le remplacement doit être validé et le dossier Prêt à être livré avant de confirmer sa facturation.')
    _valid_identity(service_request, process)
    process.invoice_reference = data['invoice_reference']
    process.invoiced_on = data['invoiced_on']
    process.billing_notes = data.get('billing_notes', '')
    process.billing_validated_at = timezone.now()
    process.billing_validated_by = actor
    process.save()
    _event(service_request, process, actor, kind='exchange_billed', summary='Facturation de l’échange confirmée. La clôture du dossier est désormais autorisée.')
    _event(service_request, process, actor, kind='exchange_billing_details', private=True,
           summary=f'Facture {process.invoice_reference} du {process.invoiced_on.isoformat()}.', observation=process.billing_notes)
    _audit(actor, process, 'exchange_bill')
    return service_request


@transaction.atomic
def close_exchange(identifier, *, actor):
    service_request = _locked_request(identifier)
    if not _manager(actor) and not can_validate_billing(actor):
        raise PermissionDenied('La clôture de cet échange est réservée aux responsables autorisés.')
    process = _locked_process(service_request)
    if not process.billing_validated_at:
        raise ValidationError('Confirmez la facturation avant de clôturer cet échange.')
    _valid_identity(service_request, process)
    if service_request.status == 'closed':
        return service_request
    service_request._exchange_transition = True
    service_request.status = 'closed'
    service_request.save(update_fields=['status', 'updated_at'])
    _event(service_request, process, actor, kind='exchange_closed', summary='Échange clôturé après confirmation de sa facturation.')
    _audit(actor, process, 'exchange_close')
    return service_request


@transaction.atomic
def reset_exchange(identifier, *, actor, reason):
    service_request = _locked_request(identifier)
    if not _manager(actor):
        raise PermissionDenied('Le responsable SAV ou un administrateur reprend la préparation de cet échange.')
    _not_handed_over(service_request)
    process = _locked_process(service_request)
    if process.billing_validated_at or service_request.status == 'closed':
        raise ValidationError('Un échange facturé ou clôturé ne peut pas être réinitialisé par cette action.')
    if not process.prepared_at and not process.validated_at:
        return service_request
    previous_serial = process.replacement_serial_number
    previous_equipment = process.replacement_equipment
    had_validation = process.validated_at is not None
    process.replacement_equipment = None
    process.validated_at = process.validated_by = process.ready_at = process.ready_by = None
    process.reservation_active = False
    process.save()
    service_request._exchange_transition = True
    service_request.status = 'exchange'
    service_request.save(update_fields=['status', 'updated_at'])
    append_event(equipment=service_request.equipment, related_equipment=previous_equipment if had_validation else None, service_request=service_request,
                 actor=actor, kind='exchange_reset', summary=(f'Validation du remplacement S/N {previous_serial or "non renseigné"} retirée. Une nouvelle validation est nécessaire.' if had_validation else 'Préparation de l’échange reprise. Aucun remplacement n’avait encore été validé.'))
    _event(service_request, process, actor, kind='exchange_reset_reason', summary='Motif de reprise de la préparation.', observation=reason, private=True)
    _audit(actor, process, 'exchange_reset')
    return service_request
