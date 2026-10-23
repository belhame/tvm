from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from rest_framework.response import Response
from rest_framework.views import exception_handler

def api_exception_handler(exc, context):
    if isinstance(exc, ProtectedError):
        return Response({'detail': 'Suppression impossible : cet élément est utilisé dans un dossier. Désactivez-le ou archivez-le.'}, status=409)
    if isinstance(exc, IntegrityError):
        return Response({'detail': 'Conflit de données : doublon ou relation invalide. Rechargez les données et vérifiez les valeurs.'}, status=409)
    return exception_handler(exc, context)
