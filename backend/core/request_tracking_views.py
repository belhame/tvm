from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import InternalPermission
from .request_tracking import write_followup
from .serializers import ServiceRequestSerializer
from .workflow_api import OperationEventSerializer


@api_view(['POST'])
@permission_classes([InternalPermission])
def followup_view(request, request_id):
    result = write_followup(request_id, request.data, actor=request.user)
    response = Response({
        'request': ServiceRequestSerializer(result.service_request, context={'request': request}).data,
        'events': OperationEventSerializer(result.events, many=True, context={'request': request}).data,
    }, status=201)
    response['Cache-Control'] = 'private, no-store'
    return response
