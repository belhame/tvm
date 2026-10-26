"""Install upload limits before CSRF/session authentication parses multipart."""

import re

from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import JsonResponse

from .attachment_validation import MAX_FILE_SIZE


MAX_MULTIPART_BODY = 11 * 1024 * 1024
DOCUMENT_UPLOAD = re.compile(r'^/api/requests/[0-9]+/documents/$')


class BoundedDocumentUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.total_bytes = 0
        self.file_bytes = 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_bytes = 0

    def receive_data_chunk(self, raw_data, start):
        self.total_bytes += len(raw_data)
        self.file_bytes += len(raw_data)
        if self.file_bytes > MAX_FILE_SIZE or self.total_bytes > MAX_FILE_SIZE:
            self.request._document_upload_too_large = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None


class AttachmentUploadLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'POST' or not DOCUMENT_UPLOAD.fullmatch(request.path_info):
            return self.get_response(request)
        raw_length = request.META.get('CONTENT_LENGTH', '')
        try:
            length = int(raw_length) if raw_length else None
            if length is not None and length < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'Taille de requête invalide.'}, status=400)
        if length is not None and length > MAX_MULTIPART_BODY:
            return JsonResponse({'detail': 'La requête dépasse la limite de 11 Mio (fichier : 10 Mio).'}, status=413)
        # Must run before CsrfViewMiddleware and DRF SessionAuthentication, both
        # of which may access request.POST before the API view is entered.
        request.upload_handlers.insert(0, BoundedDocumentUploadHandler(request))
        response = self.get_response(request)
        if getattr(request, '_document_upload_too_large', False):
            return JsonResponse({'detail': 'La pièce jointe dépasse la limite de 10 Mio.'}, status=413)
        return response
