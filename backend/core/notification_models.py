"""Private in-app notices. This module intentionally has no outbound channel."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class DailyReminderPreferences(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_reminder_preferences')
    enabled = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class InAppNotification(models.Model):
    class Kind(models.TextChoices):
        DAILY = 'daily_logistics', 'Rappel logistique quotidien'
        RECEIVED = 'equipment_received', 'Matériel reçu'
        DELIVERED = 'equipment_delivered', 'Remise enregistrée'

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='in_app_notifications')
    kind = models.CharField(max_length=32, choices=Kind.choices)
    dedup_key = models.CharField(max_length=160)
    local_date = models.DateField()
    service_request = models.ForeignKey('core.ServiceRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='in_app_notifications')
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['recipient', 'dedup_key'], name='notification_recipient_dedup_unique'),
            models.UniqueConstraint(fields=['recipient', 'kind', 'local_date'], condition=models.Q(kind='daily_logistics'), name='notification_daily_recipient_unique'),
        ]
