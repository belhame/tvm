from rest_framework import serializers

from .knowledge_models import TechnicalDocument


class StrictText(serializers.CharField):
    def to_internal_value(self, value):
        if not isinstance(value, str) or '\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            self.fail('invalid')
        return super().to_internal_value(value)


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({'detail': 'Le formulaire contient un champ non pris en charge.'})
        return super().to_internal_value(data)


class DocumentInput(StrictInput):
    title = StrictText(max_length=200)
    brand = StrictText(max_length=100)
    model = StrictText(max_length=120)
    board_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    revision = StrictText(max_length=80, required=False, allow_blank=True, default='')
    kind = serializers.ChoiceField(choices=TechnicalDocument.Kind.choices)


class CaseInput(StrictInput):
    intervention = serializers.IntegerField(min_value=1, max_value=9_223_372_036_854_775_807)
    board_reference = StrictText(max_length=120, required=False, allow_blank=True, default='')
    revision = StrictText(max_length=80, required=False, allow_blank=True, default='')
    symptoms = StrictText(max_length=6000)
    fault_code = StrictText(max_length=120, required=False, allow_blank=True, default='')
    measurements = StrictText(max_length=6000, required=False, allow_blank=True, default='')
    confirmed_cause = StrictText(max_length=6000)
    repair = StrictText(max_length=6000)
    outcome = StrictText(max_length=4000)

    def validate_intervention(self, value):
        original = self.initial_data.get('intervention')
        if isinstance(original, bool) or isinstance(original, float):
            raise serializers.ValidationError('Un identifiant entier est requis.')
        return value
