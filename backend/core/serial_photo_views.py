"""Authenticated photograph recognition, separate from receiving equipment."""
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .serial_photo import MAX_PHOTO_BYTES, SerialPhotoTooLarge, recognize_serial_photo
from .logistics_permissions import logistics_receiver


class SerialPhotoPermission(BasePermission):
    def has_permission(self, request, view):
        return logistics_receiver(request.user)


@api_view(['POST'])
@permission_classes([SerialPhotoPermission])
@parser_classes([MultiPartParser])
def recognize_serial(request):
    files = request.FILES.getlist('file')
    if len(files) != 1 or set(request.FILES) != {'file'} or set(request.data) != {'file'}:
        raise ValidationError({'file': 'Joignez exactement une photo JPEG, PNG ou WEBP dans le champ file.'})
    uploaded = files[0]
    if uploaded.size > MAX_PHOTO_BYTES:
        raise SerialPhotoTooLarge()
    data = bytearray()
    for chunk in uploaded.chunks():
        if len(data) + len(chunk) > MAX_PHOTO_BYTES:
            raise SerialPhotoTooLarge()
        data.extend(chunk)
    response = Response(recognize_serial_photo(bytes(data)))
    response['Cache-Control'] = 'private, no-store'
    return response
