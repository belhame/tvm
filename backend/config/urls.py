from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from core import views
from core import catalogue_views

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
    path('api/catalogue/', catalogue_views.catalogue_status),
    path('api/catalogue/products/', catalogue_views.catalogue_products),
    path('api/catalogue/warranties/', catalogue_views.catalogue_warranties),
    path('api/catalogue/import/', catalogue_views.catalogue_import),
    path('api/', include(router.urls)),
    re_path(r'^api(?:/.*)?$', views.api_not_found),
    re_path(r'^(?P<path>.*)$', views.spa_view),
]
