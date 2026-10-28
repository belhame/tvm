from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .simple_intake import _allowed, create_intake, intake_options, lookup_intake
from .workflow_api import StrictText


class ReceptionPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and _allowed(request.user)


class StrictId(serializers.IntegerField):
    def to_internal_value(self, value):
        if type(value) is not int:
            self.fail('invalid')
        return super().to_internal_value(value)


class LookupInput(serializers.Serializer):
    client = StrictId(min_value=1, max_value=9223372036854775807)
    serial_number = StrictText(max_length=120)
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({'non_field_errors': ['Le formulaire contient un champ inconnu.']})
        return super().to_internal_value(data)


class CreateInput(LookupInput):
    request_key = serializers.UUIDField()
    arrival_courier = StrictId(min_value=1, max_value=9223372036854775807, required=False)
    client_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    description = StrictText(max_length=4000, required=False, allow_blank=True, default='')
    def validate_request_key(self, value):
        if not isinstance(self.initial_data.get('request_key'), str):
            raise serializers.ValidationError('Une clé UUID texte est requise.')
        return value


def _input(serializer, request):
    result = serializer(data=request.data)
    result.is_valid(raise_exception=True)
    return result.validated_data


def _private(data, *, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([ReceptionPermission])
def options(request):
    if request.query_params:
        raise ValidationError('Aucun filtre supplémentaire n’est attendu pour les choix de réception.')
    return _private(intake_options(request.user))


@api_view(['POST'])
@permission_classes([ReceptionPermission])
@parser_classes([JSONParser])
def lookup(request):
    return _private(lookup_intake(request.user, **_input(LookupInput, request)))


@api_view(['POST'])
@permission_classes([ReceptionPermission])
@parser_classes([JSONParser])
def create(request):
    result = create_intake(request.user, _input(CreateInput, request))
    return _private(result, status=201 if result['created'] else 200)
