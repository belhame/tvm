from django.urls import path
from . import diagnostic_views

urlpatterns = [
    path('status/', diagnostic_views.status_view),
    path('search/', diagnostic_views.search_view),
    path('analyze/', diagnostic_views.analyze_view),
    path('runs/', diagnostic_views.run_list),
    path('runs/<int:run_id>/', diagnostic_views.run_detail),
]
