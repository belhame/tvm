"""Physical arrival and handoff invariants; exclusively fictional fixtures."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core import logistics_service as logistics
from core.models import Client, CourierReceipt, Equipment, OperationEvent, OutboundJob, ServiceRequest, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogisticsWorkflowTests(TestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Logistique laboratoire fictive', address='Adresse de laboratoire', contact_name='Contact laboratoire', phone='00000000')
        self.admin = User.objects.create_user('logistics-lab-admin', role='admin')
        self.courier = User.objects.create_user('logistics-lab-courier', role='courier')
        self.other_courier = User.objects.create_user('logistics-lab-other-courier', role='courier')
        self.customer = User.objects.create_user('logistics-lab-client', role='client', client=self.company)
        self.unit = Equipment.objects.create(client=self.company, serial_number='LOGISTICS-LAB-01', model='Modèle fictif')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def legacy_ready(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Ancien dossier prêt fictif', arrived_at=timezone.now(), client_reference='000-LOGISTICS-LAB')
        # Simulate a historical ready state without inventing a new test result.
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        return record

    def job(self):
        record = self.legacy_ready()
        return logistics.assign_outbound(self.admin, {'service_request': record.pk, 'courier': self.courier.pk})

    def test_cancellation_releases_unit_and_reassignment_keeps_immutable_cancellation_history(self):
        job = self.job()
        self.assertEqual(job.delivery_address, self.company.address)
        self.assertEqual(job.contact_name, self.company.contact_name)
        logistics.cancel_outbound(self.admin, job.pk, {'reason': 'Créneau client à corriger'})
        self.assertFalse(OutboundJob.objects.get(pk=job.pk).active)
        from core.logistics_payloads import dispatch_candidates
        self.assertEqual([row['id'] for row in dispatch_candidates(self.admin)], [job.service_request_id])
        job = logistics.assign_outbound(self.admin, {'courier': self.other_courier.pk, 'delivery_address': 'Nouvelle adresse fictive'}, pk=job.pk)
        self.assertTrue(job.active)
        self.assertIsNone(job.cancelled_at)
        self.assertEqual(job.delivery_address, 'Nouvelle adresse fictive')
        self.assertEqual(OperationEvent.objects.filter(service_request=job.service_request, kind='outbound_cancelled').count(), 1)
        logistics.handoff(self.other_courier, job.pk, {'recipient_name': 'Destinataire fictif'})
        with self.assertRaises(ValidationError):
            logistics.assign_outbound(self.admin, {'courier': self.courier.pk}, pk=job.pk)
        with self.assertRaises(ValidationError):
            logistics.cancel_outbound(self.admin, job.pk, {'reason': 'Annulation après preuve impossible'})

    def test_manager_handoff_reports_actual_actor_and_clients_see_confirmation_without_financial_data(self):
        job = self.job()
        response = self.api.post(f'/api/logistics/outbound/{job.pk}/handoff/', {'recipient_name': 'Destinataire laboratoire'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['handed_over_by_role'], 'admin')
        self.assertEqual(response.data['handed_over_by_name'], self.admin.username)
        self.assertNotEqual(response.data['handed_over_by_name'], response.data['assigned_courier_name'])
        self.api.force_authenticate(self.customer)
        response = self.api.get(f'/api/logistics/outbound/{job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['recipient_name'], 'Destinataire laboratoire')
        self.assertNotIn('invoice_reference', response.data)
        self.assertNotIn('client_confirmed_at', response.data)
        self.assertFalse(response.data['can_handoff'])
        job.service_request.refresh_from_db()
        self.assertEqual(job.service_request.status, 'ready_for_delivery')

    def test_rearrival_after_handoff_creates_another_unassigned_case_and_preserves_old_proof(self):
        job = self.job()
        logistics.handoff(self.courier, job.pk, {'recipient_name': 'Destinataire laboratoire'})
        job.refresh_from_db()
        proof = job.handed_over_at
        receipt = logistics.receive(self.courier, {'request_key': uuid4(), 'serial_number': self.unit.serial_number,
            'client': self.company.pk, 'client_reference': '000-NEW-LAB', 'source': 'usb'})
        self.assertTrue(receipt.created_request)
        self.assertFalse(receipt.already_received)
        self.assertNotEqual(receipt.service_request_id, job.service_request_id)
        self.assertEqual(receipt.service_request.status, 'new')
        self.assertIsNone(receipt.service_request.assigned_technician_id)
        self.assertEqual(receipt.service_request.client_reference, '000-NEW-LAB')
        job.refresh_from_db()
        self.assertEqual(job.handed_over_at, proof)
        self.assertEqual(job.recipient_name, 'Destinataire laboratoire')
        self.assertEqual(ServiceRequest.objects.get(pk=job.service_request_id).status, 'ready_for_delivery')

    def test_handed_over_request_and_unit_cannot_be_reparented_or_requalified_via_model(self):
        job = self.job()
        logistics.handoff(self.courier, job.pk, {'recipient_name': 'Destinataire laboratoire'})
        other = Equipment.objects.create(client=self.company, serial_number='LOGISTICS-OTHER-LAB', model='Autre modèle fictif')
        record = ServiceRequest.objects.get(pk=job.service_request_id)
        record.equipment = other
        with self.assertRaises(ValidationError):
            record.save()
        record.refresh_from_db()
        record.status = 'testing'
        with self.assertRaises(ValidationError):
            record.save()
        self.unit.serial_number = 'FORGED-LOGISTICS-SERIAL'
        with self.assertRaises(ValidationError):
            self.unit.save()
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.serial_number, 'LOGISTICS-LAB-01')

    def test_receiving_existing_new_case_sets_missing_client_reference_without_changing_its_number(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Pré-enregistrement fictif')
        reference = record.reference
        receipt = logistics.receive(self.courier, {'request_key': uuid4(), 'serial_number': self.unit.serial_number, 'client': self.company.pk, 'client_reference': '000-CLIENT-INTAKE'})
        record.refresh_from_db()
        self.assertEqual(receipt.service_request_id, record.pk)
        self.assertEqual(record.reference, reference)
        self.assertEqual(record.client_reference, '000-CLIENT-INTAKE')
        self.assertIsNotNone(record.arrived_at)

    def test_technician_cannot_be_assigned_as_courier_and_server_owned_fields_are_rejected(self):
        tech = User.objects.create_user('logistics-lab-tech', role='technician')
        job = self.job()
        for body in ({'courier': tech.pk}, {'courier': self.courier.pk, 'handed_over_at': '2000-01-01T00:00:00Z'}):
            response = self.api.post(f'/api/logistics/outbound/{job.pk}/assign/', body, format='json')
            self.assertEqual(response.status_code, 400)
        self.assertIsNone(OutboundJob.objects.get(pk=job.pk).handed_over_at)


@skipUnless(connection.vendor == 'postgresql', 'Physical logistics concurrency requires PostgreSQL row locks.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogisticsConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Concurrence logistique fictive')
        self.other_company = Client.objects.create(name='Autre concurrence fictive')
        self.courier = User.objects.create_user('courier-concurrent-lab', role='courier')
        self.manager = User.objects.create_user('courier-concurrent-manager', role='manager')
        self.unit = Equipment.objects.create(client=self.company, serial_number='COURIER-CONCURRENT-LAB', model='Laboratoire fictif')

    def worker(self, callback):
        close_old_connections()
        try:
            return callback()
        finally:
            connections.close_all()

    def run_receipts(self, same_key):
        barrier = Barrier(2)
        shared = uuid4()
        def work(index):
            actor = User.objects.get(pk=self.courier.pk)
            barrier.wait(timeout=10)
            receipt = logistics.receive(actor, {'request_key': shared if same_key else uuid4(), 'serial_number': self.unit.serial_number, 'client': self.company.pk})
            return receipt.pk, receipt.service_request_id
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, lambda index=index: work(index)) for index in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_same_uuid_concurrent_retries_create_one_receipt_and_arrival(self):
        results = self.run_receipts(True)
        self.assertEqual(results[0], results[1])
        self.assertEqual(CourierReceipt.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.filter(kind='courier_received').count(), 1)

    def test_distinct_scans_of_one_serial_concurrently_keep_one_open_arrival(self):
        results = self.run_receipts(False)
        self.assertEqual(len({row[1] for row in results}), 1)
        self.assertEqual(CourierReceipt.objects.count(), 2)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(CourierReceipt.objects.filter(already_received=True).count(), 1)

    def test_concurrent_assignments_cannot_reserve_one_unit_in_two_missions(self):
        records = [ServiceRequest.objects.create(equipment=self.unit, subject=f'Mission fictive {i}') for i in range(2)]
        ServiceRequest.objects.all().update(status='ready_for_delivery')
        barrier = Barrier(2)
        def work(record):
            actor = User.objects.get(pk=self.manager.pk)
            barrier.wait(timeout=10)
            try:
                return logistics.assign_outbound(actor, {'service_request': record.pk, 'courier': self.courier.pk}).pk
            except ValidationError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=30) for future in [pool.submit(self.worker, lambda record=record: work(record)) for record in records]]
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(OutboundJob.objects.filter(active=True).count(), 1)

    def paused_identity_mutation(self, changes, body):
        passed_guard, release, reached_lock = Event(), Event(), Event()
        original_guard = logistics.guard_logistics_equipment_update
        def guarded(instance, update_fields=None):
            original_guard(instance, update_fields)
            if instance.pk == self.unit.pk:
                passed_guard.set()
                if not release.wait(timeout=15):
                    raise RuntimeError('Synthetic identity mutation timeout')
        def mutate():
            unit = Equipment.objects.get(pk=self.unit.pk)
            for key, value in changes.items():
                setattr(unit, key, value)
            unit.save()
        def execute(execute, sql, params, many, context):
            if 'FOR NO KEY UPDATE' in sql:
                reached_lock.set()
            return execute(sql, params, many, context)
        def blocked_work():
            with connection.execute_wrapper(execute):
                return body()
        with patch('core.logistics_service.guard_logistics_equipment_update', side_effect=guarded), ThreadPoolExecutor(max_workers=2) as pool:
            mutation = pool.submit(self.worker, mutate)
            self.assertTrue(passed_guard.wait(timeout=10))
            waiting = pool.submit(self.worker, blocked_work)
            self.assertTrue(reached_lock.wait(timeout=10))
            self.assertFalse(waiting.done())
            release.set()
            mutation.result(timeout=30)
            return waiting.result(timeout=30)

    def test_receive_waits_for_owner_change_then_rejects_stale_selected_client(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Réception fictive concurrente')
        def receive():
            try:
                logistics.receive(User.objects.get(pk=self.courier.pk), {'request_key': uuid4(), 'serial_number': self.unit.serial_number, 'client': self.company.pk})
            except ValidationError:
                return 'owner_changed'
            return 'unexpected_arrival'
        result = self.paused_identity_mutation({'client_id': self.other_company.pk}, receive)
        self.assertEqual(result, 'owner_changed')
        self.assertFalse(CourierReceipt.objects.exists())
        record.refresh_from_db()
        self.assertIsNone(record.arrived_at)

    def test_handoff_waits_for_serial_mutation_then_snapshots_actual_locked_identity(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Remise fictive concurrente')
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        job = logistics.assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.courier.pk})
        def handoff():
            return logistics.handoff(User.objects.get(pk=self.courier.pk), job.pk, {'recipient_name': 'Destinataire concurrent fictif'}).pk
        identifier = self.paused_identity_mutation({'serial_number': 'COURIER-CONCURRENT-UPDATED'}, handoff)
        self.assertEqual(identifier, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.handed_over_serial, 'COURIER-CONCURRENT-UPDATED')
        self.assertFalse(job.active)
