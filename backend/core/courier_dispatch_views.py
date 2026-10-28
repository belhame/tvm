from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser

from .courier_dispatch import MAX_OUTBOUND_REVISION, accept_outbound, claim_ready, ready_queue
from .exchange_views import StrictInput
from .logistics_permissions import LogisticsOperatorPermission
from .logistics_payloads import outbound_payload
from .logistics_views import _input, _private
from .request_numbering import reference_query_value
from .request_tracking import StrictRevision
from .workflow_api import StrictBoolean


class ClaimInput(StrictInput):
    expected_revision = StrictRevision(min_value=0, max_value=MAX_OUTBOUND_REVISION)


class AcceptInput(ClaimInput):
    accept = StrictBoolean()


@api_view(['GET'])
@permission_classes([LogisticsOperatorPermission])
def ready_board(request):
    return _private(ready_queue(request.user, q=reference_query_value(request.query_params, 'q')))


@api_view(['POST'])
@permission_classes([LogisticsOperatorPermission])
@parser_classes([JSONParser])
def claim(request, request_id):
    data = _input(ClaimInput, request)
    return _private(outbound_payload(claim_ready(request.user, request_id, data['expected_revision']), request.user))


@api_view(['POST'])
@permission_classes([LogisticsOperatorPermission])
@parser_classes([JSONParser])
def accept(request, job_id):
    data = _input(AcceptInput, request)
    return _private(outbound_payload(accept_outbound(request.user, job_id, data['expected_revision'], data['accept']), request.user))
