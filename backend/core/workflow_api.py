from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import OperationEvent, ServiceRequest
from .request_assignment import MAX_REVISION, require_accepted_assignment
from .workflow import technician_can_write
from .workflow_events import append_event


class OperationEventSerializer(serializers.ModelSerializer):
    equipment_serial = serializers.CharField(source='equipment.serial_number', read_only=True)
    related_equipment_serial = serializers.CharField(source='related_equipment.serial_number', read_only=True, default=None)
    request_reference = serializers.CharField(source='service_request.reference', read_only=True, default=None)
    intervention_reference = serializers.CharField(source='intervention.reference', read_only=True, default=None)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = OperationEvent
        fields = ['id', 'equipment', 'equipment_serial', 'related_equipment', 'related_equipment_serial', 'service_request', 'request_reference', 'intervention', 'intervention_reference', 'kind', 'actor_name', 'created_at', 'recorded_created_at', 'status_before', 'status_after', 'observation', 'summary', 'is_internal', 'source']
        read_only_fields = fields

    def get_actor_name(self, obj):
        user = self.context['request'].user
        return 'Équipe SAV' if user.effective_role == 'client' else obj.actor_label


class StrictText(serializers.CharField):
    def to_internal_value(self, value):
        if not isinstance(value, str) or '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            self.fail('invalid')
        return super().to_internal_value(value)


class StrictBoolean(serializers.BooleanField):
    def to_internal_value(self, value):
        if type(value) is not bool:
            self.fail('invalid', input=value)
        return value


class AppendOperationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['observation', 'summary', 'status_changed'])
    observation = StrictText(max_length=10000, allow_blank=True, required=False, default='')
    summary = StrictText(max_length=10000, allow_blank=True, required=False, default='')
    is_internal = StrictBoolean(required=False, default=True)
    status_after = serializers.ChoiceField(choices=ServiceRequest.Status.choices, required=False)
    expected_status = serializers.ChoiceField(choices=ServiceRequest.Status.choices, required=False)
    assignment_revision = serializers.IntegerField(min_value=0, max_value=MAX_REVISION, required=False)

    def validate_assignment_revision(self, value):
        if type(self.initial_data.get('assignment_revision')) is not int:
            raise ValidationError('Un entier JSON est requis.')
        return value

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise ValidationError({'non_field_errors': ['Un objet JSON est requis.']})
        if set(data) - set(self.fields):
            raise ValidationError({'non_field_errors': ['Un champ fourni ne peut pas être écrit dans une opération historique.']})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs['kind'] == 'status_changed':
            if not attrs.get('status_after'):
                raise ValidationError({'status_after': 'Choisissez le nouvel état du dossier.'})
        elif 'status_after' in attrs:
            raise ValidationError({'status_after': 'Utilisez une opération de changement d’état.'})
        elif not (attrs['observation'].strip() or attrs['summary'].strip()):
            raise ValidationError('Renseignez une observation ou une synthèse.')
        return attrs


def visible_events(queryset, user):
    if user.effective_role == 'client':
        queryset = queryset.filter(is_internal=False, equipment__client_id=user.client_id).filter(
            Q(related_equipment__isnull=True) | Q(related_equipment__client_id=user.client_id))
    return queryset.select_related('equipment', 'related_equipment', 'service_request', 'intervention')


def timeline_response(request, *, equipment=None, service_request=None):
    if service_request is not None:
        equipment = service_request.equipment
        events = OperationEvent.objects.filter(service_request=service_request)
    else:
        events = OperationEvent.objects.filter(Q(equipment=equipment) | Q(related_equipment=equipment))
    if request.method == 'GET':
        return Response(OperationEventSerializer(visible_events(events, request.user), many=True, context={'request': request}).data)
    from .request_tracking import require_tracking_actor, write_followup
    require_tracking_actor(request.user)
    role = request.user.effective_role
    if role == 'technician':
        if service_request is not None:
            allowed = technician_can_write(request.user, service_request)
        else:
            allowed = any(technician_can_write(request.user, item) for item in equipment.service_requests.filter(assigned_technician=request.user))
        if not allowed:
            raise PermissionDenied('Cette opération est réservée à l’équipe affectée au dossier.')
    serializer = AppendOperationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if service_request is not None:
        payload = {
            'status': data.get('status_after', service_request.status),
            'observation': data['observation'], 'summary': data['summary'], 'is_internal': data['is_internal'],
            **{key: data[key] for key in ('expected_status', 'assignment_revision') if key in data},
        }
        result = write_followup(
            service_request.pk, payload, actor=request.user,
            require_preconditions=role == 'technician' and data['kind'] == 'status_changed',
            reject_unchanged=data['kind'] == 'status_changed',
            note_kind='observation' if data['kind'] == 'status_changed' else data['kind'],
            keep_status=data['kind'] != 'status_changed',
        )
        response = Response(OperationEventSerializer(result.events[0], context={'request': request}).data, status=201)
        response['Cache-Control'] = 'private, no-store'
        return response
    if data['kind'] == 'status_changed':
        raise ValidationError('Changez l’état depuis la timeline du dossier concerné.')
    if 'expected_status' in data or 'assignment_revision' in data:
        raise ValidationError('Les préconditions de suivi exigent le dossier concerné.')
    with transaction.atomic():
        actor = request.user
        if role == 'technician':
            candidates = equipment.service_requests.filter(assigned_technician=request.user).values_list('pk', flat=True)
            locked = list(ServiceRequest.objects.select_for_update().filter(pk__in=candidates).order_by('pk'))
            writable = next((item for item in locked if technician_can_write(request.user, item)), None)
            if writable is None:
                raise PermissionDenied()
            actor = require_accepted_assignment(request.user, writable)
        else:
            # Also re-read a manager's active role before an equipment-only note.
            from .request_assignment import require_internal_actor
            actor = require_internal_actor(request.user)
        event = append_event(equipment=equipment, service_request=service_request, actor=actor,
                             kind=data['kind'], observation=data['observation'], summary=data['summary'], is_internal=data['is_internal'])
    return Response(OperationEventSerializer(event, context={'request': request}).data, status=201)
