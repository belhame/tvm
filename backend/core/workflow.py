from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .request_timing import request_timing


TERMINAL_STATUSES = ('resolved', 'rejected', 'closed')
CATEGORIES = (
    ('unassigned', 'Non affecté', ('new',)),
    ('maintenance', 'En entretien', ('maintenance', 'in_progress')),
    ('testing', 'En test', ('testing',)),
    ('overdue', 'En dépassement de délai', ()),
    ('processed', 'Traité', ('resolved',)),
    ('quotation', 'À facturer', ('quotation',)),
    ('quote_sent', 'Devis envoyé — attente de réponse', ('quote_sent',)),
    ('to_repair', 'À réparer', ('to_repair',)),
    ('pending', 'En attente', ('pending', 'scheduled')),
    ('approved', 'Validé', ('approved',)),
    ('rejected', 'Refusé', ('rejected',)),
    ('exchange', 'Échange', ('exchange',)),
    ('ready_for_delivery', 'Prêt à être livré', ('ready_for_delivery',)),
    ('return_to_client', 'À retourner au client', ('return_to_client',)),
    ('closed', 'Clôturé', ('closed',)),
    ('all', 'Tous', ()),
)


def due_overdue_filter():
    return Q(due_on__lt=timezone.localdate()) & ~Q(status__in=TERMINAL_STATUSES)


def overdue_filter(queryset=None, *, now=None):
    # The configured timezone and weekend rule live in one helper. With a few
    # thousand internal requests this avoids divergent SQL/calendar formulas.
    if queryset is None:
        from .models import ServiceRequest
        queryset = ServiceRequest.objects.all()
    now = now or timezone.now()
    overdue_ids = []
    rows = queryset.exclude(status='closed').filter(arrived_at__lt=now - timedelta(hours=48)).values('pk', 'arrived_at', 'closed_at', 'status')
    for row in rows.iterator():
        timing = request_timing(row['arrived_at'], row['closed_at'], row['status'], now=now)
        if timing['timer_state'] == 'running' and timing['is_overdue_48h']:
            overdue_ids.append(row['pk'])
    return Q(pk__in=overdue_ids)


def request_category(instance):
    for key, _, states in CATEGORIES:
        if instance.status in states:
            return key
    return 'unassigned'


def is_overdue(instance):
    timing = request_timing(instance.arrived_at, instance.closed_at, instance.status)
    return timing['timer_state'] == 'running' and timing['is_overdue_48h']


def is_due_overdue(instance):
    return bool(instance.due_on and instance.due_on < timezone.localdate() and instance.status not in TERMINAL_STATUSES)


def technician_can_write(user, service_request):
    from .request_assignment import technician_has_accepted_assignment
    return technician_has_accepted_assignment(user, service_request)
