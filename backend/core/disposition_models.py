"""Recorded test outcomes and immutable diagnostic quotations."""
from django.db import models
from rest_framework.exceptions import ValidationError


class DispositionProcess(models.Model):
    class Outcome(models.TextChoices):
        PENDING = 'pending', 'À qualifier'
        REPAIRED = 'repaired', 'Réparé et testé'
        NONREPAIRABLE = 'nonrepairable', 'Non réparable'
    class FeeMode(models.TextChoices):
        BILLABLE = 'billable', 'Diagnostic à facturer'
        FREE = 'free', 'Gratuité proposée'
    service_request = models.OneToOneField('core.ServiceRequest', on_delete=models.PROTECT, related_name='disposition_process')
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.PENDING)
    diagnosis = models.TextField(blank=True)
    tests_passed = models.BooleanField(default=False)
    tested_on = models.DateField(null=True, blank=True)
    classified_at = models.DateTimeField(null=True, blank=True)
    classified_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='classified_dispositions')
    requires_diagnostic_billing = models.BooleanField(default=False)
    fee_mode = models.CharField(max_length=12, choices=FeeMode.choices, default=FeeMode.BILLABLE)
    free_reason = models.TextField(blank=True)
    price_ht = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, choices=[('TND', 'TND'), ('EUR', 'EUR'), ('USD', 'USD')], default='TND')
    quote_notes = models.TextField(blank=True)
    current_quote = models.ForeignKey('core.DiagnosticQuote', null=True, blank=True, on_delete=models.PROTECT, related_name='current_for_processes')
    finance_validated_at = models.DateTimeField(null=True, blank=True)
    finance_validated_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='financed_dispositions')
    invoice_reference = models.CharField(max_length=120, blank=True)
    invoiced_on = models.DateField(null=True, blank=True)
    billing_notes = models.TextField(blank=True)
    finance_free_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(outcome='repaired') | models.Q(tests_passed=True, tested_on__isnull=False, classified_at__isnull=False, classified_by__isnull=False), name='disposition_repaired_tested'),
            models.CheckConstraint(condition=~models.Q(outcome='nonrepairable') | (models.Q(requires_diagnostic_billing=True) & ~models.Q(diagnosis='')), name='disposition_return_diagnosed'),
            models.CheckConstraint(condition=models.Q(price_ht__isnull=True) | models.Q(price_ht__gte=0), name='disposition_price_nonnegative'),
            models.CheckConstraint(condition=models.Q(vat_rate__isnull=True) | models.Q(vat_rate__gte=0, vat_rate__lte=100), name='disposition_vat_range'),
            models.CheckConstraint(condition=(models.Q(finance_validated_at__isnull=True, finance_validated_by__isnull=True, invoice_reference='', invoiced_on__isnull=True, finance_free_reason='') | (models.Q(finance_validated_at__isnull=False, finance_validated_by__isnull=False, current_quote__isnull=False) & ((models.Q(fee_mode='billable', invoiced_on__isnull=False, finance_free_reason='') & ~models.Q(invoice_reference='')) | (models.Q(fee_mode='free', invoice_reference='', invoiced_on__isnull=True) & ~models.Q(finance_free_reason=''))))), name='disposition_finance_consistent'),
        ]


class DiagnosticQuoteSequence(models.Model):
    year = models.PositiveSmallIntegerField(primary_key=True)
    last_value = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(last_value__lte=99999), name='diagnostic_quote_sequence_max')]


class ImmutableQuoteQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Un devis émis est conservé dans son état initial.')
    def delete(self):
        raise ValidationError('Un devis émis ne peut pas être supprimé.')


class DiagnosticQuote(models.Model):
    number = models.CharField(max_length=40, unique=True)
    process = models.ForeignKey(DispositionProcess, on_delete=models.PROTECT, related_name='quotes')
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='issued_diagnostic_quotes')
    snapshot = models.JSONField()
    objects = ImmutableQuoteQuerySet.as_manager()
    class Meta:
        ordering = ['-issued_at', '-id']
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Les données d’un devis émis sont immuables.')
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError('Un devis émis reste conservé dans le dossier.')
