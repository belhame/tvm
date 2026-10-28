"""Prepared BL snapshots; dispatch and physical handoff remain separate."""
from copy import deepcopy
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .logistics_delivery_note_models import DeliveryNoteMission, LogisticsDeliveryNote
from .logistics_models import OutboundJob
from .logistics_service import canonical_outbound
from .models import AuditLog, DeliveryLine, DeliveryNote, Equipment, ServiceRequest, User
from .workflow_events import actor_context, append_event


class DeliveryNoteConflict(APIException):
    status_code = 409
    default_detail = 'La préparation ou les missions ont changé. Rechargez la liste avant de préparer le bon.'


def _permitted(actor):
    return bool(actor and actor.is_active and (
        actor.role not in ('client', 'courier') and actor.effective_role in ('admin', 'manager')
        or actor.role == 'courier' and actor.courier_kind == 'internal'))


def _actor(actor, *, lock=False):
    query = User.objects.select_for_update(no_key=True) if lock else User.objects.all()
    fresh = query.filter(pk=getattr(actor, 'pk', None)).first()
    if not _permitted(fresh):
        raise PermissionDenied('Les bons de livraison sont réservés aux responsables et aux livreurs TVM actifs.')
    return fresh


def _name(actor):
    return actor.get_full_name() or actor.username


def _reason(value, *, required=False):
    if not isinstance(value, str) or len(value) > 4000 or '\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValidationError({'reason' if required else 'comment': 'Un texte valide de 4 000 caractères au maximum est requis.'})
    value = value.strip()
    if required and not value:
        raise ValidationError({'reason': 'Expliquez l’annulation de la préparation du bon.'})
    return value


def _live_links(note):
    return note.missions.select_related('job__service_request__equipment', 'job__delivery_equipment', 'job__assigned_courier')


def _courier_applicable(note, actor):
    if note.state != 'prepared' or note.assigned_courier_id != actor.pk:
        return False
    frozen_lines = {line['job']: line for line in note.snapshot['lines']}
    for link in _live_links(note):
        job = link.job
        if (job.assigned_courier_id != actor.pk or job.assignment_revision != link.assignment_revision
            or job.cancelled_at is not None or job.client_id != note.delivery_note.client_id
            or job.service_request.equipment.client_id != job.client_id or job.delivery_equipment.client_id != job.client_id
            or job.delivery_equipment_id != link.equipment_id):
            return False
        frozen = frozen_lines.get(job.pk)
        identity = (job.handed_over_serial, job.handed_over_brand, job.handed_over_model) if job.handed_over_at else (job.delivery_equipment.serial_number, job.delivery_equipment.brand, job.delivery_equipment.model)
        if not frozen or identity != (frozen['serial_number'], frozen['brand'], frozen['model']):
            return False
        # A completed handoff retains the original BL. Before handoff the
        # prepared document is usable only for the still-current accepted job.
        if job.handed_over_at is None:
            from .courier_dispatch import outbound_is_accepted
            if not job.active or not outbound_is_accepted(job):
                return False
            try:
                unit, kind = canonical_outbound(job.service_request)
            except ValidationError:
                return False
            if unit.pk != job.delivery_equipment_id or kind != job.kind:
                return False
    return True


def visible_note(actor, note_id):
    actor = _actor(actor)
    if type(note_id) is not int or not 1 <= note_id <= 9223372036854775807:
        raise NotFound('Bon de livraison introuvable.')
    try:
        note = LogisticsDeliveryNote.objects.select_related('delivery_note', 'assigned_courier', 'created_by').get(pk=note_id)
    except LogisticsDeliveryNote.DoesNotExist as exc:
        raise NotFound('Bon de livraison introuvable.') from exc
    if actor.role == 'courier' and not _courier_applicable(note, actor):
        raise NotFound('Ce bon ne correspond plus à vos missions courantes.')
    return note


def note_payload(note, actor, *, created=None):
    facts = note.snapshot
    payload = {'id': note.pk, 'reference': facts['reference'], 'status': note.state,
        'client': deepcopy(facts['client']), 'courier': deepcopy(facts['courier']),
        'created_at': facts['issued_at'], 'line_count': len(facts['lines']), 'lines': deepcopy(facts['lines']),
        'comment': facts['comment'], 'pdf_url': f'/api/logistics/delivery-notes/{note.pk}/pdf/',
        'pdf_sha256': note.pdf_sha256, 'can_cancel': note.state == 'prepared' and not note.missions.filter(job__handed_over_at__isnull=False).exists(),
        'cancelled_at': note.cancelled_at.isoformat() if note.cancelled_at else None,
        'cancellation_reason': note.cancellation_reason}
    if created is not None:
        payload['created'] = created
    return payload


def list_notes(actor):
    actor = _actor(actor)
    notes = LogisticsDeliveryNote.objects.select_related('delivery_note', 'assigned_courier', 'created_by')
    if actor.role == 'courier':
        notes = notes.filter(assigned_courier=actor)
    return [note_payload(note, actor) for note in notes if actor.role != 'courier' or _courier_applicable(note, actor)]


def _locked_jobs(job_ids):
    # Shared order with dispatch mutations: SAV first. All IDs are sorted so
    # overlapping lots cannot deadlock by acquiring their requests in reverse.
    request_ids = list(OutboundJob.objects.filter(pk__in=job_ids).values_list('service_request_id', flat=True))
    if len(request_ids) != len(job_ids):
        raise NotFound('Une mission sélectionnée est introuvable.')
    records = list(ServiceRequest.objects.select_for_update().filter(pk__in=request_ids).order_by('pk'))
    jobs = list(OutboundJob.objects.select_for_update(of=('self',)).select_related('service_request__equipment__client', 'delivery_equipment', 'assigned_courier').filter(pk__in=job_ids).order_by('pk'))
    equipment_ids = {job.delivery_equipment_id for job in jobs} | {record.equipment_id for record in records}
    list(Equipment.objects.select_for_update(no_key=True).filter(pk__in=equipment_ids).order_by('pk'))
    # A permitted legacy identity edit may have committed while these locks
    # were awaited. Never build the PDF from the pre-lock relation caches.
    return list(OutboundJob.objects.select_related('service_request__equipment__client', 'delivery_equipment', 'assigned_courier').filter(pk__in=job_ids).order_by('pk'))


def _validate_jobs(jobs, actor):
    if actor.role == 'courier' and any(job.assigned_courier_id != actor.pk for job in jobs):
        raise NotFound('Une mission sélectionnée ne vous est pas affectée.')
    client_ids = {job.client_id for job in jobs}
    courier_ids = {job.assigned_courier_id for job in jobs}
    if len(client_ids) != 1 or len(courier_ids) != 1:
        raise ValidationError('Un bon regroupe uniquement des onduleurs du même client et du même livreur.')
    from .courier_dispatch import require_outbound_acceptance
    for job in jobs:
        if not job.active or job.cancelled_at or job.handed_over_at:
            raise DeliveryNoteConflict('Une mission n’est plus une préparation active non remise.')
        if job.client_id != job.service_request.equipment.client_id or job.client_id != job.delivery_equipment.client_id:
            raise DeliveryNoteConflict('Le propriétaire du matériel ne correspond plus à la mission.')
        unit, kind = canonical_outbound(job.service_request)
        if unit.pk != job.delivery_equipment_id or kind != job.kind:
            raise DeliveryNoteConflict('Le matériel canonique de la mission a changé.')
        if unit.pk != job.service_request.equipment_id:
            exchange = job.service_request.exchange_process
            if unit.model != exchange.replacement_model or unit.brand != exchange.replacement_brand:
                raise DeliveryNoteConflict('L’identité du remplacement validé a changé.')
        require_outbound_acceptance(actor, job)
    if len({job.delivery_equipment_id for job in jobs}) != len(jobs):
        raise ValidationError('Un même onduleur ne peut pas figurer deux fois dans le lot.')


def _fingerprint(job_ids, comment):
    return hashlib.sha256(json.dumps({'jobs': sorted(job_ids), 'comment': comment}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _conflict_existing(note, actor):
    error = DeliveryNoteConflict()
    error.detail = {'detail': 'Une mission figure déjà sur un bon préparé. Réimprimez ce bon ou annulez sa préparation avant de le remplacer.'}
    if actor.role != 'courier' or _courier_applicable(note, actor):
        error.detail['existing_note'] = {'id': note.pk, 'reference': note.snapshot['reference'],
            'pdf_url': f'/api/logistics/delivery-notes/{note.pk}/pdf/'}
    else:
        error.detail['detail'] = 'Une préparation historique ne correspond plus à la mission courante. Demandez au responsable de la vérifier et de l’annuler avant de préparer un nouveau bon.'
    raise error


@transaction.atomic
def create_note(actor, *, request_key, job_ids, comment=''):
    from .logistics_service import _lock
    comment = _reason(comment)
    if not isinstance(request_key, UUID):
        try:
            request_key = UUID(str(request_key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({'request_key': 'Une clé UUID est requise.'}) from exc
    if not isinstance(job_ids, list) or not 1 <= len(job_ids) <= 100 or any(type(pk) is not int or not 1 <= pk <= 9223372036854775807 for pk in job_ids) or len(set(job_ids)) != len(job_ids):
        raise ValidationError({'job_ids': 'Sélectionnez entre 1 et 100 missions distinctes.'})
    actor = _actor(actor)
    digest = _fingerprint(job_ids, comment)
    _lock(f'logistics-bl-key:{request_key}')
    previous = LogisticsDeliveryNote.objects.select_related('delivery_note').filter(request_key=request_key).first()
    if previous:
        if previous.created_by_id != actor.pk or previous.payload_hash != digest:
            raise DeliveryNoteConflict('Cette clé de préparation a déjà été utilisée avec un autre lot ou commentaire.')
        return note_payload(visible_note(actor, previous.pk), actor, created=False)
    jobs = _locked_jobs(sorted(job_ids))
    participant_ids = {actor.pk} | {job.assigned_courier_id for job in jobs}
    participants = {user.pk: user for user in User.objects.select_for_update(no_key=True).filter(pk__in=participant_ids).order_by('pk')}
    actor = participants.get(actor.pk)
    if not _permitted(actor):
        raise PermissionDenied('Votre rôle ne permet plus de préparer un bon.')
    courier = participants.get(jobs[0].assigned_courier_id)
    if not courier or not courier.is_active or courier.role != 'courier':
        raise ValidationError('Le livreur affecté doit être un compte livreur actif.')
    _validate_jobs(jobs, actor)
    if courier.courier_kind == 'client' and courier.client_id != jobs[0].client_id:
        raise DeliveryNoteConflict('Le livreur client ne correspond plus au client de la mission.')
    existing = DeliveryNoteMission.objects.filter(job_id__in=job_ids, active=True).select_related('note__delivery_note').first()
    if existing:
        _conflict_existing(existing.note, actor)
    company = jobs[0].service_request.equipment.client
    now = timezone.now()
    with actor_context(actor):
        base = DeliveryNote.objects.create(client=company, status='ready', notes=comment)
        lines = [{'job': job.pk, 'assignment_revision': job.assignment_revision, 'service_request': job.service_request_id,
                  'call_number': job.service_request.reference, 'client_reference': job.service_request.client_reference,
                  'equipment': job.delivery_equipment_id, 'original_serial_number': job.service_request.equipment.serial_number,
                  'serial_number': job.delivery_equipment.serial_number, 'brand': job.delivery_equipment.brand,
                  'model': job.delivery_equipment.model, 'kind': job.kind, 'delivery_address': job.delivery_address} for job in jobs]
        snapshot = {'version': 1, 'reference': base.reference, 'issued_at': now.isoformat(),
            'client': {'id': company.pk, 'name': company.name, 'address': company.address, 'city': company.city, 'postal_code': company.postal_code, 'country': company.country},
            'courier': {'id': courier.pk, 'name': _name(courier), 'courier_kind': courier.courier_kind},
            'prepared_by': {'id': actor.pk, 'name': _name(actor)}, 'comment': comment, 'lines': lines}
        if len(json.dumps(snapshot, ensure_ascii=False).encode()) > 1024 * 1024 or any(len(line['delivery_address']) > 4000 for line in lines) or len(company.address) > 4000:
            raise ValidationError('Le lot contient des adresses trop longues pour un bon lisible. Corrigez les coordonnées ou préparez des lots plus petits.')
        for line in lines:
            DeliveryLine.objects.create(delivery_note=base, quantity=1,
                description=f'{line["brand"]} {line["model"]} — S/N {line["serial_number"]}'[:250])
        from .logistics_delivery_note_pdf import render_delivery_note
        pdf = render_delivery_note(snapshot)
        note = LogisticsDeliveryNote.objects.create(delivery_note=base, request_key=request_key, payload_hash=digest,
            assigned_courier=courier, created_by=actor, snapshot=snapshot, pdf_data=pdf, pdf_sha256=hashlib.sha256(pdf).hexdigest())
        DeliveryNoteMission.objects.bulk_create([DeliveryNoteMission(note=note, job=job, assignment_revision=job.assignment_revision, equipment_id=job.delivery_equipment_id) for job in jobs])
        note.sealed_at = timezone.now()
        note.save(update_fields=['sealed_at'])
        for job in jobs:
            append_event(equipment=job.service_request.equipment, related_equipment=job.delivery_equipment if job.delivery_equipment_id != job.service_request.equipment_id else None,
                service_request=job.service_request, actor=actor, kind='delivery_note_prepared',
                summary=f'Bon de livraison {base.reference} préparé. Aucune remise physique enregistrée.', is_internal=True)
        AuditLog.objects.create(actor=actor, action='prepare_delivery_note', resource='deliverynote', resource_id=str(base.pk))
    return note_payload(note, actor, created=True)


def _cancel_locked(note, *, actor, reason, event_job=None):
    if note.state == 'cancelled':
        return note
    note.state = 'cancelled'
    note.cancelled_at = timezone.now()
    note.cancelled_by = actor
    note.cancellation_reason = reason
    note.save(update_fields=['state', 'cancelled_at', 'cancelled_by', 'cancellation_reason'])
    note.missions.filter(active=True).update(active=False)
    history = _live_links(note)
    if event_job is not None:
        # A dispatch mutation owns only its own SAV/job locks. Inserting
        # events on another SAV here would acquire an FK KEY SHARE lock in
        # reverse order while that other mutation waits on this same note.
        history = history.filter(job_id=event_job.pk)
    for link in history:
        append_event(equipment=link.job.service_request.equipment, service_request=link.job.service_request, actor=actor,
            kind='delivery_note_cancelled', summary=f'Préparation du bon {note.snapshot["reference"]} annulée ; le PDF original reste conservé.', observation=reason, is_internal=True)
    AuditLog.objects.create(actor=actor, action='cancel_delivery_note', resource='deliverynote', resource_id=str(note.pk))
    return note


@transaction.atomic
def cancel_note(actor, note_id, *, reason):
    reason = _reason(reason, required=True)
    note = visible_note(actor, note_id)
    ids = list(note.missions.values_list('job_id', flat=True))
    _locked_jobs(sorted(ids))
    actor = _actor(actor, lock=True)
    note = LogisticsDeliveryNote.objects.select_for_update().select_related('delivery_note').get(pk=note_id)
    if actor.role == 'courier' and not _courier_applicable(note, actor):
        raise NotFound()
    if note.missions.filter(job__handed_over_at__isnull=False).exists():
        raise DeliveryNoteConflict('Une remise physique est enregistrée. Le bon original doit rester conservé sans annuler sa préparation.')
    _cancel_locked(note, actor=actor, reason=reason)
    return note_payload(note, actor)


@transaction.atomic
def invalidate_delivery_notes_for_job(job, *, actor=None, reason='La mission a changé.'):
    links = DeliveryNoteMission.objects.filter(job=job, active=True).select_related('note')
    ids = sorted({link.note_id for link in links if link.assignment_revision != job.assignment_revision or job.cancelled_at is not None or not job.active and job.handed_over_at is None})
    for note in LogisticsDeliveryNote.objects.select_for_update().filter(pk__in=ids).order_by('pk'):
        _cancel_locked(note, actor=actor, reason=reason, event_job=job)


def guard_prepared_note(instance):
    if instance.pk and LogisticsDeliveryNote.objects.filter(pk=instance.pk).exists():
        old = DeliveryNote.objects.get(pk=instance.pk)
        if any(getattr(old, field.attname) != getattr(instance, field.attname) for field in instance._meta.concrete_fields):
            raise ValidationError('Ce bon possède un PDF préparé immuable. Annulez sa préparation dans l’espace logistique.')


def guard_prepared_line(instance):
    if LogisticsDeliveryNote.objects.filter(pk=instance.delivery_note_id).exists():
        raise ValidationError('Les lignes d’un bon préparé sont figées ; préparez un nouveau bon après annulation.')


def guard_prepared_equipment(instance, update_fields=None):
    fields = {'serial_number', 'model', 'brand', 'client', 'client_id'}
    if update_fields is not None and not fields.intersection(update_fields):
        return
    previous = Equipment.objects.filter(pk=instance.pk).values('serial_number', 'model', 'brand', 'client_id').first()
    if previous and any(previous[key] != getattr(instance, key) for key in previous) and DeliveryNoteMission.objects.filter(equipment_id=instance.pk, active=True).exists():
        raise ValidationError({'equipment': 'Ce matériel figure sur un bon de livraison préparé. Annulez d’abord ce bon avant de corriger son identité.'})
