import logging
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from .attachment_models import RequestAttachment
from .attachment_storage import private_path, private_storage
from .attachment_validation import check_attachment
from .models import AuditLog, ServiceRequest
from .workflow import technician_can_write
from .workflow_events import append_event


logger = logging.getLogger(__name__)


def can_write_documents(user, service_request):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.effective_role in ('admin', 'manager'):
        return True
    return user.effective_role == 'technician' and technician_can_write(user, service_request)


def visible_request(user, request_id, *, lock=False):
    query = ServiceRequest.objects.select_related('equipment__client')
    if lock:
        query = query.select_for_update()
    service_request = query.filter(pk=request_id).first()
    if service_request is None or (user.effective_role == 'client' and service_request.equipment.client_id != user.client_id):
        raise NotFound('Ce dossier n’est pas accessible.')
    return service_request


def visible_document(user, document_id, *, lock=False):
    query = RequestAttachment.objects.select_related('service_request__equipment__client')
    if lock:
        query = query.select_for_update()
    document = query.filter(pk=document_id, deleted_at__isnull=True).first()
    if document is None or (user.effective_role == 'client' and (
        not document.client_visible or document.service_request.equipment.client_id != user.client_id
    )):
        raise NotFound('Ce document n’est pas accessible.')
    return document


def create_document(*, service_request, uploaded, label, client_visible, actor):
    if not can_write_documents(actor, service_request):
        raise PermissionDenied('L’ajout est réservé au responsable SAV, à l’administrateur et à l’équipe affectée au dossier.')
    checked = check_attachment(uploaded)
    stored_name = None
    storage = private_storage()
    try:
        with transaction.atomic():
            service_request = visible_request(actor, service_request.pk, lock=True)
            if not can_write_documents(actor, service_request):
                raise PermissionDenied('Vous n’êtes plus affecté à ce dossier.')
            generated = f'requests/{service_request.pk}/{uuid4().hex}.{checked.extension}'
            private_path(generated)
            stored_name = storage.save(generated, ContentFile(checked.data))
            if stored_name != generated:
                # UUID collisions must never produce a non-conforming path.
                raise ValueError('Unexpected storage filename')
            document = RequestAttachment.objects.create(
                service_request=service_request, stored_name=stored_name,
                original_name=checked.original_name, label=label or checked.original_name,
                mime_type=checked.mime_type, size_bytes=len(checked.data), sha256=checked.sha256,
                client_visible=client_visible, uploaded_by=actor,
                uploaded_by_label=actor.get_full_name() or actor.username,
            )
            append_event(
                equipment=service_request.equipment, service_request=service_request, actor=actor,
                kind='attachment_added', is_internal=not client_visible,
                summary=f'Pièce jointe ajoutée : {checked.original_name}.',
            )
            AuditLog.objects.create(actor=actor, action='attachment_add', resource='requestattachment', resource_id=str(document.pk))
            return document
    except Exception:
        if stored_name:
            try:
                storage.delete(stored_name)
            except OSError:
                logger.error('Document upload rollback cleanup failed; run purge_request_documents for orphan reconciliation.', exc_info=False)
        raise


def purge_document_file(document_id):
    try:
        document = RequestAttachment.objects.filter(pk=document_id, deleted_at__isnull=False, storage_deleted_at__isnull=True).first()
        if document is None:
            return True
        path = private_path(document.stored_name)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        RequestAttachment.objects.filter(pk=document.pk, storage_deleted_at__isnull=True).update(storage_deleted_at=timezone.now())
    except (DatabaseError, OSError, ValueError):
        logger.error('Private document removal is pending; retry purge_request_documents.', exc_info=False)
        return False
    return True


def delete_document(*, document, actor):
    if not can_write_documents(actor, document.service_request):
        raise PermissionDenied('La suppression est réservée au responsable SAV, à l’administrateur et à l’équipe affectée au dossier.')
    result = {'purged': False}
    with transaction.atomic():
        service_request = visible_request(actor, document.service_request_id, lock=True)
        if not can_write_documents(actor, service_request):
            raise PermissionDenied('Vous n’êtes plus affecté à ce dossier.')
        document = visible_document(actor, document.pk, lock=True)
        document.deleted_at = timezone.now()
        document.deleted_by = actor
        document.save(update_fields=['deleted_at', 'deleted_by'])
        append_event(
            equipment=service_request.equipment, service_request=service_request, actor=actor,
            kind='attachment_deleted', is_internal=not document.client_visible,
            summary=f'Pièce jointe supprimée : {document.original_name}.',
        )
        AuditLog.objects.create(actor=actor, action='attachment_delete', resource='requestattachment', resource_id=str(document.pk))
        transaction.on_commit(lambda: result.update(purged=purge_document_file(document.pk)))
    return result
