from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .permissions import InternalPermission
from .serial_lookup import lookup_serial


@api_view(['POST'])
@permission_classes([InternalPermission])
def serial_lookup_view(request):
    if not isinstance(request.data, dict):
        raise ValidationError({'serial_number': 'Un objet JSON contenant serial_number est requis.'})
    body = request.data
    reference_id = body.get('warranty_reference_id', body.get('warranty_id'))
    if 'warranty_id' in body and 'warranty_reference_id' in body and body['warranty_id'] != body['warranty_reference_id']:
        raise ValidationError({'warranty_reference_id': 'Les deux identifiants de garantie ne correspondent pas.'})
    return Response(lookup_serial(
        body.get('serial_number'), profile=body.get('profile'), product_id=body.get('product_id'),
        catalogue_import_id=body.get('catalogue_import_id'), warranty_reference_id=reference_id,
    ))
