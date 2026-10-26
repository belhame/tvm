from django.urls import path

from . import notification_views

urlpatterns = [
    path('notifications/preferences/', notification_views.notification_preferences),
    path('notifications/', notification_views.notification_list),
    path('notifications/<int:notification_id>/read/', notification_views.notification_read),
]
