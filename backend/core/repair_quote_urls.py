from django.urls import path

from . import repair_quote_views as views

urlpatterns = [
    path('', views.repair_quotes),
    path('<int:quote_id>/', views.repair_quote_detail),
    path('<int:quote_id>/issue/', views.repair_quote_issue),
    path('<int:quote_id>/decision/', views.repair_quote_decision),
    path('<int:quote_id>/pdf/', views.repair_quote_download),
]
