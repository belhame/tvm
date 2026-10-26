"""Independent notice/privacy checks with fictional tasks and recipients."""

from datetime import date, datetime, timezone as dt_timezone
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client as BrowserClient, TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Client, Equipment, ServiceRequest
from core.notification_models import DailyReminderPreferences, InAppNotification
from core.notification_service import run_daily_reminders


EMPTY_WORKLOAD = {'pickups': [], 'deliveries': []}
PREFERENCES = '/api/logistics/notifications/preferences/'
INBOX = '/api/logistics/notifications/'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentNotificationReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.courier = User.objects.create_user('notice-review-courier', role='courier')
        cls.other_courier = User.objects.create_user('notice-review-other-courier', role='courier')
        cls.company = Client.objects.create(name='Centre Notifications Fictif')
        cls.other_company = Client.objects.create(name='Autre Centre Notifications Fictif')
        cls.customer = User.objects.create_user('notice-review-client', role='client', client=cls.company)
        unit = Equipment.objects.create(client=cls.company, serial_number='NOTICE-FICTION-001', model='Modèle fictif')
        other_unit = Equipment.objects.create(client=cls.other_company, serial_number='NOTICE-FICTION-002', model='Autre modèle fictif')
        cls.request = ServiceRequest.objects.create(equipment=unit, subject='Notification fictive')
        cls.other_request = ServiceRequest.objects.create(equipment=other_unit, subject='Autre notification fictive')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.courier)
        self.workload = patch('core.notification_service.logistics_workload', return_value=EMPTY_WORKLOAD)
        self.workload.start()
        self.addCleanup(self.workload.stop)

    def test_get_preferences_is_read_only_and_never_claims_a_whatsapp_send(self):
        for _ in range(2):
            response = self.api.get(PREFERENCES)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertFalse(response.data['enabled'])
            self.assertFalse(response.data['whatsapp_connected'])
            self.assertFalse(response.data['whatsapp_can_send'])
            self.assertEqual(response.data['channel_status'], 'requires_credentials')
            self.assertEqual(response.data['whatsapp_preview']['status'], 'preview_only')
            self.assertFalse(response.data['whatsapp_preview']['outbound_sent'])
            self.assertEqual((response.data['hour'], response.data['minute']), (8, 0))
            self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(DailyReminderPreferences.objects.exists())
        self.assertFalse(InAppNotification.objects.exists())

    def test_preferences_cannot_target_another_account_or_set_transport_flags(self):
        for field in ('user', 'recipient', 'whatsapp_can_send', 'outbound_sent', 'hour', 'api_token'):
            with self.subTest(field=field):
                response = self.api.patch(PREFERENCES, {'enabled': True, field: self.other_courier.pk}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        response = self.api.patch(PREFERENCES, {'enabled': True, 'timezone': 'Africa/Tunis'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(list(DailyReminderPreferences.objects.values_list('user_id', flat=True)), [self.courier.pk])
        self.assertEqual(self.api.patch(PREFERENCES, {'timezone': 'NOT/A_ZONE'}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(PREFERENCES, {'enabled': 'true'}, format='json').status_code, 400)

    def test_preferences_patch_enforces_real_session_csrf(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.courier)
        response = browser.patch(PREFERENCES, {'enabled': True}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DailyReminderPreferences.objects.exists())
        token = browser.get('/api/session/').json()['csrfToken']
        response = browser.patch(PREFERENCES, {'enabled': True, 'timezone': 'Africa/Tunis'}, content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(DailyReminderPreferences.objects.get().user_id, self.courier.pk)

    def test_inbox_and_read_acknowledgment_are_recipient_scoped_and_idempotent(self):
        own = InAppNotification.objects.create(recipient=self.courier, kind='daily_logistics', dedup_key='review-own', local_date=date(2025, 10, 15), payload={})
        foreign = InAppNotification.objects.create(recipient=self.other_courier, kind='daily_logistics', dedup_key='review-foreign', local_date=date(2025, 10, 15), payload={'raw_text': 'FOREIGN_NOTICE_PRIVATE'})
        response = self.api.get(INBOX)
        self.assertEqual([item['id'] for item in response.data['results']], [own.pk])
        self.assertNotIn('FOREIGN_NOTICE_PRIVATE', str(response.data))
        self.assertEqual(self.api.patch(f'{INBOX}{foreign.pk}/read/', {'read': True}, format='json').status_code, 404)
        self.assertEqual(self.api.patch(f'{INBOX}{own.pk}/read/', {'read': False}, format='json').status_code, 400)
        first = self.api.patch(f'{INBOX}{own.pk}/read/', {'read': True}, format='json')
        second = self.api.patch(f'{INBOX}{own.pk}/read/', {'read': True}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['read_at'], second.data['read_at'])
        foreign.refresh_from_db()
        self.assertIsNone(foreign.read_at)

    def test_daily_reminder_obeys_local_eight_disabling_and_one_notice_per_day_without_network(self):
        preference = DailyReminderPreferences.objects.create(user=self.courier, enabled=True, timezone='Africa/Tunis')
        with patch('socket.socket.connect', side_effect=AssertionError('A reminder must not open an outbound transport.')):
            self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 15, 6, 59, tzinfo=dt_timezone.utc)), 0)
            self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 15, 7, 0, tzinfo=dt_timezone.utc)), 1)
            self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 15, 17, 0, tzinfo=dt_timezone.utc)), 0)
            self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 16, 7, 0, tzinfo=dt_timezone.utc)), 1)
            preference.enabled = False
            preference.save(update_fields=['enabled'])
            self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 17, 7, 0, tzinfo=dt_timezone.utc)), 0)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.courier).count(), 2)
        self.assertEqual(set(InAppNotification.objects.values_list('kind', flat=True)), {'daily_logistics'})

    def test_old_assignment_details_are_not_replayed_from_notification_payload(self):
        notice = InAppNotification.objects.create(recipient=self.courier, kind='daily_logistics', dedup_key='review-reassigned', local_date=date(2025, 10, 15), payload={
            'pickup_ids': [42], 'delivery_ids': [51],
            'address': 'FORMER_ASSIGNMENT_PRIVATE_ADDRESS', 'raw_ocr': 'PRIVATE_UNTRUSTED_OCR_TEXT',
        })
        # Current assignments are empty: IDs from an older reminder cannot
        # confer access to a mission that now belongs to another courier.
        response = self.api.get(INBOX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['id'], notice.pk)
        self.assertEqual(response.data['results'][0]['details'], EMPTY_WORKLOAD)
        self.assertNotIn('FORMER_ASSIGNMENT_PRIVATE_ADDRESS', json.dumps(response.data, default=str))
        self.assertNotIn('PRIVATE_UNTRUSTED_OCR_TEXT', json.dumps(response.data, default=str))

    def test_client_only_sees_own_receipts_and_no_courier_daily_list_or_fake_client_ack(self):
        own = InAppNotification.objects.create(recipient=self.customer, kind='equipment_delivered', dedup_key='review-own-delivery', local_date=date(2025, 10, 15), service_request=self.request, payload={'recorded_by_role': 'courier'})
        foreign = InAppNotification.objects.create(recipient=self.customer, kind='equipment_received', dedup_key='review-foreign-receipt', local_date=date(2025, 10, 15), service_request=self.other_request)
        InAppNotification.objects.create(recipient=self.customer, kind='daily_logistics', dedup_key='review-invalid-daily', local_date=date(2025, 10, 15), payload={'address': 'COURIER_ASSIGNMENTS_PRIVATE'})
        self.api.force_authenticate(self.customer)
        response = self.api.get(INBOX)
        self.assertEqual([item['id'] for item in response.data['results']], [own.pk])
        self.assertIn('livreur', response.data['results'][0]['body'])
        self.assertNotIn('client a confirmé', response.data['results'][0]['body'].lower())
        self.assertNotIn('COURIER_ASSIGNMENTS_PRIVATE', str(response.data))
        self.assertEqual(self.api.patch(f'{INBOX}{foreign.pk}/read/', {'read': True}, format='json').status_code, 404)
        self.assertEqual(self.api.get(PREFERENCES).status_code, 403)

    def test_role_change_stops_future_courier_reminders_and_hides_old_task_details(self):
        DailyReminderPreferences.objects.create(user=self.courier, enabled=True, timezone='Africa/Tunis')
        InAppNotification.objects.create(recipient=self.courier, kind='daily_logistics', dedup_key='review-old-role', local_date=date(2025, 10, 15), payload={'pickup_ids': [42]})
        self.courier.role = 'technician'
        self.courier.save(update_fields=['role'])
        self.assertEqual(run_daily_reminders(now=datetime(2025, 10, 16, 7, 0, tzinfo=dt_timezone.utc)), 0)
        self.assertEqual(self.api.get(PREFERENCES).status_code, 403)
        response = self.api.get(INBOX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['details'], EMPTY_WORKLOAD)

    def test_manager_recorded_handoff_is_not_attributed_to_a_courier_or_customer_signature(self):
        InAppNotification.objects.create(recipient=self.customer, kind='equipment_delivered',
            dedup_key='review-team-delivery', local_date=date(2025, 10, 15),
            service_request=self.request, payload={'recorded_by_role': 'manager',
                'actor_name': 'PRIVATE_UNUSED_MANAGER_NAME', 'invoice_reference': 'PRIVATE_UNUSED_INVOICE'})
        self.api.force_authenticate(self.customer)
        response = self.api.get(INBOX)
        self.assertEqual(response.status_code, 200)
        body = response.data['results'][0]['body']
        self.assertIn('TVM', body)
        self.assertNotIn('livreur', body.lower())
        self.assertNotIn('client a confirmé', body.lower())
        self.assertNotIn('PRIVATE_UNUSED', str(response.data))
