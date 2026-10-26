from django.utils import timezone
from rest_framework import serializers


FOLLOWUP_TEXT_FIELDS = {
    'client_reference': 120, 'end_customer': 200, 'packaging': 250, 'courier_name': 150,
    'accessories': 4000, 'contact_name': 150, 'contact_phone': 40, 'contact_email': 254,
}
FOLLOWUP_FIELD_NAMES = ['arrived_at', 'client_reference', 'end_customer', 'return_flag', 'packaging',
                        'service_location', 'delivered_by', 'courier_name', 'accessories', 'warranty_status',
                        'contact_name', 'contact_phone', 'contact_email']


def validate_followup(attrs, *, instance=None, user=None, initial_data=None):
    initial_data = initial_data or {}
    for field in FOLLOWUP_TEXT_FIELDS:
        if field in initial_data and (not isinstance(initial_data[field], str) or '\x00' in initial_data[field] or any(0xD800 <= ord(c) <= 0xDFFF for c in initial_data[field])):
            raise serializers.ValidationError({field: 'Un texte valide est requis.'})
    for field in ('return_flag',):
        if field in initial_data and type(initial_data[field]) is not bool:
            raise serializers.ValidationError({field: 'Un vrai booléen JSON est requis.'})
    now = timezone.now()
    arrived = attrs.get('arrived_at', getattr(instance, 'arrived_at', None))
    state = attrs.get('status', getattr(instance, 'status', 'new'))
    existing_closed = getattr(instance, 'closed_at', None)
    if arrived and arrived > now:
        raise serializers.ValidationError({'arrived_at': 'La date d’arrivée ne peut pas être future.'})
    if 'closed_at' in initial_data:
        allowed = (instance is not None and instance.status == 'closed' and existing_closed is None
                   and state == 'closed' and user is not None and user.effective_role in ('admin', 'manager'))
        if not allowed or attrs.get('closed_at') is None:
            raise serializers.ValidationError({'closed_at': 'La clôture est datée automatiquement et reste figée. Seule une date historique manquante peut être complétée par le responsable.'})
        if attrs['closed_at'] > now:
            raise serializers.ValidationError({'closed_at': 'La date réelle de clôture ne peut pas être future.'})
    closed = attrs.get('closed_at', existing_closed) if state == 'closed' else None
    if arrived and closed and arrived > closed:
        raise serializers.ValidationError({'arrived_at': 'L’arrivée doit précéder ou correspondre à la clôture réelle.'})
    return attrs
