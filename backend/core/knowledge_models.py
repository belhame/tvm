"""Private, human-approved sources for technical diagnosis."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from .knowledge_normalization import normalized_key


class KnowledgeSource(models.Model):
    class State(models.TextChoices):
        DRAFT = 'draft', 'Brouillon'
        APPROVED = 'approved', 'Approuvé'
        ARCHIVED = 'archived', 'Archivé'
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=120)
    board_reference = models.CharField(max_length=120, blank=True)
    brand_key = models.CharField(max_length=200, editable=False)
    model_key = models.CharField(max_length=240, editable=False)
    board_reference_key = models.CharField(max_length=240, blank=True, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='%(class)s_created')
    created_by_label = models.CharField(max_length=301)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='%(class)s_approved')
    approved_by_label = models.CharField(max_length=301, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at', '-pk']

    def save(self, *args, **kwargs):
        self.brand_key = normalized_key(self.brand)
        self.model_key = normalized_key(self.model)
        self.board_reference_key = normalized_key(self.board_reference)
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            allowed = {'state', 'archived_at'}
            if old.state in (self.State.APPROVED, self.State.ARCHIVED):
                changed = {field.attname for field in self._meta.concrete_fields if getattr(old, field.attname) != getattr(self, field.attname)}
                if changed - allowed or (old.state == self.State.ARCHIVED and self.state != self.State.ARCHIVED) or self.state not in (old.state, self.State.ARCHIVED):
                    raise ValidationError('Une source approuvée ne peut pas être modifiée. Archivez-la et créez une nouvelle version.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Archivez la source pour la retirer de la recherche.')


class TechnicalDocument(KnowledgeSource):
    class Kind(models.TextChoices):
        MANUAL = 'manual', 'Manuel'
        SCHEMATIC = 'schematic', 'Schéma'
        PROCEDURE = 'procedure', 'Procédure'
    title = models.CharField(max_length=200)
    revision = models.CharField(max_length=80, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    stored_name = models.CharField(max_length=255, editable=False)
    original_name = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    pages = models.PositiveIntegerField()
    text_status = models.CharField(max_length=12, choices=[('extracted', 'Texte extrait'), ('partial', 'Texte partiel'), ('no_text', 'Aucun texte exploitable')])
    class Meta(KnowledgeSource.Meta):
        indexes = [models.Index(fields=['state', 'brand_key', 'model_key'], name='knowledge_doc_model_state')]


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(TechnicalDocument, on_delete=models.PROTECT, related_name='chunks')
    page = models.PositiveIntegerField()
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    class Meta:
        ordering = ['document_id', 'page', 'ordinal']
        constraints = [models.UniqueConstraint(fields=['document', 'page', 'ordinal'], name='knowledge_chunk_position_unique'),
                       models.CheckConstraint(condition=models.Q(page__gte=1, ordinal__gte=1), name='knowledge_chunk_position_positive')]

    def save(self, *args, **kwargs):
        if self.pk or self.document.state != KnowledgeSource.State.DRAFT:
            raise ValidationError('Les extraits techniques sont immuables après leur création.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Archivez le document pour retirer ses extraits de la recherche.')


class RepairCase(KnowledgeSource):
    revision = models.CharField(max_length=80, blank=True)
    intervention = models.ForeignKey('core.Intervention', on_delete=models.PROTECT, related_name='knowledge_cases')
    symptoms = models.TextField()
    fault_code = models.CharField(max_length=120, blank=True)
    measurements = models.TextField(blank=True)
    confirmed_cause = models.TextField()
    repair = models.TextField()
    outcome = models.TextField()
    class Meta(KnowledgeSource.Meta):
        indexes = [models.Index(fields=['state', 'brand_key', 'model_key'], name='knowledge_case_model_state')]
