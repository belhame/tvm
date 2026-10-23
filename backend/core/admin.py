from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, Client, Contract, DeliveryNote, Equipment, Intervention, Part, ServiceRequest, User, Warranty


@admin.register(User)
class PowerCareUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('PowerCare', {'fields': ('role', 'client', 'legacy_id')}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('PowerCare', {'fields': ('role', 'client')}),)
    list_display = ('username', 'email', 'role', 'client', 'is_active')


# L'administration avancée est réservée aux superutilisateurs. Le stock ne s'y
# modifie pas : toute quantité passe par le registre atomique de l'API métier.
for model in (Client, Equipment, ServiceRequest, Intervention, Contract, Warranty, DeliveryNote):
    admin.site.register(model)


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    readonly_fields = ('stock_quantity',)


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'resource', 'resource_id')
    readonly_fields = ('actor', 'action', 'resource', 'resource_id', 'created_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

admin.site.site_header = 'PowerCare — Administration TVM'
admin.site.site_title = 'PowerCare'
