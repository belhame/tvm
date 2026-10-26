from django.db.models import Q
from django.utils import timezone


TERMINAL_STATUSES = ('resolved', 'rejected', 'closed')
CATEGORIES = (
    ('unassigned', 'Non affecté', ('new',)),
    ('maintenance', 'En entretien', ('maintenance', 'in_progress')),
    ('testing', 'En test', ('testing',)),
    ('overdue', 'En dépassement de délai', ()),
    ('processed', 'Traité', ('resolved',)),
    ('quotation', 'Devis', ('quotation',)),
    ('pending', 'En attente', ('pending', 'scheduled')),
    ('approved', 'Validé', ('approved',)),
    ('rejected', 'Refusé', ('rejected',)),
    ('exchange', 'Échange', ('exchange',)),
    ('closed', 'Clôturé', ('closed',)),
    ('all', 'Tous', ()),
)


def overdue_filter():
    return Q(due_on__lt=timezone.localdate()) & ~Q(status__in=TERMINAL_STATUSES)


def request_category(instance):
    for key, _, states in CATEGORIES:
        if instance.status in states:
            return key
    return 'unassigned'


def is_overdue(instance):
    return bool(instance.due_on and instance.due_on < timezone.localdate() and instance.status not in TERMINAL_STATUSES)


def technician_can_write(user, service_request):
    return service_request.assigned_technician_id == user.pk or service_request.interventions.filter(technician_id=user.pk).exists()
