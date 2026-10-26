"""Bound photograph uploads before CSRF reads multipart data."""
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import JsonResponse


PHOTO_PATH = '/api/logistics/recognize-serial/'
MAX_BYTES = 8 * 1024 * 1024
MAX_BODY = 9 * 1024 * 1024


class BoundedSerialPhotoUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.total_bytes = 0
    def receive_data_chunk(self, raw_data, start):
        self.total_bytes += len(raw_data)
        if self.total_bytes > MAX_BYTES:
            self.request._serial_photo_too_large = True
            raise StopUpload(connection_reset=True)
        return raw_data
    def file_complete(self, file_size):
        return None


class SerialPhotoUploadLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.method != 'POST' or request.path_info != PHOTO_PATH:
            return self.get_response(request)
        raw_length = request.META.get('CONTENT_LENGTH', '')
        try:
            length = int(raw_length) if raw_length else None
            if length is not None and length < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'Taille de requête invalide.'}, status=400)
        if length is not None and length > MAX_BODY:
            return JsonResponse({'detail': 'La requête dépasse 9 Mio ; la photo est limitée à 8 Mio.'}, status=413)
        request.upload_handlers.insert(0, BoundedSerialPhotoUploadHandler(request))
        response = self.get_response(request)
        if getattr(request, '_serial_photo_too_large', False):
            return JsonResponse({'detail': 'La photo dépasse la limite de 8 Mio.'}, status=413)
        return response
