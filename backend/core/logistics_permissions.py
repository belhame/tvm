"""The courier is an operational role, not a generic internal reader."""
import re

from django.http import JsonResponse
from rest_framework.permissions import BasePermission


def logistics_operator(user):
    return bool(user and user.is_authenticated and user.is_active and user.effective_role in ('admin', 'manager', 'courier'))


def logistics_manager(user):
    return bool(user and user.is_authenticated and user.is_active and user.role != 'courier' and user.effective_role in ('admin', 'manager'))


class LogisticsOperatorPermission(BasePermission):
    def has_permission(self, request, view):
        return logistics_operator(request.user)


class CourierAPIAccessMiddleware:
    """Fail closed on all other APIs, including views with IsAuthenticated.

    The force-auth attribute is Django REST Framework's in-process test helper,
    never an HTTP header or a user-controlled value in a real request.
    """
    allowed = re.compile(r'^/api/(?:session|login|logout|health)/$|^/api/logistics/(?:bootstrap|clients|lookup|receive|recognize-serial|pickups|outbound|dispatch-candidates)/$|^/api/logistics/pickups/[0-9]+/(?:assign/|collect/|cancel/)?$|^/api/logistics/outbound/[0-9]+/(?:assign/|handoff/|cancel/)?$|^/api/logistics/notifications/(?:preferences/|[0-9]+/read/)?$')
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        actor = getattr(request, '_force_auth_user', None) or request.user
        if getattr(actor, 'is_authenticated', False) and getattr(actor, 'role', None) == 'courier':
            path = request.path_info
            if path == '/admin' or path.startswith('/admin/') or ((path == '/api' or path.startswith('/api/')) and not self.allowed.fullmatch(path)):
                return JsonResponse({'detail': 'Le compte livreur utilise uniquement son espace logistique.'}, status=403)
        return self.get_response(request)
