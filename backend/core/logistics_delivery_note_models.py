from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class LogisticsDeliveryNote(models.Model):
    delivery_note = models.OneToOneField('core.DeliveryNote', primary_key=True, on_delete=models.PROTECT, related_name='logistics_snapshot')
    request_key = models.UUIDField(unique=True, editable=False)
    payload_hash = models.CharField(max_length=64, editable=False)
    assigned_courier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='prepared_logistics_notes')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_logistics_notes')
    created_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=12, choices=[('prepared', 'Préparé'), ('cancelled', 'Annulé')], default='prepared')
    snapshot = models.JSONField(editable=False)
    pdf_data = models.BinaryField(editable=False)
    pdf_sha256 = models.CharField(max_length=64, editable=False)
    sealed_at = models.DateTimeField(null=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='cancelled_logistics_notes')
    cancellation_reason = models.TextField(blank=True)
    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.CheckConstraint(condition=(
            models.Q(state='prepared', cancelled_at__isnull=True, cancelled_by__isnull=True, cancellation_reason='')
            | (models.Q(state='cancelled', cancelled_at__isnull=False) & ~models.Q(cancellation_reason=''))
        ), name='logistics_note_cancellation_consistent')]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old and old.sealed_at:
                changed = {field.attname for field in self._meta.concrete_fields if getattr(old, field.attname) != getattr(self, field.attname)}
                if changed - {'state', 'cancelled_at', 'cancelled_by_id', 'cancellation_reason'} or old.state == 'cancelled' and changed:
                    raise ValidationError('Un bon de livraison préparé est immuable. Annulez sa préparation pour le remplacer.')
                if self.state not in (old.state, 'cancelled'):
                    raise ValidationError('Un bon de livraison annulé ne peut pas être réactivé.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Le bon de livraison et son PDF restent conservés.')


class DeliveryNoteMission(models.Model):
    note = models.ForeignKey(LogisticsDeliveryNote, on_delete=models.PROTECT, related_name='missions')
    job = models.ForeignKey('core.OutboundJob', on_delete=models.PROTECT, related_name='delivery_note_links')
    assignment_revision = models.PositiveIntegerField()
    equipment = models.ForeignKey('core.Equipment', on_delete=models.PROTECT, related_name='delivery_note_missions')
    active = models.BooleanField(default=True)
    class Meta:
        ordering = ['pk']
        constraints = [models.UniqueConstraint(fields=['note', 'job'], name='logistics_note_job_unique'),
                       models.UniqueConstraint(fields=['job'], condition=models.Q(active=True), name='logistics_note_active_job_unique')]

    def save(self, *args, **kwargs):
        if self.pk or self.note.sealed_at:
            raise ValidationError('Les lignes d’un bon préparé ne peuvent pas être réécrites.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Les lignes historiques du bon restent conservées.')
