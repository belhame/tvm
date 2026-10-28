"""Atomic request follow-up, independent of a scheduled intervention.

Only immutable history stores observations and summaries. A private note never
becomes client-visible simply because its associated status changed.
"""
from dataclasses import dataclass

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import AuditLog, ServiceRequest
from .request_assignment import MAX_REVISION, require_accepted_assignment
from .workflow_events import actor_context, append_event


class FollowupConflict(APIException):
    status_code = 409
    default_detail = 'Le dossier ou son affectation a changé. Rechargez sa fiche avant d’enregistrer le suivi.'


class StrictRevision(serializers.IntegerField):
    def to_internal_value(self, value):
        if type(value) is not int:
            self.fail('invalid')
        return super().to_internal_value(value)


class StrictBatteryCount(serializers.IntegerField):
    def to_internal_value(self, value):
        if type(value) is not int:
            self.fail('invalid')
        return super().to_internal_value(value)


class FollowupInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=ServiceRequest.Status.choices)
    expected_status = serializers.ChoiceField(choices=ServiceRequest.Status.choices, required=False)
    assignment_revision = StrictRevision(min_value=0, max_value=MAX_REVISION, required=False)
    battery_count = StrictBatteryCount(min_value=0, max_value=100000, allow_null=True, required=False)

    def get_fields(self):
        # Local import keeps the legacy timeline's strict scalar validators in
        # one place without an import cycle between its adapter and this service.
        from .workflow_api import StrictBoolean, StrictText
        fields = super().get_fields()
        fields.update({
            'observation': StrictText(max_length=10000, allow_blank=True, required=False, default=''),
            'summary': StrictText(max_length=10000, allow_blank=True, required=False, default=''),
            'is_internal': StrictBoolean(required=False, default=True),
        })
        if self.context.get('require_preconditions', True):
            fields['expected_status'].required = True
            fields['assignment_revision'].required = True
        return fields

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise ValidationError({'non_field_errors': ['Un objet JSON est requis.']})
        if set(data) - set(self.fields):
            raise ValidationError({'non_field_errors': ['Le suivi contient un champ qui ne peut pas être écrit.']})
        return super().to_internal_value(data)


@dataclass(frozen=True)
class FollowupResult:
    service_request: ServiceRequest
    events: list


def require_tracking_actor(actor):
    if not actor or not actor.is_authenticated or not actor.is_active or actor.effective_role not in ('admin', 'manager', 'technician'):
        raise PermissionDenied('Le suivi est réservé aux utilisateurs internes actifs.')


def check_tracking_preconditions(record, data):
    if ('expected_status' in data and data['expected_status'] != record.status) or ('assignment_revision' in data and data['assignment_revision'] != record.assignment_revision):
        raise FollowupConflict()


@transaction.atomic
def write_followup(identifier, payload, *, actor, require_preconditions=True, reject_unchanged=False, note_kind=None, keep_status=False):
    require_tracking_actor(actor)
    serializer = FollowupInput(data=payload, context={'require_preconditions': require_preconditions})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    record = ServiceRequest.objects.select_for_update().filter(pk=identifier).first()
    if record is None:
        raise NotFound('Ce dossier n’est pas accessible.')
    actor = require_accepted_assignment(actor, record)
    check_tracking_preconditions(record, data)
    before, after = record.status, record.status if keep_status else data['status']
    changing = before != after
    if changing and not data['observation'].strip():
        raise ValidationError({'observation': 'Expliquez le changement d’état dans une observation.'})
    if not changing and reject_unchanged:
        raise ValidationError({'status_after': 'Le dossier possède déjà cet état.'})
    if not changing and not (data['observation'].strip() or data['summary'].strip()):
        raise ValidationError({'observation': 'Renseignez une observation ou une synthèse.'})
    if changing and after == 'new' and record.assigned_technician_id:
        raise ValidationError({'status': 'Un dossier affecté ne peut pas revenir à Non affecté. Le responsable doit d’abord retirer l’affectation.'})
    events = []
    with actor_context(actor):
        battery_event = None
        if 'battery_count' in data:
            from .request_batteries import apply_request_battery_count
            battery_event = apply_request_battery_count(record, data['battery_count'], actor=actor)
        record._operation_manual_event = True
        record.status = after
        try:
            fields = ['status', 'updated_at'] if changing else ['updated_at']
            if 'battery_count' in data:
                fields += ['battery_count', 'battery_count_source', 'battery_reference']
            record.save(update_fields=fields)
        finally:
            record._operation_manual_event = False
        if changing:
            events.append(append_event(
                equipment=record.equipment, service_request=record, actor=actor,
                kind='status_changed', status_before=before, status_after=after, is_internal=False, source='followup',
                observation='' if data['is_internal'] else data['observation'],
                summary='État de la demande modifié.' if data['is_internal'] else data['summary'],
            ))
        if not changing or data['is_internal']:
            events.append(append_event(
                equipment=record.equipment, service_request=record, actor=actor,
                kind=note_kind or ('summary' if data['summary'].strip() else 'observation'),
                observation=data['observation'], summary=data['summary'], is_internal=data['is_internal'], source='followup',
            ))
        if battery_event:
            events.append(battery_event)
        AuditLog.objects.create(actor=actor, action='followup', resource='servicerequest', resource_id=str(record.pk))
    return FollowupResult(record, events)


