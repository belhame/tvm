"""Independent transport notification checks; no real provider is contacted."""

from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import AuditLog, Client, Equipment, OutboundJob, ServiceRequest
from core.outbox_adapters import DeliveryFailure
from core.outbox_models import ExternalNotification


CONFIGURED_EMAIL = {
    'TVM_EMAIL_ENABLED': True, 'TVM_WHATSAPP_ENABLED': False,
    'EMAIL_HOST': 'smtp.fixture.invalid', 'EMAIL_HOST_USER': 'fixture-only-user',
    'EMAIL_HOST_PASSWORD': 'FIXTURE_ONLY_PASSWORD_NOT_A_CREDENTIAL',
    'DEFAULT_FROM_EMAIL': 'tvm-fixture@example.invalid',
    'EMAIL_USE_TLS': True, 'EMAIL_USE_SSL': False,
}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   TVM_EMAIL_ENABLED=False, TVM_WHATSAPP_ENABLED=False)
class IndependentOutboxReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Envois Fictif', email='centre-origin@example.invalid', phone='+22900000001', notify_email=True, notify_whatsapp=True)
        cls.other_company = Client.objects.create(name='Autre Centre Envois Fictif', email='autre-centre@example.invalid')
        cls.admin = User.objects.create_user('outbox-review-admin', role='admin')
        cls.manager = User.objects.create_user('outbox-review-manager', role='manager')
        cls.courier = User.objects.create_user('outbox-review-courier', role='courier')
        cls.external = User.objects.create_user('outbox-review-external', role='courier', courier_kind='client', client=cls.company)
        cls.customer = User.objects.create_user('outbox-review-client', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='OUTBOX-FICTION-0001', model='Onduleur notifications fictif')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='Transport fictif de notification')
        ServiceRequest.objects.filter(pk=cls.record.pk).update(status='ready_for_delivery')
        cls.job = OutboundJob.objects.create(service_request=cls.record, client=cls.company, delivery_equipment=cls.unit,
            assigned_courier=cls.courier, assigned_by=cls.admin, assigned_at=timezone.now(), kind='delivery',
            delivery_address='Adresse de transport fictive', contact_name='Contact transport fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def enqueue(self):
        from core.outbox_service import notify_transport_assignment
        notify_transport_assignment(self.job.pk, revision=self.job.assignment_revision)
        return ExternalNotification.objects.get(outbound=self.job, channel='email')

    def test_journal_and_preview_gets_do_not_write_or_expose_credentials_or_full_recipient(self):
        item = self.enqueue()
        before = list(ExternalNotification.objects.values()), AuditLog.objects.count()
        with override_settings(EMAIL_HOST_PASSWORD='PRIVATE_SMTP_SENTINEL', TVM_WHATSAPP_TOKEN='PRIVATE_META_SENTINEL'):
            for path in ('/api/logistics/outbox/', f'/api/logistics/outbox/{item.pk}/preview/'):
                response = self.api.get(path)
                self.assertEqual(response.status_code, 200, response.json())
                self.assertIn('no-store', response['Cache-Control'])
                for private in ('PRIVATE_SMTP_SENTINEL', 'PRIVATE_META_SENTINEL', self.company.email):
                    self.assertNotIn(private, str(response.json()))
        self.assertEqual((list(ExternalNotification.objects.values()), AuditLog.objects.count()), before)

    def test_clients_and_all_couriers_cannot_read_or_retry_the_manager_journal(self):
        item = self.enqueue()
        for actor in (self.customer, self.courier, self.external):
            self.api.force_authenticate(actor)
            for path in ('/api/logistics/outbox/', f'/api/logistics/outbox/{item.pk}/preview/'):
                response = self.api.get(path)
                self.assertEqual(response.status_code, 403, response.json())
            response = self.api.post(f'/api/logistics/outbox/{item.pk}/retry/', {'preview_token': 'FORGED'}, format='json')
            self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(ExternalNotification.objects.get(pk=item.pk).state, 'blocked')

    def test_client_channel_status_is_own_company_only_without_secrets(self):
        self.api.force_authenticate(self.customer)
        response = self.api.get('/api/logistics/channels/')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertFalse(response.json()['email']['operational'])
        self.assertFalse(response.json()['whatsapp']['operational'])
        self.assertEqual(response.json()['client_preferences'], {'notify_email': True, 'notify_whatsapp': True})
        self.assertEqual(self.api.get(f'/api/logistics/channels/?client={self.other_company.pk}').status_code, 403)
        self.api.force_authenticate(self.external)
        self.assertEqual(self.api.get('/api/logistics/channels/').status_code, 403)

    def test_centre_logistics_inbox_never_exposes_a_foreign_case_from_an_inconsistent_source(self):
        from core.logistics_models import PickupRequest
        from core.outbox_service import notify_pickup_event

        pickup = PickupRequest.objects.create(client=self.company, equipment=self.unit, serial_number=self.unit.serial_number,
            pickup_scope='end_customer', end_customer_name='Client final fictif', fault_description='Panne fictive',
            pickup_address='Adresse finale fictive', contact_name='Contact final fictif', requested_by=self.customer,
            request_key=uuid4(), payload_hash='0' * 64)
        notify_pickup_event(pickup.pk, 'pickup_requested', revision=pickup.assignment_revision)
        self.api.force_authenticate(self.customer)
        own = self.api.get('/api/logistics/notifications/')
        self.assertEqual(own.status_code, 200, own.json())
        self.assertTrue(any(row['kind'] == 'logistics_update' for row in own.json()['results']))
        foreign_unit = Equipment.objects.create(client=self.other_company, serial_number='OUTBOX-FOREIGN-INBOX', model='Autre modèle fictif')
        foreign_record = ServiceRequest.objects.create(equipment=foreign_unit, subject='PRIVATE_FOREIGN_INBOX_SUBJECT')
        PickupRequest.objects.filter(pk=pickup.pk).update(service_request=foreign_record)
        response = self.api.get('/api/logistics/notifications/')
        self.assertEqual(response.status_code, 200, response.json())
        for private in (foreign_record.reference, foreign_unit.serial_number, self.other_company.name, 'PRIVATE_FOREIGN_INBOX_SUBJECT'):
            self.assertNotIn(private, str(response.json()))
        self.assertTrue(all(row['service_request'] is None for row in response.json()['results']))

    def test_disabled_channels_never_send_and_enabling_configuration_does_not_replay_blocked_backlog(self):
        from core.outbox_service import notify_transport_assignment, process_outbox

        with (patch('socket.socket.connect', side_effect=AssertionError('No notification transport may be opened.')),
                patch('core.outbox_service.deliver_email') as email,
                patch('core.outbox_service.deliver_whatsapp') as whatsapp):
            self.enqueue()
            self.assertEqual(process_outbox(), 0)
            with override_settings(**CONFIGURED_EMAIL):
                self.assertEqual(process_outbox(), 0)
                notify_transport_assignment(self.job.pk, revision=self.job.assignment_revision)
                self.assertEqual(process_outbox(), 0)
            email.assert_not_called()
            whatsapp.assert_not_called()
        self.assertEqual(ExternalNotification.objects.count(), 2)
        self.assertEqual(set(ExternalNotification.objects.values_list('state', flat=True)), {'blocked'})
        self.assertFalse(ExternalNotification.objects.filter(sent_at__isnull=False).exists())

    @override_settings(**CONFIGURED_EMAIL)
    def test_retry_requires_current_actor_and_recipient_preview_then_sends_only_to_parent_centre(self):
        from core.outbox_service import process_outbox

        # Start blocked; explicit manager review authorizes only the current
        # destination. A later email edit invalidates the earlier preview.
        with override_settings(TVM_EMAIL_ENABLED=False):
            item = self.enqueue()
        preview = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/').json()
        self.company.email = 'centre-current@example.invalid'
        self.company.save(update_fields=['email'])
        with patch('core.outbox_service.deliver_email', return_value='') as email:
            response = self.api.post(f'/api/logistics/outbox/{item.pk}/retry/', {'preview_token': preview['preview_token']}, format='json')
            self.assertEqual(response.status_code, 400, response.json())
            email.assert_not_called()
            fresh = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/').json()
            self.api.force_authenticate(self.manager)
            response = self.api.post(f'/api/logistics/outbox/{item.pk}/retry/', {'preview_token': fresh['preview_token']}, format='json')
            self.assertEqual(response.status_code, 400, response.json())
            fresh = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/').json()
            response = self.api.post(f'/api/logistics/outbox/{item.pk}/retry/', {'preview_token': fresh['preview_token']}, format='json')
            self.assertEqual(response.status_code, 200, response.json())
            self.assertEqual(response.json()['state'], 'pending')
            self.assertEqual(process_outbox(), 1)
            self.assertEqual(email.call_count, 1)
            self.assertEqual(email.call_args.args[0], 'centre-current@example.invalid')
        item.refresh_from_db()
        self.assertEqual(item.state, 'sent')
        self.assertEqual(item.provider_status, 'accepted')
        self.assertIsNotNone(item.sent_at)

    @override_settings(**CONFIGURED_EMAIL)
    def test_ambiguous_provider_acceptance_is_never_automatically_retried(self):
        from core.outbox_service import process_outbox

        item = self.enqueue()
        with patch('core.outbox_service.deliver_email', side_effect=DeliveryFailure('smtp_acceptance_unknown', uncertain=True)) as email:
            self.assertEqual(process_outbox(), 1)
            self.assertEqual(process_outbox(), 0)
            self.assertEqual(email.call_count, 1)
        item.refresh_from_db()
        self.assertEqual(item.state, 'uncertain')
        self.assertIsNone(item.sent_at)
        preview = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/').json()
        response = self.api.post(f'/api/logistics/outbox/{item.pk}/retry/', {'preview_token': preview['preview_token']}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        item.refresh_from_db()
        self.assertEqual(item.state, 'uncertain')

    @override_settings(**CONFIGURED_EMAIL)
    def test_queued_email_is_blocked_if_destination_changes_before_worker(self):
        from core.outbox_service import process_outbox

        item = self.enqueue()
        self.company.email = 'changed-before-send@example.invalid'
        self.company.save(update_fields=['email'])
        with patch('core.outbox_service.deliver_email') as email:
            self.assertEqual(process_outbox(), 1)
            email.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.state, 'blocked')
        self.assertEqual(item.blocked_reason, 'recipient_changed')
        self.assertIsNone(item.sent_at)

    @override_settings(**CONFIGURED_EMAIL)
    def test_noncanonical_unit_cancels_queued_assignment_instead_of_notifying_the_wrong_serial(self):
        from core.outbox_service import process_outbox

        item = self.enqueue()
        wrong = Equipment.objects.create(client=self.company, serial_number='OUTBOX-WRONG-UNIT-FICTION', model='Autre matériel fictif')
        OutboundJob.objects.filter(pk=self.job.pk).update(delivery_equipment=wrong)
        with patch('core.outbox_service.deliver_email') as email:
            self.assertEqual(process_outbox(), 1)
            email.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.state, 'cancelled')
        preview = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/')
        self.assertNotIn(wrong.serial_number, str(preview.json()))
        self.assertIsNone(item.sent_at)

    @override_settings(**CONFIGURED_EMAIL)
    def test_pending_pickup_notification_never_forwards_a_foreign_linked_case(self):
        from core.logistics_models import PickupRequest
        from core.outbox_service import notify_pickup_event, process_outbox

        pickup = PickupRequest.objects.create(client=self.company, equipment=self.unit, serial_number=self.unit.serial_number,
            pickup_scope='end_customer', end_customer_name='Client final fictif', fault_description='Panne fictive',
            pickup_address='Adresse finale fictive', contact_name='Contact final fictif', contact_phone='+22900000002',
            requested_by=self.customer, request_key=uuid4(), payload_hash='0' * 64, service_request=self.record)
        notify_pickup_event(pickup.pk, 'pickup_created', revision=pickup.assignment_revision)
        item = ExternalNotification.objects.get(pickup=pickup, channel='email')
        unit = Equipment.objects.create(client=self.other_company, serial_number='OUTBOX-FOREIGN-FICTION', model='Modèle étranger fictif')
        foreign = ServiceRequest.objects.create(equipment=unit, subject='Dossier étranger fictif')
        PickupRequest.objects.filter(pk=pickup.pk).update(service_request=foreign)
        with patch('core.outbox_service.deliver_email') as email:
            self.assertEqual(process_outbox(), 1)
            email.assert_not_called()
        item.refresh_from_db()
        self.assertIn(item.state, ('blocked', 'cancelled'))
        preview = self.api.get(f'/api/logistics/outbox/{item.pk}/preview/')
        self.assertEqual(preview.status_code, 200, preview.json())
        self.assertNotIn(foreign.reference, str(preview.json()))
        self.assertNotIn(unit.serial_number, str(preview.json()))
