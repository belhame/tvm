from django.urls import path
from . import knowledge_views as views

urlpatterns = [
    path('documents/', views.knowledge_documents),
    path('documents/<int:document_id>/', views.knowledge_document_detail),
    path('documents/<int:document_id>/download/', views.knowledge_document_download),
    path('documents/<int:document_id>/approve/', views.knowledge_document_approve),
    path('documents/<int:document_id>/archive/', views.knowledge_document_archive),
    path('cases/', views.knowledge_cases),
    path('cases/<int:case_id>/', views.knowledge_case_detail),
    path('cases/<int:case_id>/approve/', views.knowledge_case_approve),
    path('cases/<int:case_id>/archive/', views.knowledge_case_archive),
]
