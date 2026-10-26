"""A request's explicit exchange approval and billing evidence.

Preparing a replacement is not a visit, shipment, invoice generation or payment.
Past changes remain in the append-only operation history when a draft is reset.
"""
from django.db import models


class ExchangeProcess(models.Model):
    service_request = models.OneToOneField('core.ServiceRequest', on_delete=models.PROTECT, related_name='exchange_process')
    replacement_serial_number = models.CharField(max_length=120, blank=True)
    replacement_model = models.CharField(max_length=120, blank=True)
    replacement_brand = models.CharField(max_length=100, blank=True)
    replacement_equipment = models.ForeignKey('core.Equipment', null=True, blank=True, on_delete=models.PROTECT, related_name='exchange_replacements')
    prepared_at = models.DateTimeField(null=True, blank=True)
    prepared_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='prepared_exchanges')
    validated_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='validated_exchanges')
    ready_at = models.DateTimeField(null=True, blank=True)
    ready_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='ready_exchanges')
    invoice_reference = models.CharField(max_length=120, blank=True)
    invoiced_on = models.DateField(null=True, blank=True)
    billing_validated_at = models.DateTimeField(null=True, blank=True)
    billing_validated_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='billed_exchanges')
    billing_notes = models.TextField(blank=True)
    reservation_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['replacement_equipment'], condition=models.Q(reservation_active=True), name='exchange_replacement_active_unique'),
            models.CheckConstraint(condition=models.Q(reservation_active=False) | models.Q(replacement_equipment__isnull=False, validated_at__isnull=False), name='exchange_reservation_validated'),
            models.CheckConstraint(condition=models.Q(validated_at__isnull=True, validated_by__isnull=True) | models.Q(validated_at__isnull=False, validated_by__isnull=False, replacement_equipment__isnull=False), name='exchange_validation_consistent'),
            models.CheckConstraint(condition=models.Q(ready_at__isnull=True, ready_by__isnull=True) | models.Q(ready_at__isnull=False, ready_by__isnull=False, validated_at__isnull=False), name='exchange_ready_consistent'),
            models.CheckConstraint(condition=models.Q(billing_validated_at__isnull=True, billing_validated_by__isnull=True, invoiced_on__isnull=True, invoice_reference='') | (models.Q(billing_validated_at__isnull=False, billing_validated_by__isnull=False, invoiced_on__isnull=False, ready_at__isnull=False) & ~models.Q(invoice_reference='')), name='exchange_billing_consistent'),
        ]

    def __str__(self):
        return f'Échange {self.service_request.reference}'
