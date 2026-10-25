from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .intake_service import create_intake
from .permissions import InternalPermission
from .serializers import EquipmentSerializer, ServiceRequestSerializer, WarrantySerializer


@api_view(['POST'])
@permission_classes([InternalPermission])
def request_intake(request):
    result = create_intake(request.data, actor=request.user)
    context = {'request': request}
    response = Response({
        'created': result.created,
        'request': ServiceRequestSerializer(result.request, context=context).data,
        'equipment': EquipmentSerializer(result.equipment, context=context).data,
        'created_equipment': result.created_equipment,
        'warranty': WarrantySerializer(result.warranty, context=context).data if result.warranty else None,
        'intake': result.intake,
    }, status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)
    response['Cache-Control'] = 'private, no-store'
    return response
