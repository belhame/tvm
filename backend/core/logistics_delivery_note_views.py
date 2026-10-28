import hashlib

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .logistics_delivery_notes import (DeliveryNoteConflict, _permitted, cancel_note, create_note,
    list_notes, note_payload, visible_note)
from .request_assignment_views import Identifier, StrictInput
from .workflow_api import StrictText
from .models import AuditLog


class DeliveryNotePermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and _permitted(request.user)


class NoteInput(StrictInput):
    request_key = serializers.UUIDField()
    job_ids = serializers.ListField(child=Identifier(min_value=1, max_value=9223372036854775807), min_length=1, max_length=100)
    comment = StrictText(max_length=4000, required=False, allow_blank=True, default='')
    def validate_request_key(self, value):
        if not isinstance(self.initial_data['request_key'], str):
            raise serializers.ValidationError('Une clé UUID texte est requise.')
        return value


class CancelInput(StrictInput):
    reason = StrictText(max_length=4000)


def _private(data, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET', 'POST'])
@permission_classes([DeliveryNotePermission])
@parser_classes([JSONParser])
def delivery_notes(request):
    if request.method == 'GET':
        return _private(list_notes(request.user))
    serializer = NoteInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = create_note(request.user, **serializer.validated_data)
    return _private(result, status=201 if result['created'] else 200)


@api_view(['GET'])
@permission_classes([DeliveryNotePermission])
def delivery_note_detail(request, note_id):
    return _private(note_payload(visible_note(request.user, note_id), request.user))


@api_view(['GET'])
@permission_classes([DeliveryNotePermission])
def delivery_note_pdf(request, note_id):
    note = visible_note(request.user, note_id)
    pdf = bytes(note.pdf_data)
    if hashlib.sha256(pdf).hexdigest() != note.pdf_sha256:
        raise DeliveryNoteConflict('Le PDF conservé ne passe plus sa vérification d’intégrité. Contactez le responsable.')
    AuditLog.objects.create(actor=request.user, action='download_delivery_note', resource='deliverynote', resource_id=str(note.pk))
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = content_disposition_header(True, f'{note.snapshot["reference"]}.pdf')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@api_view(['POST'])
@permission_classes([DeliveryNotePermission])
@parser_classes([JSONParser])
def delivery_note_cancel(request, note_id):
    serializer = CancelInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _private(cancel_note(request.user, note_id, **serializer.validated_data))
