from rest_framework.permissions import BasePermission, SAFE_METHODS


def can_validate_billing(user):
    """Billing validation is an explicit internal permission, implicit for admins."""
    if not user or not user.is_authenticated or not user.is_active or user.role == 'client':
        return False
    return user.effective_role == 'admin' or bool(user.can_validate_billing)


class BusinessPermission(BasePermission):
    message = 'Votre rôle ne permet pas cette opération.'
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        role = request.user.effective_role
        if request.method in SAFE_METHODS:
            return True
        if role in ('admin', 'manager'):
            return True
        if role == 'technician':
            if getattr(view, 'action', None) == 'use_part':
                return True
            if getattr(view, 'basename', None) == 'request' and request.method == 'POST':
                return True
            if getattr(view, 'basename', None) == 'intervention' and request.method in ('POST', 'PATCH', 'PUT'):
                return True
        return False
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or request.user.effective_role in ('admin', 'manager'):
            return True
        if request.user.effective_role == 'technician':
            return getattr(obj, 'technician_id', None) == request.user.pk
        return False


class InternalPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.effective_role != 'client'


class ManagerPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.effective_role in ('admin', 'manager')


class AdminAccountsPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated or request.user.effective_role == 'client':
            return False
        return request.method in SAFE_METHODS or request.user.effective_role == 'admin'
