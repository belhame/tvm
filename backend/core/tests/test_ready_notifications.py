"""Ready notifications use real transitions, current permissions and no provider."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.disposition_workflow import mark_repaired, reset_disposition
from core.exchange_models import ExchangeProcess
from core.exchange_workflow import prepare_exchange, ready_exchange, validate_exchange
from core.logistics_models import OutboundJob
from core.models import Client, Equipment, OperationEvent, ServiceRequest, User
from core.notification_models import InAppNotification
from core.notification_service import notification_payload
from core.ready_notifications import ASSIGNMENT_EVENT, READY_EVENT, notify_outbound_assignment, notify_ready_availability


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReadyNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Centre disponibilités fictif', tax_id='PRIVATE_READY_TAX',
            address='PRIVATE_READY_ADDRESS', phone='PRIVATE_READY_PHONE', email='private-ready@example.invalid',
            contact_name='PRIVATE_READY_CONTACT', notes='PRIVATE_READY_CLIENT_NOTES')
        cls.manager = User.objects.create_user('ready-notice-manager', role='manager')
        cls.admin = User.objects.create_user('ready-notice-admin', role='admin')
        cls.courier = User.objects.create_user('ready-notice-courier', role='courier')
        cls.other_courier = User.objects.create_user('ready-notice-other-courier', role='courier')
        cls.disabled = User.objects.create_user('ready-notice-disabled', role='courier', is_active=False)
        cls.external = User.objects.create_user('ready-notice-external', role='courier', courier_kind='client', client=cls.company)
        cls.customer = User.objects.create_user('ready-notice-client', role='client', client=cls.company)
        cls.technician = User.objects.create_user('ready-notice-technician', role='technician')
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='READY-NOTICE-FICTIVE-001', model='Modèle fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.courier)

    def record(self, *, status='testing'):
        return ServiceRequest.objects.create(equipment=self.unit, subject='PRIVATE_READY_SUBJECT', status=status,
            description='PRIVATE_READY_DESCRIPTION', client_reference='000-CLIENT-READY', accessories='PRIVATE_READY_ACCESSORIES')

    def repair(self, record):
        data = {'diagnosis': 'PRIVATE_READY_DIAGNOSIS', 'tests_passed': True, 'tested_on': timezone.localdate()}
        with self.captureOnCommitCallbacks(execute=True):
            result = mark_repaired(record.pk, data, actor=self.manager)
        return result

    def notices(self):
        return InAppNotification.objects.filter(kind=InAppNotification.Kind.LOGISTICS, payload__event=READY_EVENT)

    def own_notice(self, record):
        return self.notices().get(recipient=self.courier, service_request=record)

    def test_real_repair_notifies_all_active_tvm_couriers_and_admin_only_without_provider(self):
        record = self.record()
        with (patch('core.outbox_service.deliver_email') as email,
              patch('core.outbox_service.deliver_whatsapp') as whatsapp):
            self.repair(record)
            email.assert_not_called()
            whatsapp.assert_not_called()
        self.assertEqual(set(self.notices().values_list('recipient_id', flat=True)),
                         {self.courier.pk, self.other_courier.pk, self.admin.pk})
        self.assertFalse(self.notices().filter(recipient__in=[self.disabled, self.external, self.customer, self.technician, self.manager]).exists())
        from core.outbox_models import ExternalNotification
        self.assertFalse(ExternalNotification.objects.exists())
        notice = self.own_notice(record)
        payload = notification_payload(notice, self.courier)
        self.assertEqual(payload['target'], 'courier_ready_queue')
        self.assertTrue(payload['details']['available'])
        self.assertEqual(payload['details']['request']['serial_number'], self.unit.serial_number)
        self.assertEqual(payload['details']['request']['client_reference'], '000-CLIENT-READY')
        for private in ('PRIVATE_READY_', self.company.email):
            self.assertNotIn(private, str(payload))
        self.assertEqual(payload['channel'], 'in_app')

    def test_exchange_needs_real_validation_and_ready_before_replacement_is_notified(self):
        record = self.record(status='exchange')
        with self.captureOnCommitCallbacks(execute=True):
            prepare_exchange(record.pk, {'replacement_serial_number': 'READY-NOTICE-REPLACEMENT', 'replacement_model': 'Remplacement fictif'}, actor=self.manager)
        self.assertFalse(self.notices().exists())
        with self.captureOnCommitCallbacks(execute=True):
            validate_exchange(record.pk, actor=self.manager)
        self.assertFalse(self.notices().exists())
        with self.captureOnCommitCallbacks(execute=True):
            ready_exchange(record.pk, actor=self.manager)
        payload = notification_payload(self.own_notice(record), self.courier)
        self.assertTrue(payload['details']['available'])
        self.assertEqual(payload['details']['request']['serial_number'], 'READY-NOTICE-REPLACEMENT')
        self.assertNotEqual(payload['details']['request']['equipment'], self.unit.pk)
        with self.captureOnCommitCallbacks(execute=True):
            ready_exchange(record.pk, actor=self.manager)
        self.assertEqual(self.notices().count(), 3)

    def test_replay_same_event_is_idempotent_and_second_true_transition_has_its_own_notice(self):
        record = self.repair(self.record())
        first = self.own_notice(record)
        self.assertEqual(notify_ready_availability(first.payload['readiness_event']), 0)
        self.repair(record)
        self.assertEqual(self.notices().count(), 3)
        with self.captureOnCommitCallbacks(execute=True):
            reset_disposition(record.pk, actor=self.manager, reason='Reprendre les tests fictifs')
        self.repair(record)
        self.assertEqual(self.notices().count(), 6)
        self.assertFalse(notification_payload(first, self.courier)['details']['available'])
        newest = self.notices().filter(recipient=self.courier).order_by('-pk').first()
        self.assertTrue(notification_payload(newest, self.courier)['details']['available'])

    def test_rollback_and_ready_then_revoked_before_commit_never_emit_a_notice(self):
        record = self.record()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                mark_repaired(record.pk, {'diagnosis': 'Tests fictifs', 'tests_passed': True, 'tested_on': timezone.localdate()}, actor=self.manager)
                raise RuntimeError('Synthetic rollback')
        self.assertFalse(self.notices().exists())
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            mark_repaired(record.pk, {'diagnosis': 'Tests fictifs', 'tests_passed': True, 'tested_on': timezone.localdate()}, actor=self.manager)
            reset_disposition(record.pk, actor=self.manager, reason='Reprise avant fin transaction')
        self.assertFalse(self.notices().exists())

    def test_plain_get_legacy_baseline_and_bulk_reference_updates_do_not_write_notices(self):
        record = self.record()
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        with self.captureOnCommitCallbacks(execute=True):
            baseline = OperationEvent.objects.create(equipment=self.unit, service_request=record, kind='baseline',
                source='baseline', status_after='ready_for_delivery')
            migrated = OperationEvent.objects.create(equipment=self.unit, service_request=record, kind='status_changed',
                source='baseline', status_before='testing', status_after='ready_for_delivery')
        self.assertEqual(notify_ready_availability(baseline.pk), 0)
        self.assertEqual(notify_ready_availability(migrated.pk), 0)
        before = InAppNotification.objects.count(), OperationEvent.objects.count()
        for _ in range(2):
            response = self.api.get('/api/logistics/notifications/')
            self.assertEqual(response.status_code, 200)
        self.assertEqual((InAppNotification.objects.count(), OperationEvent.objects.count()), before)
        self.assertFalse(self.notices().exists())

    def test_reference_event_cannot_turn_an_unverified_legacy_ready_row_into_a_new_alert(self):
        record = self.record()
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        with self.captureOnCommitCallbacks(execute=True):
            event = OperationEvent.objects.create(equipment=self.unit, service_request=record, kind='status_changed',
                status_before='testing', status_after='ready_for_delivery')
        self.assertEqual(notify_ready_availability(event.pk), 0)
        self.assertFalse(self.notices().exists())

    def test_unready_or_delivered_notice_hides_old_metadata_and_does_not_restore_availability(self):
        record = self.repair(self.record())
        notice = self.own_notice(record)
        with self.captureOnCommitCallbacks(execute=True):
            reset_disposition(record.pk, actor=self.manager, reason='Reprise fictive')
        payload = notification_payload(notice, self.courier)
        self.assertIsNone(payload['target'])
        self.assertIsNone(payload['service_request'])
        self.assertIsNone(payload['details']['request'])
        self.assertNotIn(self.unit.serial_number, str(payload))
        self.assertNotIn(self.company.name, str(payload))
        record = self.repair(record)
        notice = self.notices().filter(recipient=self.courier, service_request=record).latest('pk')
        # Historical proof fixture: a prior handoff remains excluded even while
        # the financial dossier still has its ready status.
        OutboundJob.objects.create(service_request=record, client=self.company, delivery_equipment=self.unit,
            kind='delivery', assigned_courier=self.courier, assigned_by=self.manager, assigned_at=timezone.now(),
            active=False, handed_over_at=timezone.now(), handed_over_by=self.courier, recipient_name='Destinataire fictif')
        self.assertFalse(notification_payload(notice, self.courier)['details']['available'])

    def test_role_conversion_excludes_old_notice_from_inbox_and_read_endpoint(self):
        record = self.repair(self.record())
        notice = self.own_notice(record)
        self.courier.courier_kind = 'client'
        self.courier.client = self.company
        self.courier.save()
        self.api.force_authenticate(self.courier)
        self.assertEqual(self.api.get('/api/logistics/notifications/').data['results'], [])
        self.assertEqual(self.api.patch(f'/api/logistics/notifications/{notice.pk}/read/', {'read': True}, format='json').status_code, 404)
        self.assertFalse(notification_payload(notice, self.courier)['details']['available'])
        self.assertNotIn(self.company.name, str(notification_payload(notice, self.courier)))

    def test_invalid_canonical_replacement_never_reuses_original_identity(self):
        record = self.record(status='exchange')
        prepare_exchange(record.pk, {'replacement_serial_number': 'READY-BAD-REPLACEMENT', 'replacement_model': 'Fictif'}, actor=self.manager)
        validate_exchange(record.pk, actor=self.manager)
        with self.captureOnCommitCallbacks(execute=True):
            ready_exchange(record.pk, actor=self.manager)
        notice = self.own_notice(record)
        ExchangeProcess.objects.filter(service_request=record).update(replacement_model='Incohérence historique fictive')
        self.assertFalse(notification_payload(notice, self.courier)['details']['available'])
        self.assertEqual(notify_ready_availability(notice.payload['readiness_event']), 0)

    def test_inbox_and_acknowledgement_remain_recipient_scoped_and_read_only_on_get(self):
        record = self.repair(self.record())
        own = self.own_notice(record)
        foreign = self.notices().get(recipient=self.other_courier)
        before = InAppNotification.objects.count(), own.read_at
        response = self.api.get('/api/logistics/notifications/')
        self.assertEqual([item['id'] for item in response.data['results']], [own.pk])
        self.assertEqual((InAppNotification.objects.count(), own.read_at), before)
        self.assertEqual(self.api.patch(f'/api/logistics/notifications/{foreign.pk}/read/', {'read': True}, format='json').status_code, 404)
        first = self.api.patch(f'/api/logistics/notifications/{own.pk}/read/', {'read': True}, format='json')
        second = self.api.patch(f'/api/logistics/notifications/{own.pk}/read/', {'read': True}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['read_at'], second.data['read_at'])


    def test_manual_assignment_is_private_revisioned_and_distinct_from_general_availability(self):
        from core.logistics_service import assign_outbound
        record = self.repair(self.record())
        with self.captureOnCommitCallbacks(execute=True):
            job = assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.courier.pk})
        assigned = InAppNotification.objects.get(recipient=self.courier, payload__event=ASSIGNMENT_EVENT)
        self.assertEqual(InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT).count(), 1)
        self.assertEqual(notify_outbound_assignment(job.pk, job.assignment_revision), 0)
        payload = notification_payload(assigned, self.courier)
        self.assertEqual(payload['target'], 'courier_missions')
        self.assertEqual(payload['title'], 'Livraison affectée')
        self.assertEqual(payload['details']['job']['id'], job.pk)
        self.assertFalse(payload['details']['job']['accepted'])
        self.assertEqual(self.notices().count(), 3)
        for private in ('PRIVATE_READY_', self.company.email):
            self.assertNotIn(private, str(payload))
        with self.captureOnCommitCallbacks(execute=True):
            again = assign_outbound(self.manager, {'courier': self.courier.pk}, pk=job.pk)
        self.assertEqual(again.assignment_revision, job.assignment_revision)
        self.assertEqual(InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            changed = assign_outbound(self.manager, {'courier': self.other_courier.pk}, pk=job.pk)
        self.assertEqual(InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT).count(), 2)
        old = notification_payload(assigned, self.courier)
        self.assertFalse(old['details']['available'])
        self.assertIsNone(old['details']['job'])
        self.assertNotIn(self.unit.serial_number, str(old))
        self.assertNotIn(self.other_courier.username, str(old))
        self.assertEqual(changed.assignment_revision, job.assignment_revision + 1)

    def test_automatic_internal_assignment_notifies_designated_driver_without_notifying_client_driver(self):
        self.company.internal_courier = self.courier
        self.company.save(update_fields=['internal_courier'])
        record = self.repair(self.record())
        assigned = InAppNotification.objects.get(recipient=self.courier, payload__event=ASSIGNMENT_EVENT)
        self.assertEqual(assigned.service_request_id, record.pk)
        self.assertFalse(InAppNotification.objects.filter(recipient=self.other_courier, payload__event=ASSIGNMENT_EVENT).exists())
        self.assertFalse(InAppNotification.objects.filter(recipient=self.external, payload__event__in=[READY_EVENT, ASSIGNMENT_EVENT]).exists())
        self.assertEqual(self.notices().count(), 3)

    def test_external_assignment_and_self_claim_do_not_emit_a_second_private_notice(self):
        from core.courier_dispatch import claim_ready
        from core.logistics_service import assign_outbound
        record = self.repair(self.record())
        with self.captureOnCommitCallbacks(execute=True):
            assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.external.pk})
        self.assertFalse(InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT).exists())
        other_unit = Equipment.objects.create(client=self.company, serial_number='READY-NOTICE-CLAIM-002', model='Modèle fictif')
        other_record = ServiceRequest.objects.create(equipment=other_unit, subject='Tests fictifs', status='testing')
        self.repair(other_record)
        with self.captureOnCommitCallbacks(execute=True):
            claim_ready(self.courier, other_record.pk, 0)
        self.assertFalse(InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT).exists())

    def test_reassignment_before_commit_notifies_only_the_final_recipient(self):
        from core.logistics_service import assign_outbound
        record = self.repair(self.record())
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            job = assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.courier.pk})
            job = assign_outbound(self.manager, {'courier': self.other_courier.pk}, pk=job.pk)
        assigned = InAppNotification.objects.filter(payload__event=ASSIGNMENT_EVENT)
        self.assertEqual(assigned.count(), 1)
        self.assertEqual(assigned.get().recipient_id, self.other_courier.pk)
        self.assertEqual(assigned.get().payload['revision'], job.assignment_revision)

    def test_private_assignment_after_acceptance_stays_current_but_cancellation_hides_it(self):
        from core.courier_dispatch import accept_outbound
        from core.logistics_service import assign_outbound, cancel_outbound
        record = self.repair(self.record())
        with self.captureOnCommitCallbacks(execute=True):
            job = assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.courier.pk})
        assigned = InAppNotification.objects.get(recipient=self.courier, payload__event=ASSIGNMENT_EVENT)
        accept_outbound(self.courier, job.pk, job.assignment_revision, True)
        payload = notification_payload(assigned, self.courier)
        self.assertTrue(payload['details']['job']['accepted'])
        self.assertEqual(notify_outbound_assignment(job.pk, job.assignment_revision), 0)
        with self.captureOnCommitCallbacks(execute=True):
            cancel_outbound(self.manager, job.pk, {'reason': 'Créneau fictif à revoir'})
        self.assertFalse(notification_payload(assigned, self.courier)['details']['available'])


@skipUnless(connection.vendor == 'postgresql', 'Ready notice deduplication uses the PostgreSQL unique constraint.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReadyNotificationConcurrencyTests(TransactionTestCase):
    def test_concurrent_retries_of_one_committed_transition_have_one_notice_per_recipient(self):
        company = Client.objects.create(name='Concurrence disponibilités fictive')
        manager = User.objects.create_user('ready-concurrent-manager', role='manager')
        courier = User.objects.create_user('ready-concurrent-courier', role='courier')
        unit = Equipment.objects.create(client=company, serial_number='READY-CONCURRENT-FICTIVE', model='Modèle fictif')
        record = ServiceRequest.objects.create(equipment=unit, subject='Tests fictifs', status='testing')
        mark_repaired(record.pk, {'diagnosis': 'Tests fictifs réussis', 'tests_passed': True, 'tested_on': timezone.localdate()}, actor=manager)
        event_id = record.operation_events.get(kind='status_changed', status_after='ready_for_delivery').pk
        InAppNotification.objects.all().delete()
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return notify_ready_availability(event_id)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = [future.result(timeout=30) for future in [pool.submit(worker) for _ in range(2)]]
        self.assertEqual(sum(counts), 1)
        self.assertEqual(InAppNotification.objects.filter(recipient=courier, payload__event=READY_EVENT).count(), 1)
