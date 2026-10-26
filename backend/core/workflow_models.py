from django.core.exceptions import ValidationError
from django.db import models


class ImmutableEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Les opérations historiques ne peuvent pas être modifiées.')

    def delete(self):
        raise ValidationError('Les opérations historiques ne peuvent pas être supprimées.')


class OperationEvent(models.Model):
    """Append-only business history; corrections are new observations."""
    equipment = models.ForeignKey('core.Equipment', on_delete=models.PROTECT, related_name='operation_events')
    related_equipment = models.ForeignKey('core.Equipment', on_delete=models.PROTECT, null=True, blank=True, related_name='related_operation_events')
    service_request = models.ForeignKey('core.ServiceRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='operation_events')
    intervention = models.ForeignKey('core.Intervention', on_delete=models.PROTECT, null=True, blank=True, related_name='operation_events')
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT, null=True, blank=True, related_name='operation_events')
    actor_label = models.CharField(max_length=301, blank=True)
    kind = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
    status_before = models.CharField(max_length=20, blank=True)
    status_after = models.CharField(max_length=20, blank=True)
    observation = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    is_internal = models.BooleanField(default=False)
    source = models.CharField(max_length=20, default='application')
    recorded_created_at = models.DateTimeField(null=True, blank=True)
    objects = ImmutableEventQuerySet.as_manager()

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['equipment', 'created_at'], name='core_operat_equipme_a7d65b_idx'), models.Index(fields=['service_request', 'created_at'], name='core_operat_service_c795da_idx')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Les opérations historiques ne peuvent pas être modifiées.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Les opérations historiques ne peuvent pas être supprimées.')
