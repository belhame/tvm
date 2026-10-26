from datetime import datetime, timedelta, timezone
from unittest import TestCase
from zoneinfo import ZoneInfo

from core.request_timing import request_timing


class BusinessTimingTests(TestCase):
    zone = ZoneInfo('Africa/Lagos')

    def day(self, value):
        return datetime.fromisoformat(value).replace(tzinfo=self.zone)

    def calculate(self, arrival, now, *, status='pending', closed=None, zone='Africa/Lagos'):
        return request_timing(arrival, closed, status, now=now, timezone_name=zone)

    def test_friday_to_monday_counts_twenty_four_hours(self):
        result = self.calculate(self.day('2026-10-23T10:00'), self.day('2026-10-26T10:00'))
        self.assertEqual((result['elapsed_hours'], result['elapsed_days']), (24, 1))
        self.assertFalse(result['is_overdue_48h'])

    def test_exactly_two_weekdays_stays_green_then_becomes_late(self):
        arrived = self.day('2026-10-23T10:00')
        threshold = self.day('2026-10-27T10:00')
        result = self.calculate(arrived, threshold)
        self.assertEqual(result['elapsed_hours'], 48)
        self.assertFalse(result['is_overdue_48h'])
        self.assertTrue(self.calculate(arrived, threshold + timedelta(seconds=1))['is_overdue_48h'])
        self.assertAlmostEqual(self.calculate(arrived, threshold + timedelta(hours=1))['elapsed_hours'], 49)

    def test_weekend_does_not_advance_and_weekend_arrival_starts_monday(self):
        arrived = self.day('2026-10-24T12:00')
        self.assertEqual(self.calculate(arrived, self.day('2026-10-25T20:00'))['elapsed_hours'], 0)
        self.assertEqual(self.calculate(arrived, self.day('2026-10-26T10:00'))['elapsed_hours'], 10)
        friday = self.day('2026-10-23T23:00')
        self.assertEqual(self.calculate(friday, self.day('2026-10-25T23:00'))['elapsed_hours'], 1)

    def test_complete_weeks_and_day_floor(self):
        result = self.calculate(self.day('2026-10-19T00:00'), self.day('2026-11-02T01:30'))
        self.assertEqual(result['elapsed_hours'], 241.5)
        self.assertEqual(result['elapsed_days'], 10)

    def test_local_timezone_defines_weekend_boundaries(self):
        start = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        self.assertEqual(self.calculate(start, end)['elapsed_hours'], 1)
        self.assertEqual(self.calculate(start, end, zone='UTC')['elapsed_hours'], .5)

    def test_dst_weekend_is_excluded_without_phantom_hour(self):
        paris = ZoneInfo('Europe/Paris')
        for friday, monday in [('2026-03-27T10:00', '2026-03-30T10:00'), ('2026-10-23T10:00', '2026-10-26T10:00')]:
            start = datetime.fromisoformat(friday).replace(tzinfo=paris)
            end = datetime.fromisoformat(monday).replace(tzinfo=paris)
            result = self.calculate(start, end, zone='Europe/Paris')
            self.assertEqual(result['elapsed_hours'], 24)

    def test_closed_counter_and_historical_lateness_remain_frozen(self):
        arrived = self.day('2026-10-23T10:00')
        closed = self.day('2026-10-27T11:00')
        result = self.calculate(arrived, self.day('2026-11-10T15:00'), status='closed', closed=closed)
        self.assertEqual((result['timer_state'], result['elapsed_hours'], result['elapsed_days']), ('closed', 49, 2))
        self.assertTrue(result['is_overdue_48h'])

    def test_unknown_arrival_and_unknown_historical_closure_are_not_invented(self):
        now = self.day('2026-10-27T11:00')
        for arrived, status in [(None, 'new'), (self.day('2026-10-23T10:00'), 'closed')]:
            result = self.calculate(arrived, now, status=status)
            self.assertEqual(result['timer_state'], 'unknown')
            self.assertIsNone(result['elapsed_hours'])
            self.assertFalse(result['is_overdue_48h'])
            self.assertTrue(result['warning'])

    def test_future_reversed_and_naive_timestamps_remain_unknown(self):
        now = self.day('2026-10-27T11:00')
        for arrived, closed, status in [
            (now + timedelta(days=1), None, 'pending'),
            (now, now - timedelta(hours=1), 'closed'),
            (now - timedelta(hours=1), now + timedelta(hours=1), 'closed'),
            (datetime(2026, 10, 23), None, 'pending'),
        ]:
            self.assertEqual(self.calculate(arrived, now, closed=closed, status=status)['timer_state'], 'unknown')

    def test_resolved_or_rejected_is_running_until_explicitly_closed(self):
        for state in ['resolved', 'rejected']:
            result = self.calculate(self.day('2026-10-23T10:00'), self.day('2026-10-27T11:00'), status=state)
            self.assertEqual(result['timer_state'], 'running')
            self.assertTrue(result['is_overdue_48h'])
