"""Strict session/CSRF API for repair quotation revisions and client opinions."""
import hashlib

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exchange_views import StrictInput
from .models import AuditLog
from .repair_quote_service import create_draft, decide_quote, edit_draft, issue_quote, quote_payload, quotes_for, visible_quote
from .workflow_api import StrictText


class StrictInteger(serializers.IntegerField):
    def to_internal_value(self, value):
        if type(value) is not int:
            raise ValidationError('Un nombre entier JSON est requis.')
        return super().to_internal_value(value)


class DraftInput(StrictInput):
    request_key = serializers.UUIDField()
    service_request = StrictInteger(min_value=1, max_value=9_223_372_036_854_775_807)
    lines = serializers.JSONField()
    vat_rate = serializers.JSONField()
    currency = serializers.ChoiceField(choices=['TND', 'EUR', 'USD'], default='TND')
    discount_kind = serializers.ChoiceField(choices=['none', 'percent', 'fixed'], default='none')
    discount_value = serializers.JSONField(default='0')
    terms = StrictText(max_length=10000, allow_blank=True, required=False)
    valid_until = serializers.DateField(allow_null=True, required=False)


class EditInput(DraftInput):
    request_key = None
    service_request = None
    expected_revision = StrictInteger(min_value=0, max_value=9_223_372_036_854_775_806)
    lines = serializers.JSONField(required=False)
    vat_rate = serializers.JSONField(required=False)
    currency = serializers.ChoiceField(choices=['TND', 'EUR', 'USD'], required=False)
    discount_kind = serializers.ChoiceField(choices=['none', 'percent', 'fixed'], required=False)
    discount_value = serializers.JSONField(required=False)


class IssueInput(StrictInput):
    request_key = serializers.UUIDField()
    expected_revision = StrictInteger(min_value=0, max_value=9_223_372_036_854_775_806)


class DecisionInput(IssueInput):
    decision = serializers.ChoiceField(choices=['accepted', 'refused'])


def _response(quote, actor, *, status=200):
    result = Response(quote_payload(quote, actor), status=status)
    result['Cache-Control'] = 'private, no-store'
    return result


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def repair_quotes(request):
    if request.method == 'POST':
        serializer = DraftInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote, created = create_draft(request.user, **serializer.validated_data)
        return _response(quote, request.user, status=201 if created else 200)
    query = quotes_for(request.user)
    identifier = request.query_params.get('service_request')
    if identifier is not None:
        if not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 19 or not 0 < int(identifier) <= 9_223_372_036_854_775_807:
            raise ValidationError({'service_request': 'Identifiant SAV invalide.'})
        query = query.filter(book__service_request_id=int(identifier))
    result = Response([quote_payload(quote, request.user) for quote in query])
    result['Cache-Control'] = 'private, no-store'
    return result


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def repair_quote_detail(request, quote_id):
    quote = visible_quote(request.user, quote_id)
    if request.method == 'PATCH':
        serializer = EditInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = edit_draft(request.user, quote_id, **serializer.validated_data)
    return _response(quote, request.user)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def repair_quote_issue(request, quote_id):
    visible_quote(request.user, quote_id)
    serializer = IssueInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    quote, created = issue_quote(request.user, quote_id, **serializer.validated_data)
    return _response(quote, request.user, status=201 if created else 200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def repair_quote_decision(request, quote_id):
    visible_quote(request.user, quote_id)
    serializer = DecisionInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    quote, _ = decide_quote(request.user, quote_id, **serializer.validated_data)
    return _response(quote, request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def repair_quote_download(request, quote_id):
    quote = visible_quote(request.user, quote_id)
    if quote.state != 'issued':
        raise NotFound('Ce brouillon ne possède pas encore de PDF émis.')
    data = bytes(quote.pdf_data)
    if not data or hashlib.sha256(data).hexdigest() != quote.pdf_sha256:
        raise ValidationError('L’intégrité de ce document doit être vérifiée par l’administrateur.')
    result = HttpResponse(data, content_type='application/pdf')
    result['Content-Disposition'] = f'attachment; filename="Devis-reparation-{quote.pk}-R{quote.version}.pdf"'
    result['Cache-Control'] = 'private, no-store'
    result['X-Content-Type-Options'] = 'nosniff'
    AuditLog.objects.create(actor=request.user, action='download_repair_quote', resource='repairquote', resource_id=str(quote.pk))
    return result
