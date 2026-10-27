from django.urls import path

from . import logistics_views as views


urlpatterns = [
    path('bootstrap/', views.bootstrap),
    path('clients/', views.clients),
    path('lookup/', views.lookup),
    path('receive/', views.receive),
    path('pickups/', views.pickups),
    path('pickups/<int:pickup_id>/', views.pickup_detail),
    path('pickups/<int:pickup_id>/assign/', views.pickup_assign),
    path('pickups/<int:pickup_id>/collect/', views.pickup_collect),
    path('pickups/<int:pickup_id>/cancel/', views.pickup_cancel),
    path('outbound/', views.outbound),
    path('outbound/<int:job_id>/', views.outbound_detail),
    path('outbound/<int:job_id>/assign/', views.outbound_assign),
    path('outbound/<int:job_id>/handoff/', views.outbound_handoff),
    path('outbound/<int:job_id>/cancel/', views.outbound_cancel),
    path('dispatch-candidates/', views.dispatch_candidates),
    path('reconcile/', views.reconcile),
]
