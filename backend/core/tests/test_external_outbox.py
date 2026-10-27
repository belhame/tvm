"""Synthetic delivery only: locmem SMTP and mocked WhatsApp transport."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import json
import smtplib
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from urllib.error import HTTPError

from django.core import mail
from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.disposition_workflow import mark_repaired
from core.logistics_models import OutboundJob
from core.models import Client, Equipment, User, ServiceRequest
from core.notification_models import InAppNotification
from core.outbox_adapters import DeliveryFailure, NoRedirect, deliver_email, deliver_whatsapp
from core.outbox_models import ExternalNotification
from core.outbox_service import notify_transport_assignment, preview, process_outbox, retry_notification


EMAIL_SETTINGS = dict(TVM_EMAIL_ENABLED=True, EMAIL_HOST='smtp.example.invalid', EMAIL_HOST_USER='synthetic',
    EMAIL_HOST_PASSWORD='synthetic-password', EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
    DEFAULT_FROM_EMAIL='tvm@example.invalid', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')


def fixture(suffix=''):
    admin = User.objects.create_user(f'outbox-admin{suffix}', role='admin')
    courier = User.objects.create_user(f'outbox-courier{suffix}', role='courier', courier_kind='internal')
    client = Client.objects.create(name=f'Centre Outbox Fictif {suffix}', contact_name='Responsable fictif',
        email='responsable@example.invalid', phone='+99912345678', notify_email=True, notify_whatsapp=True)
    portal = User.objects.create_user(f'outbox-client{suffix}', role='client', client=client)
    unit = Equipment.objects.create(client=client, serial_number=f'OUTBOX-FICTIF-{suffix or "A"}', model='Onduleur fictif')
    record = ServiceRequest.objects.create(equipment=unit, subject='Essai fictif', status='testing')
    mark_repaired(record.pk, {'diagnosis': 'Tests fictifs réussis', 'tested_on': timezone.localdate(), 'tests_passed': True}, actor=admin)
    job = OutboundJob.objects.create(client=client, service_request=record, delivery_equipment=unit, kind='delivery',
        assigned_courier=courier, assigned_by=admin, assigned_at=timezone.now(), assignment_revision=1,
        delivery_address='Adresse de livraison fictive')
    return admin, courier, client, portal, record, job


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TVM_EMAIL_ENABLED=False, TVM_WHATSAPP_ENABLED=False)
class ExternalOutboxTests(TestCase):
    def setUp(self):
        self.admin, self.courier, self.client, self.portal, self.record, self.job = fixture()

    def email(self):
        return ExternalNotification.objects.get(channel='email')

    def test_default_disabled_creates_two_blocked_channels_and_own_centre_notice_without_send(self):
        with patch('core.outbox_service.deliver_email') as email, patch('core.outbox_service.deliver_whatsapp') as whatsapp:
            self.assertEqual(notify_transport_assignment(self.job.pk), 2)
            self.assertEqual(notify_transport_assignment(self.job.pk), 0)
            self.assertEqual(process_outbox(), 0)
        email.assert_not_called()
        whatsapp.assert_not_called()
        self.assertEqual(list(ExternalNotification.objects.values_list('state', flat=True)), ['blocked', 'blocked'])
        self.assertEqual(InAppNotification.objects.filter(recipient=self.portal, kind='logistics_update').count(), 1)

    def test_enabling_provider_never_bulk_sends_the_old_blocked_queue(self):
        notify_transport_assignment(self.job.pk)
        with override_settings(**EMAIL_SETTINGS), patch('core.outbox_service.deliver_email') as send:
            self.assertEqual(process_outbox(), 0)
        send.assert_not_called()
        self.assertEqual(self.email().state, 'blocked')

    @override_settings(**EMAIL_SETTINGS)
    def test_locmem_adapter_sends_only_to_current_responsible_centre_and_records_acceptance(self):
        notify_transport_assignment(self.job.pk)
        self.assertEqual(process_outbox(), 1)
        item = self.email()
        self.assertEqual(item.state, 'sent')
        self.assertEqual(item.provider_status, 'accepted')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['responsable@example.invalid'])
        self.assertIn(self.record.reference, mail.outbox[0].body)
        self.assertIn(self.job.delivery_equipment.serial_number, mail.outbox[0].body)
        self.assertIn('Livreur : outbox-courier (TVM)', mail.outbox[0].body)
        self.assertNotIn('diagnosis', mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].extra_headers['Message-ID'].endswith('@example.invalid>'))
        self.assertEqual(process_outbox(), 0)

    @override_settings(**EMAIL_SETTINGS)
    def test_changed_recipient_requires_fresh_preview_and_manual_retry(self):
        notify_transport_assignment(self.job.pk)
        old_preview = preview(self.email(), self.admin)
        self.client.email = 'nouveau@example.invalid'
        self.client.save(update_fields=['email'])
        with patch('core.outbox_service.deliver_email') as send:
            process_outbox()
        send.assert_not_called()
        item = self.email()
        self.assertEqual((item.state, item.blocked_reason), ('blocked', 'recipient_changed'))
        with self.assertRaises(ValidationError):
            retry_notification(item.pk, self.admin, old_preview['preview_token'])
        current = preview(item, self.admin)
        retry_notification(item.pk, self.admin, current['preview_token'])
        process_outbox()
        self.assertEqual(mail.outbox[0].to, ['nouveau@example.invalid'])

    @override_settings(**EMAIL_SETTINGS)
    def test_revision_or_mission_change_cancels_old_delivery(self):
        notify_transport_assignment(self.job.pk)
        OutboundJob.objects.filter(pk=self.job.pk).update(assignment_revision=2)
        with patch('core.outbox_service.deliver_email') as send:
            process_outbox()
        send.assert_not_called()
        self.assertEqual(self.email().state, 'cancelled')

    @override_settings(**EMAIL_SETTINGS)
    def test_explicit_provider_rejection_retries_with_backoff_but_timeout_is_manual(self):
        notify_transport_assignment(self.job.pk)
        now = timezone.now()
        with patch('core.outbox_service.deliver_email', side_effect=DeliveryFailure('smtp_rejected', retryable=True)):
            process_outbox(now=now)
        item = self.email()
        self.assertEqual(item.state, 'pending')
        self.assertGreater(item.next_attempt_at, now)
        with patch('core.outbox_service.deliver_email', side_effect=DeliveryFailure('smtp_acceptance_unknown', uncertain=True)):
            process_outbox(now=item.next_attempt_at + timedelta(seconds=1))
        item.refresh_from_db()
        self.assertEqual(item.state, 'uncertain')
        with self.assertRaises(ValidationError):
            retry_notification(item.pk, self.admin, preview(item, self.admin)['preview_token'])
        with patch('core.outbox_service.deliver_email') as send:
            process_outbox(now=now + timedelta(days=1))
        send.assert_not_called()

    @override_settings(**EMAIL_SETTINGS)
    def test_interrupted_claim_is_not_reclaimed_for_another_automatic_send(self):
        notify_transport_assignment(self.job.pk)
        ExternalNotification.objects.filter(channel='email').update(state='processing', claimed_at=timezone.now()-timedelta(minutes=6))
        with patch('core.outbox_service.deliver_email') as send:
            process_outbox()
        send.assert_not_called()
        self.assertEqual(self.email().state, 'uncertain')

    @override_settings(**EMAIL_SETTINGS)
    def test_client_opt_out_and_expired_review_block_before_any_transport(self):
        notify_transport_assignment(self.job.pk)
        self.client.notify_email = False
        self.client.save(update_fields=['notify_email'])
        with patch('core.outbox_service.deliver_email') as send:
            process_outbox()
        send.assert_not_called()
        self.assertEqual(self.email().blocked_reason, 'client_opt_out')


@skipUnless(connection.vendor == 'postgresql', 'Outbox claims require real PostgreSQL concurrency.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TVM_WHATSAPP_ENABLED=False, **EMAIL_SETTINGS)
class ExternalOutboxConcurrencyTests(TransactionTestCase):
    def test_two_workers_claim_one_notification_and_call_provider_once(self):
        _, _, _, _, _, job = fixture('concurrent')
        notify_transport_assignment(job.pk)
        barrier = Barrier(2)
        def work():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return process_outbox(limit=1)
            finally:
                connections.close_all()
        with patch('core.outbox_service.deliver_email', return_value='') as send, ThreadPoolExecutor(max_workers=2) as pool:
            handled = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(sum(handled), 1)
        send.assert_called_once()
        self.assertEqual(ExternalNotification.objects.get(channel='email').state, 'sent')


@override_settings(**EMAIL_SETTINGS, TVM_WHATSAPP_TOKEN='synthetic-secret-token', TVM_WHATSAPP_PHONE_ID='123456789',
    TVM_WHATSAPP_API_VERSION='v23.0', TVM_WHATSAPP_TEMPLATE='synthetic_logistics', TVM_WHATSAPP_LANGUAGE='fr', TVM_NOTIFICATION_TIMEOUT=10)
class ExternalProviderAdapterTests(SimpleTestCase):
    context = {'subject': 'TVM essai fictif', 'text': 'Message de laboratoire fictif',
               'template_values': ['Affectation fictive', '26-00001', 'CLIENT-FICTIF', 'SN-FICTIF', 'Adresse fictive']}

    def test_whatsapp_mock_uses_only_graph_host_approved_template_shape_and_bounded_timeout(self):
        with patch('core.outbox_adapters.build_opener') as factory:
            factory.return_value.open.return_value = BytesIO(b'{"messages":[{"id":"wamid.SYNTHETIC"}]}')
            self.assertEqual(deliver_whatsapp('+99912345678', self.context, 'synthetic-key'), 'wamid.SYNTHETIC')
        request = factory.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v23.0/123456789/messages')
        self.assertEqual(factory.return_value.open.call_args.kwargs['timeout'], 10)
        payload = json.loads(request.data)
        self.assertEqual(payload['type'], 'template')
        self.assertEqual(payload['to'], '99912345678')
        self.assertEqual(len(payload['template']['components'][0]['parameters']), 5)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid/'))

    def test_whatsapp_server_or_unstructured_proxy_errors_are_uncertain_not_automatic_retry(self):
        for status, body in ((502, b'upstream error'), (429, b'not-provider-json')):
            with self.subTest(status=status), patch('core.outbox_adapters.build_opener') as factory:
                factory.return_value.open.side_effect = HTTPError('https://graph.facebook.com/', status, 'synthetic', None, BytesIO(body))
                with self.assertRaises(DeliveryFailure) as error:
                    deliver_whatsapp('+99912345678', self.context, 'synthetic-key')
                self.assertTrue(error.exception.uncertain)
                self.assertFalse(error.exception.retryable)
                self.assertNotIn('synthetic-secret-token', str(error.exception))

    def test_whatsapp_explicit_rate_limit_is_retryable_without_claiming_acceptance(self):
        with patch('core.outbox_adapters.build_opener') as factory:
            factory.return_value.open.side_effect = HTTPError('https://graph.facebook.com/', 429, 'synthetic', None, BytesIO(b'{"error":{"code":4}}'))
            with self.assertRaises(DeliveryFailure) as error:
                deliver_whatsapp('+99912345678', self.context, 'synthetic-key')
        self.assertTrue(error.exception.retryable)
        self.assertFalse(error.exception.uncertain)

    def test_smtp_explicit_temporary_refusal_and_disconnection_have_distinct_retry_policies(self):
        for exception, retryable, uncertain in ((smtplib.SMTPDataError(450, b'synthetic'), True, False),
                                                (smtplib.SMTPServerDisconnected('synthetic-secret-token'), False, True)):
            with self.subTest(exception=type(exception).__name__), patch('core.outbox_adapters.get_connection') as factory:
                factory.return_value.send_messages.side_effect = exception
                with self.assertRaises(DeliveryFailure) as error:
                    deliver_email('responsable@example.invalid', self.context, 'synthetic-key')
                self.assertEqual(error.exception.retryable, retryable)
                self.assertEqual(error.exception.uncertain, uncertain)
                self.assertNotIn('synthetic-secret-token', str(error.exception))
