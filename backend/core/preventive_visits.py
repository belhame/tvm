"""Preventive campaign targets and actual visits, always scoped to one dossier.

A target is a plan, never evidence that a visit took place. Counts derive from
recorded interventions; maintenance, commissioning and cancelled visits do not
increase preventive progress. Old requests retain an unknown target.
"""
from django.db.models import Count, Q


def with_preventive_counts(queryset, path='interventions'):
    return queryset.annotate(
        _preventive_completed_visit_count=Count(path, filter=Q(**{f'{path}__kind': 'preventive', f'{path}__status': 'completed'}), distinct=True),
        _preventive_total_visit_count=Count(path, filter=Q(**{f'{path}__kind': 'preventive'}) & ~Q(**{f'{path}__status': 'cancelled'}), distinct=True),
    )


def preventive_visit_progress(service_request, *, counts_source=None):
    source = counts_source if counts_source is not None else service_request
    if hasattr(source, '_preventive_completed_visit_count') and hasattr(source, '_preventive_total_visit_count'):
        completed = source._preventive_completed_visit_count
        total = source._preventive_total_visit_count
    else:
        counts = service_request.interventions.filter(kind='preventive').aggregate(
            completed=Count('pk', filter=Q(status='completed')),
            total=Count('pk', filter=~Q(status='cancelled')),
        )
        completed, total = counts['completed'], counts['total']
    target = service_request.planned_visit_count
    return {
        'planned_visit_count': target,
        'preventive_completed_visit_count': completed,
        'preventive_total_visit_count': total,
        'preventive_remaining_visit_count': None if target is None else max(target - completed, 0),
    }
