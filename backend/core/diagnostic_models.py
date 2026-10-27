"""Auditable technical assistance; never a business operation or provider secret."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class DiagnosticGate(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='diagnostic_gate_singleton')]


class DiagnosticRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', 'Analyse en cours'
        COMPLETED = 'completed', 'Assistance à valider'
        ABSTAINED = 'abstained', 'Sources insuffisantes'
        REQUIRES_CONFIGURATION = 'requires_configuration', 'Fournisseur à configurer'
        PROVIDER_ERROR = 'provider_error', 'Fournisseur indisponible'
        INVALID_RESPONSE = 'invalid_response', 'Réponse non vérifiable'
        SOURCES_CHANGED = 'sources_changed', 'Sources modifiées pendant l’analyse'
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='diagnostic_runs')
    actor_label = models.CharField(max_length=301)
    service_request = models.ForeignKey('core.ServiceRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='diagnostic_runs')
    request_key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=32, choices=Status.choices)
    technical_input = models.JSONField(default=dict)
    source_snapshots = models.JSONField(default=list)
    output = models.JSONField(null=True, blank=True)
    warnings = models.JSONField(default=list)
    error_code = models.CharField(max_length=80, blank=True)
    provider = models.CharField(max_length=40, default='openai_responses')
    provider_model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['actor', 'request_key'], name='diagnostic_actor_key_unique')]
