"""Repair estimates, separate from non-repairable diagnostic billing."""
from django.db import models
from rest_framework.exceptions import ValidationError


class RepairQuoteBook(models.Model):
    service_request = models.OneToOneField('core.ServiceRequest', on_delete=models.PROTECT, related_name='repair_quote_book')
    current_quote = models.ForeignKey('core.RepairQuote', on_delete=models.PROTECT, null=True, blank=True, related_name='current_for_books')
    last_version = models.PositiveIntegerField(default=0)
    decision_revision = models.PositiveBigIntegerField(default=0)
    current_decision = models.ForeignKey('core.RepairQuoteDecision', on_delete=models.PROTECT, null=True, blank=True, related_name='current_for_books')


class RepairQuote(models.Model):
    book = models.ForeignKey(RepairQuoteBook, on_delete=models.PROTECT, related_name='quotes')
    client = models.ForeignKey('core.Client', on_delete=models.PROTECT, related_name='repair_quotes')
    version = models.PositiveIntegerField()
    state = models.CharField(max_length=12, choices=[('draft', 'Brouillon'), ('issued', 'Émis')], default='draft')
    revision = models.PositiveBigIntegerField(default=0)
    request_key = models.UUIDField(unique=True, editable=False)
    create_hash = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='created_repair_quotes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    amounts = models.JSONField()
    terms = models.TextField(blank=True)
    valid_until = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey('core.User', on_delete=models.PROTECT, null=True, blank=True, related_name='issued_repair_quotes')
    issue_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    issue_revision = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    snapshot = models.JSONField(default=dict, editable=False)
    pdf_data = models.BinaryField(default=bytes, editable=False)
    pdf_sha256 = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['book', 'version'], name='repair_quote_version_unique'),
            models.UniqueConstraint(fields=['book'], condition=models.Q(state='draft'), name='repair_quote_single_draft'),
            models.UniqueConstraint(fields=['reference'], condition=~models.Q(reference=''), name='repair_quote_reference_unique'),
            models.CheckConstraint(condition=models.Q(version__gte=1), name='repair_quote_version_positive'),
            models.CheckConstraint(condition=(models.Q(state='draft', issued_at__isnull=True, issued_by__isnull=True, issue_key__isnull=True, issue_revision__isnull=True, reference='', pdf_sha256='') | (models.Q(state='issued', issued_at__isnull=False, issued_by__isnull=False, issue_key__isnull=False, issue_revision__isnull=False) & ~models.Q(reference='') & ~models.Q(pdf_sha256=''))), name='repair_quote_issue_consistent'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and type(self).objects.filter(pk=self.pk, state='issued').exists():
            raise ValidationError('Un devis émis est immuable. Préparez une nouvelle révision.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Les devis sont conservés dans leur historique.')


class RepairQuoteDecision(models.Model):
    quote = models.ForeignKey(RepairQuote, on_delete=models.PROTECT, related_name='decisions')
    revision = models.PositiveBigIntegerField()
    request_key = models.UUIDField(unique=True, editable=False)
    expected_revision = models.PositiveBigIntegerField(editable=False)
    decision = models.CharField(max_length=12, choices=[('accepted', 'Accepté'), ('refused', 'Refusé')])
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='repair_quote_decisions')
    actor_label = models.CharField(max_length=301)
    decided_at = models.DateTimeField()
    status_changed = models.BooleanField(default=False)

    class Meta:
        ordering = ['revision', 'id']
        constraints = [
            models.UniqueConstraint(fields=['quote', 'revision'], name='repair_quote_decision_revision_unique'),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name='repair_quote_decision_revision_positive'),
            models.CheckConstraint(condition=models.Q(decision__in=['accepted', 'refused']), name='repair_quote_decision_choice'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Une décision reste conservée. Enregistrez votre nouvel avis.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Les décisions client sont conservées.')
