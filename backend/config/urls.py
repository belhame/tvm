from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from core import views
from core import catalogue_views
from core import intake_views
from core.serial_lookup_views import serial_lookup_view
from core import attachment_views
from core.client_import_views import client_import
from core import exchange_views

router = DefaultRouter()
router.register('clients', views.ClientViewSet, basename='client')
router.register('equipment', views.EquipmentViewSet, basename='equipment')
router.register('requests', views.ServiceRequestViewSet, basename='request')
router.register('interventions', views.InterventionViewSet, basename='intervention')
router.register('users', views.UserViewSet, basename='user')
router.register('parts', views.PartViewSet, basename='part')
router.register('stock-movements', views.StockMovementViewSet, basename='stockmovement')
router.register('contracts', views.ContractViewSet, basename='contract')
router.register('warranties', views.WarrantyViewSet, basename='warranty')
router.register('delivery-notes', views.DeliveryNoteViewSet, basename='deliverynote')
router.register('audit', views.AuditViewSet, basename='audit')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/session/', views.session_view), path('api/login/', views.login_view), path('api/logout/', views.logout_view),
    path('api/health/', views.health_view), path('api/dashboard/', views.dashboard_view), path('api/search/', views.search_view), path('api/integrations/', views.integrations_view),
    path('api/serial-analysis/', views.serial_analysis_view),
    path('api/serial-lookup/', serial_lookup_view),
    path('api/catalogue/', catalogue_views.catalogue_status),
    path('api/catalogue/products/', catalogue_views.catalogue_products),
    path('api/catalogue/warranties/', catalogue_views.catalogue_warranties),
    path('api/catalogue/import/', catalogue_views.catalogue_import),
    path('api/clients/import/', client_import),
    path('api/requests/intake/', intake_views.request_intake),
    path('api/exchanges/', exchange_views.exchange_list),
    path('api/exchanges/billing/', exchange_views.exchange_list, {'billing': True}),
    path('api/requests/<int:request_id>/exchange/', exchange_views.exchange_detail),
    path('api/requests/<int:request_id>/exchange/validate/', exchange_views.exchange_action, {'operation': 'validate'}),
    path('api/requests/<int:request_id>/exchange/ready/', exchange_views.exchange_action, {'operation': 'ready'}),
    path('api/requests/<int:request_id>/exchange/billing/', exchange_views.exchange_action, {'operation': 'billing'}),
    path('api/requests/<int:request_id>/exchange/close/', exchange_views.exchange_action, {'operation': 'close'}),
    path('api/requests/<int:request_id>/exchange/reset/', exchange_views.exchange_action, {'operation': 'reset'}),
    path('api/requests/<int:request_id>/documents/', attachment_views.request_documents),
    path('api/documents/<int:document_id>/download/', attachment_views.document_download),
    path('api/documents/<int:document_id>/', attachment_views.document_delete),
    path('api/', include(router.urls)),
    re_path(r'^api(?:/.*)?$', views.api_not_found),
    re_path(r'^(?P<path>.*)$', views.spa_view),
]
