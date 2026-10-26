"""Reminder scheduling, reliable deduplication and event accuracy."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from threading import Barrier
from uuid import uuid4
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import Client, DailyReminderPreferences, Equipment, InAppNotification, ServiceRequest, User
from core.notification_service import logistics_workload, notification_payload, notify_delivered, notify_received, preferences_payload, run_daily_reminders


EMPTY_WORKLOAD = {'pickups': [], 'deliveries': []}


@override_settings(TIME_ZONE='Africa/Lagos', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DailyLogisticsReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.courier = User.objects.create_user('notification-driver', role='courier')

    def test_opt_in_and_local_eight_oclock_are_both_required(self):
        before = datetime(2026, 10, 26, 6, 59, tzinfo=dt_timezone.utc)
        due = datetime(2026, 10, 26, 7, 0, tzinfo=dt_timezone.utc)
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            self.assertEqual(run_daily_reminders(now=due), 0)
            preference = DailyReminderPreferences.objects.create(user=self.courier, enabled=True)
            self.assertEqual(run_daily_reminders(now=before), 0)
            self.assertEqual(run_daily_reminders(now=due), 1)
            self.assertEqual(run_daily_reminders(now=due), 0)
            preference.enabled = False
            preference.save()
            self.assertEqual(run_daily_reminders(now=due.replace(day=27)), 0)

    def test_local_timezone_can_cross_the_utc_day_without_duplicate(self):
        DailyReminderPreferences.objects.create(user=self.courier, enabled=True, timezone='Pacific/Auckland')
        now = datetime(2026, 10, 26, 19, 0, tzinfo=dt_timezone.utc)  # 27 October, 08:00.
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            self.assertEqual(run_daily_reminders(now=now), 1)
            self.assertEqual(run_daily_reminders(now=now.replace(hour=20)), 0)
        self.assertEqual(InAppNotification.objects.get().local_date.isoformat(), '2026-10-27')

    def test_reactivation_on_same_local_day_keeps_original_reminder(self):
        preference = DailyReminderPreferences.objects.create(user=self.courier, enabled=True)
        now = datetime(2026, 10, 26, 10, 0, tzinfo=dt_timezone.utc)
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            self.assertEqual(run_daily_reminders(now=now), 1)
            preference.enabled = False
            preference.save()
            self.assertEqual(run_daily_reminders(now=now), 0)
            preference.enabled = True
            preference.save()
            self.assertEqual(run_daily_reminders(now=now), 0)
            self.assertEqual(run_daily_reminders(now=now.replace(day=27)), 1)

    def test_preference_schedule_matches_today_catch_up_then_tomorrow_after_creation(self):
        DailyReminderPreferences.objects.create(user=self.courier, enabled=True, timezone='Africa/Tunis')
        now = datetime(2026, 10, 26, 9, 0, tzinfo=dt_timezone.utc)
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            before = preferences_payload(self.courier, now=now)
            self.assertEqual(before['schedule_mode'], 'catch_up_today')
            self.assertEqual(before['next_run_at'], now)
            self.assertEqual(run_daily_reminders(now=now), 1)
            after = preferences_payload(self.courier, now=now)
            self.assertEqual(after['schedule_mode'], 'next_08')
            self.assertEqual(after['next_run_at'].isoformat(), '2026-10-27T08:00:00+01:00')

    def test_preference_preview_never_creates_a_message_or_stores_contacts(self):
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            payload = preferences_payload(self.courier)
        self.assertFalse(payload['enabled'])
        self.assertIsNone(payload['next_run_at'])
        self.assertEqual(payload['schedule_mode'], 'disabled')
        self.assertEqual(payload['channel_status'], 'requires_credentials')
        self.assertFalse(payload['whatsapp_connected'])
        self.assertFalse(payload['whatsapp_preview']['outbound_sent'])
        self.assertEqual(DailyReminderPreferences.objects.count(), 0)
        self.assertEqual(InAppNotification.objects.count(), 0)

    def test_only_identifiers_are_persisted_not_financial_or_contact_snapshots(self):
        DailyReminderPreferences.objects.create(user=self.courier, enabled=True)
        workload = {'pickups': [{'id': 5, 'address': 'Adresse fictive', 'contact_phone': 'CONTACT-FICTIF'}],
                    'deliveries': [{'id': 9, 'invoice_reference': 'NE-PAS-STOCKER'}]}
        with patch('core.notification_service.logistics_workload', return_value=workload):
            run_daily_reminders(now=datetime(2026, 10, 26, 10, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(InAppNotification.objects.get().payload, {'pickup_ids': [5], 'delivery_ids': [9]})

    def test_inactive_and_non_courier_accounts_do_not_receive_daily_reminders(self):
        DailyReminderPreferences.objects.create(user=self.courier, enabled=True)
        User.objects.filter(pk=self.courier.pk).update(is_active=False)
        another = User.objects.create_user('notification-tech', role='technician')
        DailyReminderPreferences.objects.create(user=another, enabled=True)
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD):
            self.assertEqual(run_daily_reminders(), 0)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReceivingNotificationTests(TestCase):
    def test_receiving_notice_requires_real_arrival_and_only_reaches_own_active_portal(self):
        company = Client.objects.create(name='Client notification fictif')
        foreign = Client.objects.create(name='Autre client notification fictif')
        unit = Equipment.objects.create(client=company, serial_number='NOTIF-FAUX-001', model='Onduleur fictif')
        record = ServiceRequest.objects.create(equipment=unit, subject='Réception fictive')
        owner = User.objects.create_user('notification-client', role='client', client=company)
        User.objects.create_user('notification-foreign', role='client', client=foreign)
        User.objects.create_user('notification-disabled', role='client', client=company, is_active=False)
        self.assertEqual(notify_received(record.pk), 0)
        record.arrived_at = timezone.now()
        record.save(update_fields=['arrived_at'])
        self.assertEqual(notify_received(record.pk), 1)
        self.assertEqual(notify_received(record.pk), 0)
        notice = InAppNotification.objects.get()
        self.assertEqual(notice.recipient_id, owner.pk)
        self.assertEqual(notice.kind, InAppNotification.Kind.RECEIVED)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogisticsNotificationWorkloadTests(TestCase):
    def setUp(self):
        from core.disposition_workflow import mark_repaired
        from core.logistics_models import OutboundJob, PickupRequest
        self.manager = User.objects.create_user('notice-work-manager', role='manager')
        self.driver = User.objects.create_user('notice-work-driver', role='courier')
        self.other_driver = User.objects.create_user('notice-work-other', role='courier')
        self.company = Client.objects.create(name='Centre Mission Fictif', address='Ancienne adresse fictive')
        self.owner = User.objects.create_user('notice-work-client', role='client', client=self.company)
        self.unit = Equipment.objects.create(client=self.company, serial_number='NOTICE-JOB-FICTIF', model='Modèle fictif')
        self.record = ServiceRequest.objects.create(equipment=self.unit, subject='Remise fictive', status='testing')
        mark_repaired(self.record.pk, {'diagnosis': 'Tests fictifs réussis.', 'tests_passed': True, 'tested_on': timezone.localdate()}, actor=self.manager)
        self.job = OutboundJob.objects.create(service_request=self.record, client=self.company, delivery_equipment=self.unit, kind='delivery',
            assigned_courier=self.driver, assigned_at=timezone.now(), assigned_by=self.manager,
            delivery_address='Destination de mission fictive', contact_name='Contact de mission fictif', contact_phone='CONTACT-FICTIF')
        self.pickup = PickupRequest.objects.create(client=self.company, serial_number='NOTICE-PICKUP-FICTIF',
            fault_description='Défaut fictif', pickup_address='Collecte fictive', contact_name='Contact fictif',
            assigned_courier=self.driver, status='assigned', requested_by=self.owner, request_key=uuid4(), payload_hash='0' * 64)
        PickupRequest.objects.create(client=self.company, serial_number='NOTICE-PICKUP-AUTRE',
            fault_description='Défaut fictif', pickup_address='Autre collecte fictive', contact_name='Contact fictif',
            assigned_courier=self.other_driver, status='assigned', requested_by=self.owner, request_key=uuid4(), payload_hash='1' * 64)

    def test_real_workload_uses_current_assignment_and_mission_destination(self):
        workload = logistics_workload(self.driver)
        self.assertEqual([row['id'] for row in workload['pickups']], [self.pickup.pk])
        self.assertEqual([row['id'] for row in workload['deliveries']], [self.job.pk])
        self.assertEqual(workload['deliveries'][0]['address'], 'Destination de mission fictive')
        self.assertEqual(workload['deliveries'][0]['contact_name'], 'Contact de mission fictif')
        notice = InAppNotification.objects.create(recipient=self.driver, kind='daily_logistics', dedup_key='test-real-workload',
            local_date=timezone.localdate(), payload={'pickup_ids': [], 'delivery_ids': [self.job.pk]})
        self.job.assigned_courier = self.other_driver
        self.job.save(update_fields=['assigned_courier'])
        self.assertEqual(notification_payload(notice, self.driver)['details']['deliveries'], [])

    def test_handoff_notice_requires_proof_and_retries_do_not_duplicate_it(self):
        self.assertEqual(notify_delivered(self.job.pk), 0)
        self.job.handed_over_at = timezone.now()
        self.job.handed_over_by = self.driver
        self.job.recipient_name = 'Destinataire fictif'
        self.job.active = False
        self.job.save(update_fields=['handed_over_at', 'handed_over_by', 'recipient_name', 'active'])
        self.assertEqual(notify_delivered(self.job.pk), 1)
        self.assertEqual(notify_delivered(self.job.pk), 0)
        notice = InAppNotification.objects.get()
        self.assertEqual(notice.recipient_id, self.owner.pk)
        self.assertEqual(notice.kind, InAppNotification.Kind.DELIVERED)
        self.assertEqual(logistics_workload(self.driver)['deliveries'], [])


class ReminderWorkerCommandTests(SimpleTestCase):
    def test_once_reports_only_internal_delivery_and_does_not_loop(self):
        output = StringIO()
        with patch('core.management.commands.logistics_reminders.run_daily_reminders', return_value=2) as run:
            call_command('logistics_reminders', once=True, stdout=output)
        run.assert_called_once_with()
        self.assertIn('Rappels internes créés : 2', output.getvalue())
        self.assertIn('aucun envoi externe', output.getvalue())

    def test_invalid_poll_interval_is_rejected_before_accessing_database(self):
        for interval in (0, 9, 3601):
            with self.assertRaises(CommandError):
                call_command('logistics_reminders', once=True, interval=interval)


@skipUnless(connection.vendor == 'postgresql', 'Concurrency requires real PostgreSQL connections.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DailyReminderConcurrencyTests(TransactionTestCase):
    def test_two_workers_create_one_daily_notice(self):
        courier = User.objects.create_user('notification-concurrent', role='courier')
        DailyReminderPreferences.objects.create(user=courier, enabled=True, timezone='Africa/Lagos')
        barrier = Barrier(2)
        now = datetime(2026, 10, 26, 7, 0, tzinfo=dt_timezone.utc)
        def work():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return run_daily_reminders(now=now)
            finally:
                connections.close_all()
        with patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(InAppNotification.objects.count(), 1)
