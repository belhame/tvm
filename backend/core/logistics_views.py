"""Minimal logistics endpoints, separate from internal SAV/financial APIs."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .exchange_views import StrictInput
from .logistics_permissions import LogisticsOperatorPermission, logistics_manager, logistics_receiver
from .models import Client
from .request_numbering import reference_query_value
from .workflow_api import StrictBoolean, StrictText


class ParticipantPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and (
            user.effective_role in ('admin', 'manager', 'courier') or
            (user.effective_role == 'client' and user.client_id)))


class LogisticsManagerPermission(BasePermission):
    def has_permission(self, request, view):
        return logistics_manager(request.user)


class InternalLogisticsPermission(BasePermission):
    message = 'La réception atelier et les collectes sont réservées à l’équipe TVM.'

    def has_permission(self, request, view):
        return logistics_receiver(request.user)


class StrictId(serializers.IntegerField):
    def __init__(self, **kwargs):
        super().__init__(min_value=1, max_value=9223372036854775807, **kwargs)

    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail('invalid')
        return super().to_internal_value(data)


class StrictUuid(serializers.UUIDField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        return super().to_internal_value(data)


class LookupInput(StrictInput):
    serial_number = StrictText(max_length=120)
    profile = StrictText(max_length=40, required=False)
    product_id = StrictId(required=False)
    catalogue_import_id = StrictId(required=False)


class ReceiveInput(LookupInput):
    request_key = StrictUuid()
    client = StrictId()
    pickup = StrictId(required=False)
    service_request = StrictId(required=False)
    client_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    fault_description = StrictText(max_length=4000, required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(choices=['manual', 'usb', 'camera', 'photo'], default='manual')
    manual_model = StrictText(max_length=120, required=False, allow_blank=True)
    manual_brand = StrictText(max_length=100, required=False, allow_blank=True)
    manual_reason = StrictText(max_length=4000, required=False, allow_blank=True)

    def validate(self, attrs):
        if any(attrs.get(key) for key in ('manual_model', 'manual_brand', 'manual_reason')):
            if not attrs.get('manual_model') or not attrs.get('manual_reason'):
                raise serializers.ValidationError('Un modèle manuel exige son nom et une justification.')
        return attrs


class PickupInput(StrictInput):
    request_key = StrictUuid()
    client = StrictId(required=False)
    pickup_scope = serializers.ChoiceField(choices=['direct', 'end_customer'], required=False, default='direct')
    end_customer_name = StrictText(max_length=200, required=False, allow_blank=True, default='')
    equipment = StrictId(required=False)
    serial_number = StrictText(max_length=120, required=False)
    brand = StrictText(max_length=100, required=False, allow_blank=True, default='')
    model = StrictText(max_length=120, required=False, allow_blank=True, default='')
    client_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    fault_description = StrictText(max_length=4000)
    pickup_address = StrictText(max_length=4000)
    contact_name = StrictText(max_length=150)
    contact_phone = StrictText(max_length=40, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if not attrs.get('equipment') and not attrs.get('serial_number'):
            raise serializers.ValidationError({'serial_number': 'Sélectionnez votre équipement ou renseignez son numéro de série.'})
        if attrs.get('pickup_scope') == 'end_customer' and not attrs.get('end_customer_name'):
            raise serializers.ValidationError({'end_customer_name': 'Renseignez le nom du client final chez qui collecter l’onduleur.'})
        return attrs


class AssignmentInput(StrictInput):
    courier = StrictId()


class OutboundAssignmentInput(AssignmentInput):
    service_request = StrictId(required=False)
    delivery_address = StrictText(max_length=4000, allow_blank=True, required=False)
    contact_name = StrictText(max_length=150, allow_blank=True, required=False)
    contact_phone = StrictText(max_length=40, allow_blank=True, required=False)


class ReasonInput(StrictInput):
    reason = StrictText(max_length=4000)


class HandoffInput(StrictInput):
    recipient_name = StrictText(max_length=150)


class ReconcileInput(StrictInput):
    client = StrictId(required=False)
    reassign_automatic = StrictBoolean(required=False, default=False)


def _input(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _private(data, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([LogisticsOperatorPermission])
def bootstrap(request):
    from .logistics_payloads import bootstrap_payload
    return _private(bootstrap_payload(request.user, q=reference_query_value(request.query_params, 'q')))


@api_view(['GET'])
@permission_classes([InternalLogisticsPermission])
def clients(request):
    queryset = Client.objects.order_by('name', 'id')
    query = reference_query_value(request.query_params, 'q')
    if query:
        queryset = queryset.filter(name__icontains=query)
    return _private(list(queryset.values('id', 'name')[:250]))


@api_view(['POST'])
@permission_classes([InternalLogisticsPermission])
@parser_classes([JSONParser])
def lookup(request):
    from .logistics_service import lookup as lookup_serial
    data = _input(LookupInput, request)
    serial_number = data.pop('serial_number')
    return _private(lookup_serial(serial_number, **data))


@api_view(['POST'])
@permission_classes([InternalLogisticsPermission])
@parser_classes([JSONParser])
def receive(request):
    from .logistics_service import receive as receive_equipment
    from .logistics_payloads import receipt_payload
    receipt = receive_equipment(request.user, _input(ReceiveInput, request))
    return _private(receipt_payload(receipt))


@api_view(['GET', 'POST'])
@permission_classes([ParticipantPermission])
@parser_classes([JSONParser])
def pickups(request):
    from .logistics_service import create_pickup, pickups_for
    from .logistics_payloads import pickup_payload
    if request.method == 'POST':
        if request.user.effective_role != 'client' and not logistics_manager(request.user):
            raise PermissionDenied('Le client ou le responsable TVM enregistre la demande d’enlèvement.')
        record = create_pickup(request.user, _input(PickupInput, request))
        return _private(pickup_payload(record, request.user))
    queryset = pickups_for(request.user)
    query = reference_query_value(request.query_params, 'q')
    if query:
        queryset = queryset.filter(Q(serial_number__icontains=query) | Q(client_reference__icontains=query) |
                                   Q(client__name__icontains=query) | Q(service_request__reference__icontains=query))
    return _private([pickup_payload(row, request.user) for row in queryset])


@api_view(['GET'])
@permission_classes([ParticipantPermission])
def pickup_detail(request, pickup_id):
    from .logistics_service import pickups_for
    from .logistics_payloads import pickup_payload
    return _private(pickup_payload(get_object_or_404(pickups_for(request.user), pk=pickup_id), request.user))


@api_view(['POST'])
@permission_classes([LogisticsManagerPermission])
@parser_classes([JSONParser])
def pickup_assign(request, pickup_id):
    from .logistics_service import assign_pickup
    from .logistics_payloads import pickup_payload
    return _private(pickup_payload(assign_pickup(request.user, pickup_id, _input(AssignmentInput, request)), request.user))


@api_view(['POST'])
@permission_classes([InternalLogisticsPermission])
@parser_classes([JSONParser])
def pickup_collect(request, pickup_id):
    from .logistics_service import collect_pickup
    from .logistics_payloads import pickup_payload
    _input(StrictInput, request)
    return _private(pickup_payload(collect_pickup(request.user, pickup_id), request.user))


@api_view(['POST'])
@permission_classes([ParticipantPermission])
@parser_classes([JSONParser])
def pickup_cancel(request, pickup_id):
    from .logistics_service import cancel_pickup
    from .logistics_payloads import pickup_payload
    return _private(pickup_payload(cancel_pickup(request.user, pickup_id, _input(ReasonInput, request)), request.user))


@api_view(['GET', 'POST'])
@permission_classes([ParticipantPermission])
@parser_classes([JSONParser])
def outbound(request):
    from .logistics_service import assign_outbound, outbound_for
    from .logistics_payloads import outbound_payload
    if request.method == 'POST':
        if not logistics_manager(request.user):
            raise PermissionDenied('Le responsable SAV affecte les transports.')
        data = _input(OutboundAssignmentInput, request)
        if not data.get('service_request'):
            raise serializers.ValidationError({'service_request': 'Choisissez un dossier prêt à être livré ou retourné.'})
        return _private(outbound_payload(assign_outbound(request.user, data), request.user))
    queryset = outbound_for(request.user)
    query = reference_query_value(request.query_params, 'q')
    if query:
        queryset = queryset.filter(Q(service_request__reference__icontains=query) |
            Q(service_request__client_reference__icontains=query) | Q(client__name__icontains=query) |
            Q(delivery_equipment__serial_number__icontains=query) | Q(handed_over_serial__icontains=query))
    return _private([outbound_payload(row, request.user) for row in queryset])


@api_view(['GET'])
@permission_classes([ParticipantPermission])
def outbound_detail(request, job_id):
    from .logistics_service import outbound_for
    from .logistics_payloads import outbound_payload
    return _private(outbound_payload(get_object_or_404(outbound_for(request.user), pk=job_id), request.user))


@api_view(['POST'])
@permission_classes([LogisticsManagerPermission])
@parser_classes([JSONParser])
def outbound_assign(request, job_id):
    from .logistics_service import assign_outbound
    from .logistics_payloads import outbound_payload
    return _private(outbound_payload(assign_outbound(request.user, _input(OutboundAssignmentInput, request), pk=job_id), request.user))


@api_view(['POST'])
@permission_classes([LogisticsOperatorPermission])
@parser_classes([JSONParser])
def outbound_handoff(request, job_id):
    from .logistics_service import handoff
    from .logistics_payloads import outbound_payload
    return _private(outbound_payload(handoff(request.user, job_id, _input(HandoffInput, request)), request.user))


@api_view(['POST'])
@permission_classes([LogisticsManagerPermission])
@parser_classes([JSONParser])
def outbound_cancel(request, job_id):
    from .logistics_service import cancel_outbound
    from .logistics_payloads import outbound_payload
    return _private(outbound_payload(cancel_outbound(request.user, job_id, _input(ReasonInput, request)), request.user))


@api_view(['GET'])
@permission_classes([LogisticsManagerPermission])
def dispatch_candidates(request):
    from .logistics_payloads import dispatch_candidates as candidates
    return _private(candidates(request.user, q=reference_query_value(request.query_params, 'q')))


@api_view(['POST'])
@permission_classes([LogisticsManagerPermission])
@parser_classes([JSONParser])
def reconcile(request):
    from .logistics_service import reconcile_dispatch
    data = _input(ReconcileInput, request)
    return _private(reconcile_dispatch(request.user, client_id=data.get('client'),
                                       reassign_automatic=data['reassign_automatic']))
