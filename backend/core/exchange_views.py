"""Authenticated, owner-scoped exchange queues and explicit approval actions."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exchange_workflow import (bill_exchange, close_exchange, exchange_related, is_exchange_case,
                                prepare_exchange, ready_exchange, reset_exchange, validate_exchange)
from .models import ServiceRequest
from .permissions import can_validate_billing
from .preventive_visits import with_preventive_counts
from .request_numbering import reference_query_value
from .serializers import ServiceRequestSerializer
from .workflow_api import StrictText


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({'detail': 'Un objet JSON avec les seuls champs de cette action est requis.'})
        return super().to_internal_value(data)


class PreparationInput(StrictInput):
    replacement_serial_number = StrictText(max_length=120, allow_blank=True, required=False)
    replacement_model = StrictText(max_length=120, allow_blank=True, required=False)
    replacement_brand = StrictText(max_length=100, allow_blank=True, required=False)
    replacement_equipment = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class BillingInput(StrictInput):
    invoice_reference = StrictText(max_length=120)
    invoiced_on = serializers.DateField()
    billing_notes = StrictText(max_length=4000, allow_blank=True, required=False, default='')
    def validate_invoiced_on(self, value):
        if value > timezone.localdate():
            raise ValidationError('La date de facture ne peut pas être future.')
        return value


class ResetInput(StrictInput):
    reason = StrictText(max_length=4000)


def _queryset(user):
    queryset = exchange_related(with_preventive_counts(ServiceRequest.objects.select_related('equipment__client', 'assigned_technician')))
    if user.effective_role == 'client':
        queryset = queryset.filter(equipment__client_id=user.client_id)
    return queryset


def _exchanges(queryset):
    return queryset.filter(Q(status='exchange') | Q(exchange_process__isnull=False) | Q(_exchange_legacy=True) | Q(_exchange_history=True))


def _record(identifier, user):
    return get_object_or_404(_exchanges(_queryset(user)), pk=identifier)


def _response(record, request):
    # Re-read after each atomic action so reverse relation caches never expose a
    # stale draft, permission or timestamp in the mutation response.
    refreshed = _record(record.pk, request.user)
    response = Response(ServiceRequestSerializer(refreshed, context={'request': request}).data)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def exchange_list(request, billing=False):
    if billing and not can_validate_billing(request.user):
        raise PermissionDenied('Cette liste est réservée au niveau de validation de la facturation.')
    queryset = _exchanges(_queryset(request.user))
    if billing and request.query_params.get('include_closed') != '1':
        queryset = queryset.exclude(status='closed')
    query = reference_query_value(request.query_params, 'q')
    if query:
        replacement_query = Q(exchange_process__replacement_serial_number__icontains=query)
        if request.user.effective_role == 'client':
            replacement_query &= Q(exchange_process__validated_at__isnull=False)
        queryset = queryset.filter(Q(reference__icontains=query) | Q(client_reference__icontains=query) |
            Q(equipment__client__name__icontains=query) | Q(equipment__serial_number__icontains=query) |
            replacement_query)
    state = request.query_params.get('state')
    if state:
        accepted = {'awaiting_preparation', 'pending_validation', 'validated', 'ready_for_delivery', 'invoiced', 'closed'}
        if state not in accepted:
            raise ValidationError({'state': 'Étape d’échange inconnue.'})
        # Stage predicates mirror exchange_payload without trusting client data.
        if state == 'closed':
            queryset = queryset.filter(status='closed')
        else:
            queryset = queryset.exclude(status='closed')
            if state == 'invoiced':
                queryset = queryset.filter(exchange_process__billing_validated_at__isnull=False)
            else:
                queryset = queryset.filter(exchange_process__billing_validated_at__isnull=True)
                if state == 'ready_for_delivery':
                    queryset = queryset.filter(exchange_process__ready_at__isnull=False)
                else:
                    queryset = queryset.filter(exchange_process__ready_at__isnull=True)
                    if state == 'validated':
                        queryset = queryset.filter(exchange_process__validated_at__isnull=False)
                    else:
                        queryset = queryset.filter(exchange_process__validated_at__isnull=True)
                        queryset = queryset.filter(exchange_process__prepared_at__isnull=(state == 'awaiting_preparation'))
    response = Response(ServiceRequestSerializer(queryset, many=True, context={'request': request}).data)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def exchange_detail(request, request_id):
    record = _record(request_id, request.user)
    if request.method == 'PATCH':
        if request.user.effective_role == 'client':
            raise PermissionDenied('Le portail client permet uniquement la consultation de ses dossiers.')
        serializer = PreparationInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = prepare_exchange(record.pk, serializer.validated_data, actor=request.user)
    return _response(record, request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exchange_action(request, request_id, operation):
    record = _record(request_id, request.user)
    if request.user.effective_role == 'client':
        raise PermissionDenied('Le portail client permet uniquement la consultation de ses dossiers.')
    input_class = BillingInput if operation == 'billing' else ResetInput if operation == 'reset' else StrictInput
    serializer = input_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    if operation == 'billing':
        record = bill_exchange(record.pk, serializer.validated_data, actor=request.user)
    elif operation == 'reset':
        record = reset_exchange(record.pk, actor=request.user, reason=serializer.validated_data['reason'])
    else:
        action = {'validate': validate_exchange, 'ready': ready_exchange, 'close': close_exchange}.get(operation)
        if action is None:
            raise ValidationError('Action d’échange inconnue.')
        record = action(record.pk, actor=request.user)
    return _response(record, request)
