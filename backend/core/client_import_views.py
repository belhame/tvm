from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .client_import import MAX_CLIENT_BYTES, ClientImportError, import_clients_csv
from .permissions import ManagerPermission


class ClientUploadTooLarge(APIException):
    status_code = 413
    default_detail = 'Le fichier clients dépasse la limite de 2 Mio.'


@api_view(['POST'])
@permission_classes([ManagerPermission])
@parser_classes([MultiPartParser, FormParser])
def client_import(request):
    files = request.FILES.getlist('file')
    if len(files) != 1 or set(request.FILES) != {'file'}:
        raise ValidationError({'file': 'Joignez exactement un fichier CSV clients dans le champ file.'})
    mode = request.data.get('mode', 'preview')
    if mode not in ('preview', 'apply'):
        raise ValidationError({'mode': 'Choisissez preview ou apply.'})
    uploaded = files[0]
    if uploaded.size > MAX_CLIENT_BYTES:
        raise ClientUploadTooLarge()
    data = bytearray()
    for chunk in uploaded.chunks():
        if len(data) + len(chunk) > MAX_CLIENT_BYTES:
            raise ClientUploadTooLarge()
        data.extend(chunk)
    try:
        result = import_clients_csv(bytes(data), uploaded.name, actor=request.user, apply=mode == 'apply', expected_sha256=request.data.get('sha256'))
    except ClientImportError as exc:
        raise ValidationError({'file': str(exc)}) from exc
    response = Response(result)
    response['Cache-Control'] = 'private, no-store'
    return response
