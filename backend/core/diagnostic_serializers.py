from rest_framework import serializers

from .exchange_views import StrictInput
from .workflow_api import StrictText


class StrictIdentifier(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail('invalid')
        return super().to_internal_value(data)


class DiagnosticSearchInput(StrictInput):
    model = StrictText(max_length=120, required=False, allow_blank=True)
    brand = StrictText(max_length=100, required=False, default='Eaton')
    symptoms = StrictText(max_length=6000, allow_blank=True)
    fault_code = StrictText(max_length=120, required=False, allow_blank=True, default='')
    measurements = StrictText(max_length=6000, required=False, allow_blank=True, default='')
    board_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    revision = StrictText(max_length=80, required=False, allow_blank=True, default='')
    service_request = StrictIdentifier(min_value=1, max_value=9223372036854775807, required=False)

    def validate(self, attrs):
        if not attrs.get('model') and not attrs.get('service_request'):
            raise serializers.ValidationError({'model': 'Choisissez le modèle exact ou un dossier autorisé.'})
        if not any(attrs.get(key, '').strip() for key in ('symptoms', 'fault_code', 'measurements')):
            raise serializers.ValidationError({'symptoms': 'Décrivez les symptômes, le code défaut ou les mesures.'})
        return attrs


class DiagnosticAnalyzeInput(DiagnosticSearchInput):
    request_key = serializers.UUIDField()
    def to_internal_value(self, data):
        if isinstance(data, dict) and not isinstance(data.get('request_key'), str):
            raise serializers.ValidationError({'request_key': 'Un UUID sous forme de texte est requis.'})
        return super().to_internal_value(data)
