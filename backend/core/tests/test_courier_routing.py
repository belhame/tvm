"""Courier routing decisions and their concurrency, with fictional companies."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core import logistics_service as logistics
from core.disposition_workflow import mark_nonrepairable, mark_repaired
from core.exchange_workflow import prepare_exchange, ready_exchange, validate_exchange
from core.models import Client, Equipment, OperationEvent, OutboundJob, ServiceRequest, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CourierRoutingTests(TestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Centre routage fictif')
        self.manager = User.objects.create_user('routing-lab-manager', role='manager')
        self.internal = User.objects.create_user('routing-lab-internal', role='courier')
        self.external = User.objects.create_user('routing-lab-external', role='courier', courier_kind='client', client=self.company)
        self.unit = Equipment.objects.create(client=self.company, serial_number='ROUTING-LAB-UNIT', model='Onduleur fictif')
        self.company.default_courier = self.external
        self.company.internal_courier = self.internal
        self.company.save()

    def new_request(self):
        return ServiceRequest.objects.create(equipment=self.unit, subject='Qualification fictive', status='testing')

    def repair(self, record):
        return mark_repaired(record.pk, {'diagnosis': 'Tests fictifs réussis', 'tests_passed': True, 'tested_on': timezone.localdate()}, actor=self.manager)

    def test_new_repair_uses_external_default_and_replay_keeps_one_automatic_assignment(self):
        record = self.new_request()
        self.repair(record)
        job = OutboundJob.objects.get(service_request=record)
        self.assertEqual(job.assigned_courier_id, self.external.pk)
        self.assertEqual(job.assignment_mode, 'automatic')
        self.assertEqual(job.routing_source, 'default_courier')
        self.assertIsNone(job.assigned_by_id)  # Direct model/service call records System, never a fabricated actor.
        self.repair(record)
        self.assertEqual(OutboundJob.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.filter(service_request=record, kind='outbound_auto_assigned').count(), 1)

    def test_inactive_default_falls_back_to_internal_without_mutating_client_configuration(self):
        self.external.is_active = False
        self.external.save(update_fields=['is_active'])
        record = self.new_request()
        self.repair(record)
        job = OutboundJob.objects.get(service_request=record)
        self.assertEqual(job.assigned_courier_id, self.internal.pk)
        self.assertEqual(job.routing_source, 'internal_courier')
        self.company.refresh_from_db()
        self.assertEqual(self.company.default_courier_id, self.external.pk)

    def test_validated_exchange_auto_assignment_uses_the_canonical_replacement(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Échange fictif', status='exchange')
        prepare_exchange(record.pk, {'replacement_serial_number': 'ROUTING-LAB-REPLACEMENT', 'replacement_model': 'Remplacement fictif'}, actor=self.manager)
        validate_exchange(record.pk, actor=self.manager)
        ready = ready_exchange(record.pk, actor=self.manager)
        job = OutboundJob.objects.get(service_request=record)
        self.assertEqual(job.delivery_equipment_id, ready.exchange_process.replacement_equipment_id)
        self.assertNotEqual(job.delivery_equipment_id, self.unit.pk)
        self.assertEqual(job.assigned_courier_id, self.external.pk)

    def test_reconcile_only_reassigns_automatic_jobs_when_explicit_and_preserves_manual_and_proofs(self):
        record = self.new_request()
        self.repair(record)
        job = OutboundJob.objects.get(service_request=record)
        self.company.default_courier = None
        self.company.save(update_fields=['default_courier'])
        result = logistics.reconcile_dispatch(self.manager, client_id=self.company.pk)
        self.assertEqual(result['skipped'], [record.pk])
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.external.pk)
        result = logistics.reconcile_dispatch(self.manager, client_id=self.company.pk, reassign_automatic=True)
        self.assertEqual(result['reassigned'], [job.pk])
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.internal.pk)
        self.assertEqual(job.assignment_revision, 2)
        logistics.assign_outbound(self.manager, {'courier': self.external.pk}, pk=job.pk)
        result = logistics.reconcile_dispatch(self.manager, client_id=self.company.pk, reassign_automatic=True)
        self.assertEqual(result['skipped'], [record.pk])
        job.refresh_from_db()
        self.assertEqual(job.assignment_mode, 'manual')
        logistics.handoff(self.external, job.pk, {'recipient_name': 'Destinataire fictif'})
        proof = OutboundJob.objects.get(pk=job.pk).handed_over_at
        logistics.reconcile_dispatch(self.manager, client_id=self.company.pk, reassign_automatic=True)
        job.refresh_from_db()
        self.assertEqual(job.handed_over_at, proof)
        self.assertEqual(job.assigned_courier_id, self.external.pk)

    def test_manual_assignment_exact_retry_does_not_create_a_revision_or_notification_event(self):
        record = self.new_request()
        self.repair(record)
        job = OutboundJob.objects.get(service_request=record)
        job = logistics.assign_outbound(self.manager, {'courier': self.internal.pk}, pk=job.pk)
        revision, assigned_at = job.assignment_revision, job.assigned_at
        retry = logistics.assign_outbound(self.manager, {'courier': self.internal.pk}, pk=job.pk)
        self.assertEqual(retry.assignment_revision, revision)
        self.assertEqual(retry.assigned_at, assigned_at)
        self.assertEqual(OperationEvent.objects.filter(service_request=record, kind='outbound_assigned').count(), 1)

    def test_nonrepairable_return_is_not_automatically_classified_as_a_ready_delivery(self):
        record = self.new_request()
        mark_nonrepairable(record.pk, {'diagnosis': 'Diagnostic fictif non réparable'}, actor=self.manager)
        self.assertFalse(OutboundJob.objects.exists())
        self.assertEqual(logistics.reconcile_dispatch(self.manager)['created'], [])

    def test_missing_referents_keep_ready_without_a_job_and_get_payload_does_not_write(self):
        self.company.default_courier = self.company.internal_courier = None
        self.company.save()
        record = self.new_request()
        self.repair(record)
        from core.logistics_payloads import dispatch_candidates
        before = OperationEvent.objects.count()
        rows = dispatch_candidates(self.manager)
        self.assertEqual(rows[0]['routing_status'], 'unassigned')
        self.assertIsNone(rows[0]['recommended_courier'])
        self.assertFalse(OutboundJob.objects.exists())
        self.assertEqual(OperationEvent.objects.count(), before)
        record.refresh_from_db()
        self.assertEqual(record.status, 'ready_for_delivery')

    def test_end_customer_pickup_keeps_paying_center_while_receipt_records_final_customer(self):
        customer = User.objects.create_user('routing-lab-client', role='client', client=self.company)
        pickup = logistics.create_pickup(customer, {'request_key': uuid4(), 'equipment': self.unit.pk,
            'pickup_scope': 'end_customer', 'end_customer_name': 'Site final fictif', 'pickup_address': 'Adresse finale fictive',
            'contact_name': 'Contact final fictif', 'fault_description': 'Panne fictive', 'client_reference': '000-FINAL-CLIENT'})
        logistics.assign_pickup(self.manager, pickup.pk, {'courier': self.internal.pk})
        logistics.collect_pickup(self.internal, pickup.pk)
        receipt = logistics.receive(self.internal, {'request_key': uuid4(), 'serial_number': self.unit.serial_number, 'client': self.company.pk, 'pickup': pickup.pk})
        self.assertEqual(receipt.service_request.end_customer, 'Site final fictif')
        self.assertEqual(receipt.service_request.equipment.client_id, self.company.pk)
        self.assertEqual(receipt.service_request.contact_name, 'Contact final fictif')
        self.assertEqual(receipt.service_request.client_reference, '000-FINAL-CLIENT')
        self.assertEqual(Client.objects.count(), 1)


@skipUnless(connection.vendor == 'postgresql', 'Routing concurrency requires PostgreSQL row locks.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CourierRoutingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Concurrence routage fictive')
        self.other = Client.objects.create(name='Autre concurrence fictive')
        self.manager = User.objects.create_user('route-concurrent-manager', role='manager')
        self.external = User.objects.create_user('route-concurrent-external', role='courier', courier_kind='client', client=self.company)
        self.company.default_courier = self.external
        self.company.save()
        self.unit = Equipment.objects.create(client=self.company, serial_number='ROUTE-CONCURRENT-LAB', model='Onduleur fictif')
        self.record = ServiceRequest.objects.create(equipment=self.unit, subject='Ancien prêt fictif')
        ServiceRequest.objects.filter(pk=self.record.pk).update(status='ready_for_delivery')

    def worker(self, callback):
        close_old_connections()
        try:
            return callback()
        finally:
            connections.close_all()

    def test_parallel_reconciliation_creates_one_job_and_one_assignment_revision(self):
        barrier = Barrier(2)
        def reconcile():
            barrier.wait(timeout=10)
            job = logistics.auto_assign_ready(self.record.pk)
            return job.pk if job else None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=30) for future in [pool.submit(self.worker, reconcile) for _ in range(2)]]
        self.assertEqual(sum(value is not None for value in results), 1)
        job = OutboundJob.objects.get()
        self.assertEqual(job.assignment_revision, 1)
        self.assertEqual(OperationEvent.objects.filter(kind='outbound_auto_assigned').count(), 1)

    def test_account_conversion_waits_for_assignment_and_then_cannot_change_historical_owner(self):
        validated, release, conversion_lock = Event(), Event(), Event()
        original = logistics._courier
        def paused(*args, **kwargs):
            result = original(*args, **kwargs)
            validated.set()
            if not release.wait(timeout=15):
                raise RuntimeError('Synthetic courier lock timeout')
            return result
        def assign():
            return logistics.assign_outbound(User.objects.get(pk=self.manager.pk), {'service_request': self.record.pk, 'courier': self.external.pk}).pk
        def observe(execute, sql, params, many, context):
            if 'FOR UPDATE' in sql and 'core_user' in sql:
                conversion_lock.set()
            return execute(sql, params, many, context)
        def convert():
            account = User.objects.get(pk=self.external.pk)
            account.client = self.other
            with connection.execute_wrapper(observe):
                try:
                    account.save()
                except ValidationError:
                    return 'protected'
            return 'unexpected_conversion'
        with patch('core.logistics_service._courier', side_effect=paused), ThreadPoolExecutor(max_workers=2) as pool:
            assignment = pool.submit(self.worker, assign)
            self.assertTrue(validated.wait(timeout=10))
            conversion = pool.submit(self.worker, convert)
            self.assertTrue(conversion_lock.wait(timeout=10))
            self.assertFalse(conversion.done())
            release.set()
            self.assertIsNotNone(assignment.result(timeout=30))
            self.assertEqual(conversion.result(timeout=30), 'protected')
        self.external.refresh_from_db()
        self.assertEqual(self.external.client_id, self.company.pk)
