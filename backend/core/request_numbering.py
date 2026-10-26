"""Allocate the shared TVM call number; visit references remain independent."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError


@transaction.atomic
def next_request_number():
    from .models import RequestNumberSequence, ServiceRequest

    year = timezone.localdate().year
    prefix = f'{year % 100:02d}-'
    RequestNumberSequence.objects.get_or_create(year=year)
    sequence = RequestNumberSequence.objects.select_for_update().get(year=year)
    # Existing imported numbers remain authoritative. The fixed-width pattern
    # excludes unrelated historic formats and allows a safe lexical maximum.
    highest = (ServiceRequest.objects.filter(reference__regex=rf'^{prefix}[0-9]{{5}}$')
               .order_by('-reference').values_list('reference', flat=True).first())
    maximum = max(sequence.last_value, int(highest[-5:]) if highest else 0)
    if maximum >= 99999:
        raise ValidationError({'reference': 'Les 99 999 numéros annuels sont attribués. Contactez l’administrateur avant de créer un nouveau dossier.'})
    sequence.last_value = maximum + 1
    sequence.save(update_fields=['last_value'])
    return f'{prefix}{sequence.last_value:05d}'


def reference_query_value(params, key):
    value = params.get(key, '')
    if len(value) > 200 or '\x00' in value or '\ufffd' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValidationError({key: 'Recherchez un texte valide de 200 caractères au maximum.'})
    return value.strip()
