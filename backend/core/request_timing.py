"""Elapsed weekday duration: Saturdays and Sundays do not advance the clock."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


THRESHOLD_HOURS = 48


def business_seconds(start, end, timezone_name):
    """Count real elapsed seconds in local Monday–Friday date intervals.

    Blocks stop at local Saturday midnight, so timezone and DST transitions
    affect actual elapsed hours without treating office hours or holidays.
    """
    zone = ZoneInfo(timezone_name)
    cursor = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    seconds = 0.0
    while cursor < end:
        local = cursor.astimezone(zone)
        weekday = local.weekday()
        if weekday >= 5:
            monday = local.date() + timedelta(days=7 - weekday)
            cursor = datetime.combine(monday, time.min, zone).astimezone(timezone.utc)
        else:
            saturday = local.date() + timedelta(days=5 - weekday)
            boundary = datetime.combine(saturday, time.min, zone).astimezone(timezone.utc)
            endpoint = min(end, boundary)
            seconds += (endpoint - cursor).total_seconds()
            cursor = endpoint
    return seconds


def request_timing(arrived_at, closed_at, status, *, now=None, timezone_name=None):
    if timezone_name is None:
        from django.conf import settings
        timezone_name = settings.TIME_ZONE
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('La date de calcul doit préciser un fuseau horaire.')
    now = now.astimezone(timezone.utc)
    result = {
        'timer_state': 'unknown', 'elapsed_hours': None, 'elapsed_days': None,
        'is_overdue_48h': False, 'threshold_hours': THRESHOLD_HOURS,
        'clock_basis': 'business_hours_excluding_weekends', 'timezone': timezone_name,
        'as_of': now.isoformat(), 'warning': None,
    }
    if arrived_at is None:
        result['warning'] = 'Date d’arrivée non renseignée ; la date de création du dossier ne la remplace pas.'
        return result
    if arrived_at.tzinfo is None or arrived_at.utcoffset() is None:
        result['warning'] = 'Le fuseau horaire de l’arrivée est inconnu.'
        return result
    arrived_at = arrived_at.astimezone(timezone.utc)
    if arrived_at > now:
        result['warning'] = 'La date d’arrivée est future ; le compteur ne peut pas être calculé.'
        return result
    if status == 'closed':
        if closed_at is None:
            result['warning'] = 'Ancien dossier clôturé : renseignez sa date réelle de clôture pour figer un compteur fiable.'
            return result
        if closed_at.tzinfo is None or closed_at.utcoffset() is None:
            result['warning'] = 'Le fuseau horaire de la clôture est inconnu.'
            return result
        endpoint = closed_at.astimezone(timezone.utc)
        if endpoint > now or endpoint < arrived_at:
            result['warning'] = 'La date de clôture est incohérente avec l’arrivée ou la date actuelle.'
            return result
        state = 'closed'
    else:
        endpoint = now
        state = 'running'
    seconds = business_seconds(arrived_at, endpoint, timezone_name)
    result.update(timer_state=state, elapsed_hours=round(seconds / 3600, 6),
                  elapsed_days=int(seconds // 86400), is_overdue_48h=seconds > THRESHOLD_HOURS * 3600)
    return result
