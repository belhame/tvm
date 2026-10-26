"""Shared delivery/return queues and explicit diagnostic document actions."""
from decimal import Decimal
import re

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .diagnostic_quote import diagnostic_quote_pdf, quote_amounts
from .disposition_models import DiagnosticQuote
from .disposition_workflow import (approve_free_diagnostic, close_disposition, confirm_diagnostic_invoice, disposition_related,
    edit_quote_draft, get_disposition, issue_quote, mark_nonrepairable, mark_repaired, reset_disposition)
from .exchange_views import BillingInput, ResetInput, StrictInput
from .exchange_workflow import exchange_related, workflow_permission_hints
from .models import AuditLog, ServiceRequest
from .permissions import can_validate_billing
from .preventive_visits import with_preventive_counts
from .request_numbering import reference_query_value
from .serializers import ServiceRequestSerializer
from .workflow_api import StrictBoolean, StrictText


class RepairInput(StrictInput):
    diagnosis = StrictText(max_length=10000)
    tests_passed = StrictBoolean()
    tested_on = serializers.DateField()
    def validate_tests_passed(self, value):
        if value is not True:
            raise ValidationError('Confirmez que les tests de réparation sont réussis.')
        return value
    def validate_tested_on(self, value):
        if value > timezone.localdate():
            raise ValidationError('La date réelle des tests ne peut pas être future.')
        return value


class NonrepairableInput(StrictInput):
    diagnosis = StrictText(max_length=10000)
    fee_mode = serializers.ChoiceField(choices=['billable', 'free'], required=False)
    free_reason = StrictText(max_length=4000, allow_blank=True, required=False)


class QuoteDraftInput(StrictInput):
    diagnosis = StrictText(max_length=10000, required=False)
    fee_mode = serializers.ChoiceField(choices=['billable', 'free'], required=False)
    free_reason = StrictText(max_length=4000, allow_blank=True, required=False)
    price_ht = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'), required=False, allow_null=True)
    vat_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False, allow_null=True)
    currency = serializers.ChoiceField(choices=['TND', 'EUR', 'USD'], required=False)
    quote_notes = StrictText(max_length=4000, allow_blank=True, required=False)
    def to_internal_value(self, data):
        if isinstance(data, dict):
            for field in ('price_ht', 'vat_rate'):
                value = data.get(field)
                if value is None:
                    continue
                if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
                    raise ValidationError({field: 'Utilisez un nombre décimal explicite sous forme de texte.'})
                if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', str(value).strip()):
                    raise ValidationError({field: 'Utilisez un nombre décimal sans exposant ni séparateur de milliers.'})
        return super().to_internal_value(data)
    def validate(self, attrs):
        process = self.context.get('process')
        currency = attrs.get('currency', process.currency if process else 'TND')
        price = attrs.get('price_ht', process.price_ht if process else None)
        rate = attrs.get('vat_rate', process.vat_rate if process else None)
        if price is not None:
            # This validates precision only. Missing VAT remains unknown in the
            # draft and is still mandatory before a quote may be issued.
            quote_amounts(price, rate if rate is not None else Decimal('0'), currency)
        return attrs


def _queryset(user):
    queryset = disposition_related(exchange_related(with_preventive_counts(ServiceRequest.objects.select_related('equipment__client', 'assigned_technician'))))
    scoped = queryset.filter(equipment__client_id=user.client_id) if user.effective_role == 'client' else queryset
    return workflow_permission_hints(scoped, user)


def _record(identifier, user):
    return get_object_or_404(_queryset(user), pk=identifier)


def _response(record, request):
    response = Response(ServiceRequestSerializer(_record(record.pk, request.user), context={'request': request}).data)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dispatch_list(request, queue):
    if queue == 'billing' and not can_validate_billing(request.user):
        raise PermissionDenied('Cette liste est réservée à la validation financière des diagnostics.')
    queryset = _queryset(request.user)
    if queue == 'ready':
        queryset = queryset.filter(status='ready_for_delivery')
    elif queue == 'returns':
        queryset = queryset.filter(Q(status='return_to_client') | Q(disposition_process__outcome='nonrepairable')).exclude(status='closed')
    else:
        queryset = queryset.filter(Q(disposition_process__requires_diagnostic_billing=True) | Q(status='return_to_client'))
        if request.query_params.get('include_closed') != '1':
            queryset = queryset.exclude(status='closed')
    query = reference_query_value(request.query_params, 'q')
    if query:
        replacement = Q(exchange_process__replacement_serial_number__icontains=query)
        if request.user.effective_role == 'client':
            replacement &= Q(exchange_process__validated_at__isnull=False)
        queryset = queryset.filter(Q(reference__icontains=query) | Q(client_reference__icontains=query) | Q(subject__icontains=query) |
            Q(equipment__serial_number__icontains=query) | Q(equipment__client__name__icontains=query) | replacement)
    response = Response(ServiceRequestSerializer(queryset, many=True, context={'request': request}).data)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def disposition_detail(request, request_id):
    record = _record(request_id, request.user)
    if request.method == 'PATCH':
        if request.user.effective_role == 'client':
            raise PermissionDenied('Le portail client permet uniquement la consultation.')
        serializer = QuoteDraftInput(data=request.data, context={'process': get_disposition(record)})
        serializer.is_valid(raise_exception=True)
        record = edit_quote_draft(record.pk, serializer.validated_data, actor=request.user)
    return _response(record, request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disposition_action(request, request_id, operation):
    record = _record(request_id, request.user)
    if request.user.effective_role == 'client':
        raise PermissionDenied('Le portail client permet uniquement la consultation.')
    input_class = {'repair': RepairInput, 'nonrepairable': NonrepairableInput, 'invoice': BillingInput, 'free': ResetInput, 'reset': ResetInput}.get(operation, StrictInput)
    serializer = input_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if operation == 'repair':
        record = mark_repaired(record.pk, data, actor=request.user)
    elif operation == 'nonrepairable':
        record = mark_nonrepairable(record.pk, data, actor=request.user)
    elif operation == 'invoice':
        record = confirm_diagnostic_invoice(record.pk, data, actor=request.user)
    elif operation == 'free':
        record = approve_free_diagnostic(record.pk, actor=request.user, reason=data['reason'])
    elif operation == 'reset':
        record = reset_disposition(record.pk, actor=request.user, reason=data['reason'])
    elif operation == 'quote_issue':
        record = issue_quote(record.pk, actor=request.user)
    elif operation == 'close':
        record = close_disposition(record.pk, actor=request.user)
    else:
        raise ValidationError('Action de qualification inconnue.')
    return _response(record, request)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def diagnostic_quote_download(request, quote_id):
    quotes = DiagnosticQuote.objects.select_related('process__service_request__equipment')
    if request.user.effective_role == 'client':
        quotes = quotes.filter(process__service_request__equipment__client_id=request.user.client_id)
    quote = get_object_or_404(quotes, pk=quote_id)
    if request.user.effective_role == 'client' and quote.snapshot['client']['id'] != request.user.client_id:
        # Scope frozen and current ownership: even a direct database transfer
        # cannot expose a previous client's issued diagnostic document.
        from django.http import Http404
        raise Http404()
    response = HttpResponse(diagnostic_quote_pdf(quote.snapshot), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Devis-diagnostic-{quote.number}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    AuditLog.objects.create(actor=request.user, action='download_quote', resource='diagnosticquote', resource_id=str(quote.pk))
    return response
