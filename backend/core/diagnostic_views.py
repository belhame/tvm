from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .diagnostic_models import DiagnosticRun
from .diagnostic_serializers import DiagnosticAnalyzeInput, DiagnosticSearchInput
from .diagnostic_service import analyze, diagnostic_status, run_payload, search


class DiagnosticPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and user.effective_role in ('admin', 'manager', 'technician'))


def _private(data):
    response = Response(data)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([DiagnosticPermission])
def status_view(request):
    return _private(diagnostic_status())


@api_view(['POST'])
@permission_classes([DiagnosticPermission])
def search_view(request):
    serializer = DiagnosticSearchInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _private(search(serializer.validated_data))


@api_view(['POST'])
@permission_classes([DiagnosticPermission])
def analyze_view(request):
    serializer = DiagnosticAnalyzeInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _private(run_payload(analyze(request.user, serializer.validated_data)))


def _history(user):
    records = DiagnosticRun.objects.select_related('actor', 'service_request__equipment__client')
    return records.filter(actor=user) if user.effective_role == 'technician' else records


@api_view(['GET'])
@permission_classes([DiagnosticPermission])
def run_list(request):
    return _private({'results': [run_payload(run) for run in _history(request.user)[:50]], 'as_of': timezone.now()})


@api_view(['GET'])
@permission_classes([DiagnosticPermission])
def run_detail(request, run_id):
    return _private(run_payload(get_object_or_404(_history(request.user), pk=run_id)))
