"""Shared readiness exposes operational facts, never an implicit assignment."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.test import APIClient

from core.courier_dispatch import DispatchConflict, accept_outbound, claim_ready, outbound_is_accepted, ready_queue
from core.logistics_payloads import outbound_payload
from core.logistics_service import assign_outbound, cancel_outbound, handoff
from core.models import Client, Equipment, OperationEvent, OutboundJob, ServiceRequest, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CourierDispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('dispatch-manager', role='manager')
        cls.courier = User.objects.create_user('dispatch-tvm-one', role='courier', courier_kind='internal')
        cls.other_courier = User.objects.create_user('dispatch-tvm-two', role='courier', courier_kind='internal')
        cls.company = Client.objects.create(name='Client livraison fictif A', address='Adresse fictive A')
        cls.other_company = Client.objects.create(name='Client livraison fictif B')
        cls.external = User.objects.create_user('dispatch-external', role='courier', courier_kind='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='DISPATCH-LAB-A', model='Modèle fictif A')
        cls.other_unit = Equipment.objects.create(client=cls.other_company, serial_number='DISPATCH-LAB-B', model='Modèle fictif B')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='Ancien dossier prêt fictif A', client_reference='000-CLIENT-A')
        cls.other_record = ServiceRequest.objects.create(equipment=cls.other_unit, subject='Ancien dossier prêt fictif B')
        # Honest simulation of existing ready rows, without inventing tests or
        # a new technical transition to obtain them.
        ServiceRequest.objects.filter(pk__in=[cls.record.pk, cls.other_record.pk]).update(status='ready_for_delivery')

    def job(self, courier=None):
        return assign_outbound(self.manager, {'service_request': self.record.pk, 'courier': (courier or self.courier).pk})

    def test_internal_couriers_see_all_clients_without_creating_jobs(self):
        rows = ready_queue(self.courier)
        self.assertEqual({row['client']['id'] for row in rows}, {self.company.pk, self.other_company.pk})
        self.assertTrue(all(row['can_claim'] and row['expected_revision'] == 0 for row in rows))
        self.assertFalse(OutboundJob.objects.exists())
        self.assertNotIn('diagnosis', str(rows))
        self.assertNotIn('contact_phone', str(rows))
        self.assertNotIn('invoice', str(rows))

    def test_external_courier_cannot_see_or_probe_shared_queue(self):
        with self.assertRaises(PermissionDenied):
            ready_queue(self.external)
        for identifier in (self.record.pk, self.other_record.pk, 999999):
            with self.assertRaises(PermissionDenied):
                claim_ready(self.external, identifier, 0)

    def test_claim_assigns_and_accepts_atomically_without_handoff(self):
        job = claim_ready(self.courier, self.record.pk, 0)
        self.assertEqual(job.assigned_courier_id, self.courier.pk)
        self.assertTrue(outbound_is_accepted(job))
        self.assertEqual(job.accepted_revision, job.assignment_revision)
        self.assertIsNone(job.handed_over_at)
        self.assertEqual(job.delivery_equipment_id, self.unit.pk)
        self.assertEqual(job.delivery_address, self.company.address)
        self.assertTrue(self.record.operation_events.filter(kind='outbound_claimed', actor=self.courier).exists())
        self.assertTrue(self.record.operation_events.filter(kind='outbound_accepted', actor=self.courier).exists())
        row = next(item for item in ready_queue(self.other_courier) if item['id'] == self.record.pk)
        self.assertEqual(row['routing_status'], 'reserved')
        self.assertFalse(row['can_claim'])

    def test_reserved_assignment_cannot_be_stolen(self):
        job = self.job(self.other_courier)
        for actor in (self.courier, self.other_courier):
            with self.assertRaises(DispatchConflict):
                claim_ready(actor, self.record.pk, job.assignment_revision)
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.other_courier.pk)
        self.assertIsNone(job.accepted_at)

    def test_manager_assignment_waits_for_confirmation_and_cancel_does_not_confirm(self):
        job = self.job()
        self.assertFalse(outbound_is_accepted(job))
        self.assertFalse(outbound_payload(job, self.courier)['can_handoff'])
        self.assertTrue(outbound_payload(job, self.courier)['can_accept'])
        unchanged = accept_outbound(self.courier, job.pk, job.assignment_revision, False)
        self.assertIsNone(unchanged.accepted_at)
        with self.assertRaises(PermissionDenied):
            handoff(self.courier, job.pk, {'recipient_name': 'Destinataire fictif'})
        accepted = accept_outbound(self.courier, job.pk, job.assignment_revision, True)
        first_timestamp = accepted.accepted_at
        replay = accept_outbound(self.courier, job.pk, job.assignment_revision, True)
        self.assertEqual(replay.accepted_at, first_timestamp)
        self.assertEqual(self.record.operation_events.filter(kind='outbound_accepted').count(), 1)
        with self.assertRaises(DispatchConflict):
            handoff(self.courier, job.pk, {'recipient_name': 'Destinataire fictif', 'expected_revision': job.assignment_revision + 1})
        handoff(self.courier, job.pk, {'recipient_name': 'Destinataire fictif', 'expected_revision': job.assignment_revision})
        job.refresh_from_db()
        self.assertEqual(job.accepted_at, first_timestamp)
        self.assertIsNotNone(job.handed_over_at)

    def test_external_accepts_only_own_company_mission(self):
        job = self.job(self.external)
        with self.assertRaises(NotFound):
            accept_outbound(self.other_courier, job.pk, job.assignment_revision, True)
        accepted = accept_outbound(self.external, job.pk, job.assignment_revision, True)
        self.assertTrue(outbound_is_accepted(accepted))
        self.assertTrue(outbound_payload(accepted, self.external)['can_handoff'])

    def test_reassignment_and_address_change_invalidate_old_acceptance(self):
        job = self.job()
        accept_outbound(self.courier, job.pk, job.assignment_revision, True)
        revised = assign_outbound(self.manager, {'courier': self.courier.pk, 'delivery_address': 'Nouvelle adresse fictive', 'expected_revision': job.assignment_revision}, pk=job.pk)
        self.assertGreater(revised.assignment_revision, job.assignment_revision)
        self.assertFalse(outbound_is_accepted(revised))
        with self.assertRaises(DispatchConflict):
            accept_outbound(self.courier, revised.pk, job.assignment_revision, True)
        accepted = accept_outbound(self.courier, revised.pk, revised.assignment_revision, True)
        revised = assign_outbound(self.manager, {'courier': self.other_courier.pk, 'expected_revision': accepted.assignment_revision}, pk=job.pk)
        self.assertIsNone(revised.accepted_at)
        with self.assertRaises(NotFound):
            accept_outbound(self.courier, revised.pk, revised.assignment_revision, True)

    def test_cancellation_releases_claim_and_requires_a_new_confirmation(self):
        job = claim_ready(self.courier, self.record.pk, 0)
        old_revision = job.assignment_revision
        cancelled = cancel_outbound(self.manager, job.pk, {'reason': 'Changement de tournée fictive'})
        self.assertGreater(cancelled.assignment_revision, old_revision)
        self.assertIsNone(cancelled.accepted_at)
        row = next(item for item in ready_queue(self.other_courier) if item['id'] == self.record.pk)
        self.assertTrue(row['can_claim'])
        with self.assertRaises(DispatchConflict):
            claim_ready(self.other_courier, self.record.pk, old_revision)
        taken = claim_ready(self.other_courier, self.record.pk, row['expected_revision'])
        self.assertEqual(taken.pk, job.pk)
        self.assertTrue(outbound_is_accepted(taken))

    def test_manager_handoff_does_not_manufacture_courier_acceptance(self):
        job = self.job()
        handed = handoff(self.manager, job.pk, {'recipient_name': 'Destinataire fictif'})
        self.assertIsNotNone(handed.handed_over_at)
        self.assertIsNone(handed.accepted_at)
        self.assertNotIn(self.record.pk, {row['id'] for row in ready_queue(self.courier)})

    def test_confirmation_metadata_cannot_be_forged_and_database_requires_revision(self):
        job = self.job()
        job.accepted_at = timezone.now()
        job.accepted_by = self.courier
        job.accepted_revision = job.assignment_revision
        with self.assertRaises(ValidationError):
            job.save(update_fields=['accepted_at', 'accepted_by', 'accepted_revision'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            OutboundJob.objects.filter(pk=job.pk).update(accepted_at=timezone.now(), accepted_by=self.courier, accepted_revision=None)

    def test_direct_administrative_reassignment_resets_acceptance(self):
        job = claim_ready(self.courier, self.record.pk, 0)
        previous_revision = job.assignment_revision
        job.assigned_courier = self.other_courier
        job.save(update_fields=['assigned_courier'])
        job.refresh_from_db()
        self.assertEqual(job.assignment_revision, previous_revision + 1)
        self.assertIsNone(job.accepted_at)
        self.assertIsNone(job.accepted_by_id)
        self.assertIsNone(job.accepted_revision)

    def test_deactivated_actor_is_rechecked_before_claim_or_accept(self):
        job = self.job()
        User.objects.filter(pk=self.courier.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            claim_ready(self.courier, self.other_record.pk, 0)
        with self.assertRaises(PermissionDenied):
            accept_outbound(self.courier, job.pk, job.assignment_revision, True)

    def test_stale_claim_and_strict_revision_are_rejected(self):
        with self.assertRaises(DispatchConflict):
            claim_ready(self.courier, self.record.pk, 1)
        for value in (True, 1.0, '0', -1):
            with self.assertRaises(ValidationError):
                claim_ready(self.courier, self.record.pk, value)

    def test_claim_rolls_back_assignment_when_confirmation_event_fails(self):
        with patch('core.courier_dispatch.append_event', side_effect=RuntimeError('Synthetic event failure')):
            with self.assertRaises(RuntimeError):
                claim_ready(self.courier, self.record.pk, 0)
        self.assertFalse(OutboundJob.objects.filter(service_request=self.record).exists())

    def test_queue_query_count_does_not_grow_for_each_client(self):
        with self.assertNumQueries(3):
            rows = ready_queue(self.courier)
        self.assertEqual(len(rows), 2)


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL requis pour vérifier les vrais verrous concurrents.')
class ConcurrentCourierDispatchTests(TransactionTestCase):
    def setUp(self):
        company = Client.objects.create(name='Client concurrence livraison fictif')
        unit = Equipment.objects.create(client=company, serial_number='DISPATCH-CONCURRENT-LAB', model='Modèle de laboratoire')
        self.record = ServiceRequest.objects.create(equipment=unit, subject='Ancien prêt concurrent fictif')
        ServiceRequest.objects.filter(pk=self.record.pk).update(status='ready_for_delivery')
        self.first = User.objects.create_user('dispatch-concurrent-a', role='courier', courier_kind='internal')
        self.second = User.objects.create_user('dispatch-concurrent-b', role='courier', courier_kind='internal')

    def test_two_couriers_cannot_claim_the_same_unit(self):
        barrier = Barrier(2)
        identifier = self.record.pk
        def take(actor_id):
            close_old_connections()
            try:
                actor = User.objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                try:
                    return ('ok', claim_ready(actor, identifier, 0).pk)
                except DispatchConflict:
                    return ('conflict', None)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(take, [self.first.pk, self.second.pk]))
        self.assertEqual(sorted(item[0] for item in result), ['conflict', 'ok'])
        self.assertEqual(OutboundJob.objects.filter(service_request=self.record, active=True).count(), 1)
        self.assertEqual(self.record.operation_events.filter(kind='outbound_accepted').count(), 1)
