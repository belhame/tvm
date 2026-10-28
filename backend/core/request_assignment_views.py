"""Explicit assignment and acceptance actions; no automatic technician consent."""
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .request_assignment import assign_request, claim_request, confirm_assignment, takeover_request
from .serializers import ServiceRequestSerializer
from .workflow_api import StrictBoolean, StrictText


class AssignmentPermission(BasePermission):
    def has_permission(self, request, view):
        actor = request.user
        return bool(actor.is_authenticated and actor.is_active and actor.role not in ('client', 'courier')
                    and actor.effective_role in ('admin', 'manager', 'technician'))


class Identifier(serializers.IntegerField):
    def to_internal_value(self, value):
        if type(value) is not int:
            self.fail('invalid')
        return super().to_internal_value(value)


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({'non_field_errors': ['Le formulaire contient un champ inconnu.']})
        return super().to_internal_value(data)


class AssignInput(StrictInput):
    technician = Identifier(min_value=1, max_value=9223372036854775807, allow_null=True)
    expected_revision = Identifier(min_value=0, max_value=9223372036854775807)
    reason = StrictText(max_length=2000, allow_blank=True, required=False, default='')


class ConfirmInput(StrictInput):
    expected_revision = Identifier(min_value=0, max_value=9223372036854775807)
    accept = StrictBoolean()
    on_behalf = StrictBoolean(required=False, default=False)
    reason = StrictText(max_length=2000, allow_blank=True, required=False, default='')


class ClaimInput(StrictInput):
    expected_revision = Identifier(min_value=0, max_value=9223372036854775807)


class TakeoverInput(ClaimInput):
    reason = StrictText(max_length=2000)


@api_view(['POST'])
@permission_classes([AssignmentPermission])
def assignment_view(request, request_id):
    serializer = AssignInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    record = assign_request(request_id, actor=request.user, technician_id=data['technician'],
                            expected_revision=data['expected_revision'], reason=data['reason'])
    return Response(ServiceRequestSerializer(record, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([AssignmentPermission])
def confirmation_view(request, request_id):
    serializer = ConfirmInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    record = confirm_assignment(request_id, actor=request.user, **serializer.validated_data)
    return Response(ServiceRequestSerializer(record, context={'request': request}).data)


class TechnicianSelfAssignmentPermission(BasePermission):
    def has_permission(self, request, view):
        actor = request.user
        return bool(actor.is_authenticated and actor.is_active and actor.role == 'technician'
                    and actor.effective_role == 'technician')


@api_view(['POST'])
@permission_classes([TechnicianSelfAssignmentPermission])
def claim_view(request, request_id):
    serializer = ClaimInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    record = claim_request(request_id, actor=request.user, **serializer.validated_data)
    return Response(ServiceRequestSerializer(record, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([TechnicianSelfAssignmentPermission])
def takeover_view(request, request_id):
    serializer = TakeoverInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    record = takeover_request(request_id, actor=request.user, **serializer.validated_data)
    return Response(ServiceRequestSerializer(record, context={'request': request}).data)
