"""External delivery records; no provider secret or old contact is stored here."""
import uuid

from django.db import models
from django.utils import timezone


class ExternalNotification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = 'email', 'E-mail'
        WHATSAPP = 'whatsapp', 'WhatsApp'

    class State(models.TextChoices):
        BLOCKED = 'blocked', 'Bloqué'
        PENDING = 'pending', 'À traiter'
        PROCESSING = 'processing', 'En cours'
        SENT = 'sent', 'Accepté par le fournisseur'
        FAILED = 'failed', 'Échec'
        UNCERTAIN = 'uncertain', 'Acceptation incertaine'
        CANCELLED = 'cancelled', 'Événement remplacé'

    client = models.ForeignKey('core.Client', on_delete=models.PROTECT, related_name='external_notifications')
    outbound = models.ForeignKey('core.OutboundJob', null=True, blank=True, on_delete=models.PROTECT, related_name='external_notifications')
    pickup = models.ForeignKey('core.PickupRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='external_notifications')
    channel = models.CharField(max_length=12, choices=Channel.choices)
    event = models.CharField(max_length=40)
    event_key = models.CharField(max_length=180)
    revision = models.PositiveIntegerField(default=1)
    context_hash = models.CharField(max_length=64)
    recipient_hash = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.BLOCKED)
    blocked_reason = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)
    delivery_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    recipient_redacted = models.CharField(max_length=180, blank=True)
    provider_status = models.CharField(max_length=40, blank=True)
    provider_message_id = models.CharField(max_length=200, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['event_key', 'channel'], name='outbox_event_channel_unique'),
            models.CheckConstraint(condition=(models.Q(outbound__isnull=False, pickup__isnull=True) | models.Q(outbound__isnull=True, pickup__isnull=False)), name='outbox_one_logistics_source'),
            models.CheckConstraint(condition=~models.Q(state='sent') | models.Q(sent_at__isnull=False, provider_status='accepted'), name='outbox_sent_requires_acceptance'),
        ]
