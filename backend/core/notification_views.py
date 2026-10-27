"""Own-account notifications; reads never create preferences or reminders."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exchange_views import StrictInput
from .notification_models import DailyReminderPreferences, InAppNotification
from .workflow_api import StrictBoolean, StrictText


class PreferencesInput(StrictInput):
    enabled = StrictBoolean(required=False)
    timezone = StrictText(max_length=64, required=False)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError('Choisissez un fuseau IANA valide, par exemple Africa/Tunis.')
        return value


class ReadInput(StrictInput):
    read = StrictBoolean()

    def validate_read(self, value):
        if value is not True:
            raise serializers.ValidationError('Confirmez la lecture avec read: true.')
        return value


def _active(user):
    if not user.is_active:
        raise PermissionDenied('Ce compte est désactivé.')


def _private(data):
    response = Response(data)
    response['Cache-Control'] = 'private, no-store'
    return response


def _inbox(user):
    queryset = InAppNotification.objects.filter(recipient=user)
    if user.effective_role == 'client':
        queryset = queryset.exclude(kind=InAppNotification.Kind.DAILY).filter(
            Q(service_request__equipment__client_id=user.client_id) |
            Q(kind=InAppNotification.Kind.LOGISTICS, client_id=user.client_id))
    return queryset.select_related('service_request__equipment__client')


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def notification_preferences(request):
    from .notification_service import preferences_payload
    _active(request.user)
    if request.user.effective_role not in ('admin', 'courier'):
        raise PermissionDenied('Ces préférences sont réservées au compte livreur ou administrateur connecté.')
    if request.method == 'PATCH':
        serializer = PreferencesInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        preferences, _ = DailyReminderPreferences.objects.get_or_create(user=request.user)
        for key, value in serializer.validated_data.items():
            setattr(preferences, key, value)
        preferences.save()
    return _private(preferences_payload(request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    from .notification_service import notification_payload
    _active(request.user)
    queryset = _inbox(request.user)
    # The inbox is bounded; unread_count includes older notices as well.
    return _private({'results': [notification_payload(item, request.user) for item in queryset[:100]],
                     'unread_count': queryset.filter(read_at__isnull=True).count(), 'as_of': timezone.now()})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def notification_read(request, notification_id):
    from .notification_service import notification_payload
    _active(request.user)
    item = get_object_or_404(_inbox(request.user), pk=notification_id)
    serializer = ReadInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    InAppNotification.objects.filter(pk=item.pk, read_at__isnull=True).update(read_at=timezone.now())
    item.refresh_from_db()
    return _private(notification_payload(item, request.user))
