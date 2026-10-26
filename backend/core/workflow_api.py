from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import OperationEvent, ServiceRequest
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
    role = request.user.effective_role
    if role == 'client':
        raise PermissionDenied('Le portail client permet uniquement la consultation de l’historique.')
    if role == 'technician':
        if service_request is not None:
            allowed = technician_can_write(request.user, service_request)
        else:
            allowed = equipment.service_requests.filter(Q(assigned_technician=request.user) | Q(interventions__technician=request.user)).exists()
        if not allowed:
            raise PermissionDenied('Cette opération est réservée à l’équipe affectée au dossier.')
    serializer = AppendOperationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    with transaction.atomic():
        if service_request is not None:
            service_request = ServiceRequest.objects.select_for_update().get(pk=service_request.pk)
            if role == 'technician' and not technician_can_write(request.user, service_request):
                raise PermissionDenied()
        elif role == 'technician':
            candidates = equipment.service_requests.filter(Q(assigned_technician=request.user) | Q(interventions__technician=request.user)).values_list('pk', flat=True)
            locked = list(ServiceRequest.objects.select_for_update().filter(pk__in=candidates))
            if not any(technician_can_write(request.user, item) for item in locked):
                raise PermissionDenied()
        before = ''
        after = ''
        if data['kind'] == 'status_changed':
            if service_request is None:
                raise ValidationError('Changez l’état depuis la timeline du dossier concerné.')
            before = service_request.status
            after = data['status_after']
            if after == 'new' and service_request.assigned_technician_id:
                raise ValidationError({'status_after': 'Un dossier affecté ne peut pas revenir à Non affecté. Le responsable doit d’abord retirer l’affectation.'})
            if before == after:
                raise ValidationError({'status_after': 'Le dossier possède déjà cet état.'})
            service_request._operation_manual_event = True
            service_request.status = after
            service_request.save(update_fields=['status', 'updated_at'])
        private_status_note = data['kind'] == 'status_changed' and data['is_internal']
        event = append_event(equipment=equipment, service_request=service_request, actor=request.user,
                             kind=data['kind'], status_before=before, status_after=after,
                             observation='' if private_status_note else data['observation'],
                             summary='État de la demande modifié.' if private_status_note else data['summary'],
                             is_internal=False if data['kind'] == 'status_changed' else data['is_internal'])
        if private_status_note and (data['observation'] or data['summary']):
            append_event(equipment=equipment, service_request=service_request, actor=request.user,
                         kind='observation', observation=data['observation'], summary=data['summary'], is_internal=True)
    return Response(OperationEventSerializer(event, context={'request': request}).data, status=201)
