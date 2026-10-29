"""Only issued quotes and real client decisions produce these SAV states."""
from contextlib import contextmanager

from rest_framework.exceptions import ValidationError


_TRANSITION_TOKEN = object()
DERIVED_QUOTE_STATUSES = frozenset(('quote_sent', 'to_repair'))


@contextmanager
def quote_status_transition(record):
    previous = getattr(record, '_quote_status_transition', None)
    record._quote_status_transition = _TRANSITION_TOKEN
    try:
        yield
    finally:
        record._quote_status_transition = previous


def guard_quote_status(record, update_fields, old_status):
    if update_fields is not None and 'status' not in update_fields:
        return
    if record.status == old_status or record.status not in DERIVED_QUOTE_STATUSES:
        return
    if getattr(record, '_quote_status_transition', None) is not _TRANSITION_TOKEN:
        raise ValidationError({'status': 'Cet état résulte de l’envoi du devis ou de l’acceptation du client. Utilisez les actions du devis.'})
