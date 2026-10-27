"""Manager journal and explicit previews. Never receive provider credentials."""
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exchange_views import StrictInput
from .models import AuditLog, Client
from .outbox_models import ExternalNotification
from .outbox_service import channel_status, outbox_payload, preview, retry_notification
from .workflow_api import StrictBoolean, StrictText


def _manager(user):
    if not user.is_active or user.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('Le journal des notifications est réservé aux responsables SAV.')


def _private(data):
    response = Response(data)
    response['Cache-Control'] = 'private, no-store'
    return response


def _client_id(value):
    try:
        identifier = int(value)
        if identifier < 1 or identifier > 9223372036854775807:
            raise ValueError()
        return identifier
    except (ValueError, TypeError):
        raise serializers.ValidationError({'client': 'Identifiant client invalide.'}) from None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def outbox_list(request):
    _manager(request.user)
    records = ExternalNotification.objects.select_related('client')
    if request.query_params.get('client'):
        records = records.filter(client_id=_client_id(request.query_params['client']))
    for field, allowed in (('channel', ExternalNotification.Channel.values), ('state', ExternalNotification.State.values)):
        if request.query_params.get(field) and request.query_params[field] not in allowed:
            raise serializers.ValidationError({field: 'Filtre inconnu.'})
    if request.query_params.get('channel'):
        records = records.filter(channel=request.query_params['channel'])
    counts = {state: 0 for state in ExternalNotification.State.values}
    counts.update({row['state']: row['count'] for row in records.order_by().values('state').annotate(count=Count('id'))})
    if request.query_params.get('state'):
        records = records.filter(state=request.query_params['state'])
    return _private({'results': [outbox_payload(item) for item in records[:200]], 'counts': counts, 'as_of': timezone.now()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def outbox_preview(request, notification_id):
    _manager(request.user)
    item = get_object_or_404(ExternalNotification.objects.select_related('client'), pk=notification_id)
    return _private(preview(item, request.user))


class RetryInput(StrictInput):
    preview_token = StrictText(max_length=2000)
    confirm_uncertain = StrictBoolean(required=False, default=False)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def outbox_retry(request, notification_id):
    _manager(request.user)
    get_object_or_404(ExternalNotification, pk=notification_id)
    serializer = RetryInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = retry_notification(notification_id, request.user, serializer.validated_data['preview_token'],
        confirm_uncertain=serializer.validated_data['confirm_uncertain'])
    AuditLog.objects.create(actor=request.user, action='outbox_retry', resource='externalnotification', resource_id=str(item.pk))
    return _private(outbox_payload(item))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def channels(request):
    user = request.user
    if not user.is_active or user.role == 'courier':
        raise PermissionDenied('Le compte livreur utilise ses notifications propres.')
    client = None
    if user.effective_role == 'client':
        if request.query_params.get('client') and _client_id(request.query_params['client']) != user.client_id:
            raise PermissionDenied('Consultez uniquement les canaux de votre société.')
        client = get_object_or_404(Client, pk=user.client_id)
    elif request.query_params.get('client'):
        _manager(user)
        client = get_object_or_404(Client, pk=_client_id(request.query_params['client']))
    return _private({'email': channel_status('email'), 'whatsapp': channel_status('whatsapp'),
        'client_preferences': {'notify_email': client.notify_email, 'notify_whatsapp': client.notify_whatsapp} if client else None})
