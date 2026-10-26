"""Private request documents; stored paths are never exposed as media URLs."""

from django.conf import settings
from django.db import models


class RequestAttachment(models.Model):
    service_request = models.ForeignKey('core.ServiceRequest', on_delete=models.CASCADE, related_name='documents')
    stored_name = models.CharField(max_length=255, editable=False)
    original_name = models.CharField(max_length=200)
    label = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    client_visible = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='uploaded_request_documents')
    uploaded_by_label = models.CharField(max_length=301)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_request_documents')
    storage_deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['service_request', 'deleted_at'], name='attachment_request_active')]
