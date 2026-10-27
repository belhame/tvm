from django.urls import path
from . import outbox_views

urlpatterns = [
    path('outbox/', outbox_views.outbox_list),
    path('outbox/<int:notification_id>/preview/', outbox_views.outbox_preview),
    path('outbox/<int:notification_id>/retry/', outbox_views.outbox_retry),
    path('channels/', outbox_views.channels),
]
