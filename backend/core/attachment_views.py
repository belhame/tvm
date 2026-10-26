from django.http import FileResponse
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .attachment_models import RequestAttachment
from .attachment_service import can_write_documents, create_document, delete_document, visible_document, visible_request
from .attachment_storage import private_path
from .attachment_validation import ALLOWED_EXTENSIONS, MAX_FILE_SIZE


class AttachmentInput(serializers.Serializer):
    label = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    client_visible = serializers.CharField(required=False, default='false', trim_whitespace=False)

    def validate_client_visible(self, value):
        if value not in ('true', 'false'):
            raise serializers.ValidationError('Utilisez exactement true ou false pour le partage client.')
        return value == 'true'


def document_metadata(document, request):
    return {
        'id': document.pk, 'service_request': document.service_request_id,
        'label': document.label, 'original_name': document.original_name,
        'mime_type': document.mime_type, 'size_bytes': document.size_bytes,
        'sha256': document.sha256, 'client_visible': document.client_visible,
        'uploaded_by_name': 'Équipe SAV' if request.user.effective_role == 'client' else document.uploaded_by_label,
        'created_at': document.created_at.isoformat(),
        'can_delete': can_write_documents(request.user, document.service_request),
        'download_url': f'/api/documents/{document.pk}/download/',
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def request_documents(request, request_id):
    service_request = visible_request(request.user, request_id)
    if request.method == 'GET':
        documents = RequestAttachment.objects.filter(service_request=service_request, deleted_at__isnull=True).select_related('service_request')
        if request.user.effective_role == 'client':
            documents = documents.filter(client_visible=True)
        response = Response({
            'results': [document_metadata(document, request) for document in documents],
            'can_upload': can_write_documents(request.user, service_request),
            'max_file_size': MAX_FILE_SIZE, 'allowed_extensions': list(ALLOWED_EXTENSIONS),
            'virus_scanned': False,
        })
    else:
        if not can_write_documents(request.user, service_request):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Vous ne pouvez pas ajouter de pièce jointe à ce dossier.')
        unknown = set(request.data) - {'file', 'label', 'client_visible'}
        if unknown or any(len(request.data.getlist(key)) != 1 for key in request.data if key != 'file'):
            raise ValidationError({'detail': 'Le formulaire contient un champ non pris en charge ou dupliqué.'})
        files = request.FILES.getlist('file')
        if len(files) != 1:
            raise ValidationError({'file': 'Joignez exactement un fichier dans le champ file.'})
        # DRF's HTML form handling treats an empty optional CharField as
        # missing. Sharing must instead accept only these explicit tokens.
        if 'client_visible' in request.data and request.data['client_visible'] not in ('true', 'false'):
            raise ValidationError({'client_visible': 'Utilisez exactement true ou false pour le partage client.'})
        serializer = AttachmentInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = create_document(service_request=service_request, uploaded=files[0], actor=request.user, **serializer.validated_data)
        response = Response(document_metadata(document, request), status=status.HTTP_201_CREATED)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def document_download(request, document_id):
    document = visible_document(request.user, document_id)
    try:
        file = private_path(document.stored_name).open('rb')
    except (OSError, ValueError) as exc:
        raise NotFound('Le fichier privé n’est plus disponible. Contactez le responsable SAV.') from exc
    response = FileResponse(file, as_attachment=True, filename=document.original_name, content_type=document.mime_type)
    response['Cache-Control'] = 'private, no-store'
    response['Pragma'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def document_delete(request, document_id):
    document = visible_document(request.user, document_id)
    result = delete_document(document=document, actor=request.user)
    response = Response(status=status.HTTP_204_NO_CONTENT) if result['purged'] else Response(
        {'detail': 'Le document a été retiré. La suppression physique est en attente de reprise.'}, status=status.HTTP_202_ACCEPTED,
    )
    response['Cache-Control'] = 'private, no-store'
    return response
