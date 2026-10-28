"""Approval is evidence, not an inference from a SAV status or a visit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.exchange_workflow import prepare_exchange, ready_exchange, validate_exchange
from core.models import AuditLog, Client, Equipment, ExchangeProcess, Intervention, OperationEvent, ServiceRequest
from core.request_assignment import confirm_assignment


User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ExchangeWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Échanges de laboratoire fictifs')
        cls.foreign = Client.objects.create(name='Autre centre fictif')
        cls.original = Equipment.objects.create(client=cls.company, serial_number='EXCHANGE-LAB-OLD', model='Ancien modèle fictif')
        cls.stock = Equipment.objects.create(client=cls.company, serial_number='EXCHANGE-LAB-STOCK', model='Modèle stock fictif')
        cls.foreign_unit = Equipment.objects.create(client=cls.foreign, serial_number='EXCHANGE-FOREIGN-STOCK', model='Autre modèle fictif')
        cls.admin = User.objects.create_user('exchange-admin', role='admin')
        cls.manager = User.objects.create_user('exchange-manager', role='manager')
        cls.finance = User.objects.create_user('exchange-finance', role='manager', can_validate_billing=True)
        cls.tech = User.objects.create_user('exchange-tech', role='technician')
        cls.other_tech = User.objects.create_user('exchange-other-tech', role='technician')
        cls.customer = User.objects.create_user('exchange-customer', role='client', client=cls.company)
        cls.request = ServiceRequest.objects.create(equipment=cls.original, subject='Remplacement fictif', status='exchange',
                                                   assigned_technician=cls.tech, client_reference='000-CLIENT-EXCHANGE')
        cls.request = confirm_assignment(cls.request.pk, actor=cls.tech, expected_revision=cls.request.assignment_revision, accept=True)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def endpoint(self, action=None, request=None):
        path = f'/api/requests/{(request or self.request).pk}/exchange/'
        return path + f'{action}/' if action else path

    def prepare(self, **changes):
        payload = dict(replacement_serial_number='EXCHANGE-NEW-001', replacement_model='Modèle remplacement fictif', replacement_brand='Marque fictive')
        payload.update(changes)
        response = self.api.patch(self.endpoint(), payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def validate(self):
        response = self.api.post(self.endpoint('validate'), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def ready(self):
        response = self.api.post(self.endpoint('ready'), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def bill(self):
        self.api.force_authenticate(self.finance)
        response = self.api.post(self.endpoint('billing'), {'invoice_reference': '000-FACT-EXCHANGE', 'invoiced_on': timezone.localdate().isoformat(), 'billing_notes': 'NOTE-FINANCE-PRIVEE'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_status_alone_appears_in_queue_without_creating_a_visit_or_approval(self):
        before = (Intervention.objects.count(), Equipment.objects.count())
        result = self.api.get('/api/exchanges/?q=000-CLIENT-EXCHANGE')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([row['id'] for row in result.data], [self.request.pk])
        self.assertEqual(result.data[0]['exchange']['state'], 'awaiting_preparation')
        self.assertIsNone(result.data[0]['exchange']['validated_at'])
        self.assertEqual((Intervention.objects.count(), Equipment.objects.count()), before)

    def test_preparation_does_not_create_equipment_validation_does_and_keeps_call_and_original(self):
        before = Equipment.objects.count()
        reference = self.request.reference
        self.prepare()
        self.assertEqual(Equipment.objects.count(), before)
        response = self.validate()
        self.assertEqual(Equipment.objects.count(), before + 1)
        self.assertEqual(response.data['reference'], reference)
        self.assertEqual(response.data['client_reference'], '000-CLIENT-EXCHANGE')
        self.assertEqual(response.data['equipment'], self.original.pk)
        replacement = Equipment.objects.get(pk=response.data['exchange']['replacement_equipment'])
        self.assertEqual(replacement.client_id, self.company.pk)
        self.assertEqual(replacement.serial_number, 'EXCHANGE-NEW-001')
        self.assertFalse(Intervention.objects.exists())
        self.assertEqual(response.data['status'], 'exchange')
        self.assertEqual(response.data['exchange']['state'], 'validated')

    def test_missing_model_serial_original_and_foreign_unit_never_validate(self):
        for values in [dict(replacement_serial_number=''), dict(replacement_serial_number=self.original.serial_number), dict(replacement_serial_number='EXCHANGE-UNKNOWN', replacement_model='')]:
            self.prepare(**values)
            response = self.api.post(self.endpoint('validate'), {}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        before = Equipment.objects.count()
        response = self.api.patch(self.endpoint(), {'replacement_serial_number': self.foreign_unit.serial_number}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Equipment.objects.count(), before)
        self.assertIsNone(ExchangeProcess.objects.get(service_request=self.request).validated_at)

    def test_existing_replacement_selection_reuses_identity_and_checks_model(self):
        self.prepare(replacement_serial_number=self.stock.serial_number, replacement_model='Mauvais modèle')
        response = self.api.post(self.endpoint('validate'), {}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.patch(self.endpoint(), {'replacement_equipment': self.stock.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        count = Equipment.objects.count()
        self.validate()
        self.assertEqual(Equipment.objects.count(), count)
        process = ExchangeProcess.objects.get(service_request=self.request)
        self.assertEqual(process.replacement_equipment_id, self.stock.pk)
        self.assertEqual(process.replacement_model, self.stock.model)

    def test_assigned_technician_prepares_but_cannot_approve_or_mark_ready(self):
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.api.patch(self.endpoint(), {'replacement_serial_number': 'EXCHANGE-TECH'}, format='json').status_code, 403)
        self.api.force_authenticate(self.tech)
        self.prepare()
        self.assertEqual(self.api.post(self.endpoint('validate'), {}, format='json').status_code, 403)
        self.api.force_authenticate(self.manager)
        self.validate()
        self.api.force_authenticate(self.tech)
        self.assertEqual(self.api.post(self.endpoint('ready'), {}, format='json').status_code, 403)

    def test_ready_and_billing_are_separate_and_do_not_close_or_confirm_delivery(self):
        self.assertEqual(self.api.post(self.endpoint('ready'), {}, format='json').status_code, 400)
        self.prepare()
        self.validate()
        response = self.ready()
        self.assertEqual(response.data['status'], 'ready_for_delivery')
        self.assertFalse(response.data['exchange']['is_invoiced'])
        self.assertIsNone(response.data['closed_at'])
        self.assertEqual(self.api.post(self.endpoint('close'), {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(self.endpoint('billing'), {'invoice_reference': '000-FACT', 'invoiced_on': timezone.localdate().isoformat()}, format='json').status_code, 403)
        response = self.bill()
        self.assertEqual(response.data['status'], 'ready_for_delivery')
        self.assertTrue(response.data['exchange']['is_invoiced'])
        self.assertIsNone(response.data['closed_at'])
        self.assertIn(self.request.pk, [row['id'] for row in self.api.get('/api/exchanges/billing/').data])
        response = self.api.post(self.endpoint('close'), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'closed')
        self.assertNotIn(self.request.pk, [row['id'] for row in self.api.get('/api/exchanges/billing/').data])
        self.assertFalse(ExchangeProcess.objects.get(service_request=self.request).reservation_active)

    def test_billing_requires_explicit_permission_reference_and_past_date(self):
        self.api.force_authenticate(self.finance)
        payload = {'invoice_reference': '000-FACT', 'invoiced_on': timezone.localdate().isoformat()}
        self.assertEqual(self.api.post(self.endpoint('billing'), payload, format='json').status_code, 400)
        self.prepare()
        self.validate()
        self.ready()
        for bad in ({}, {'invoice_reference': '', 'invoiced_on': payload['invoiced_on']}, {'invoice_reference': '000-FACT', 'invoiced_on': (timezone.localdate() + timedelta(days=1)).isoformat()}, {'invoice_reference': 42, 'invoiced_on': payload['invoiced_on']}):
            response = self.api.post(self.endpoint('billing'), bad, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        response = self.bill()
        self.assertEqual(response.data['exchange']['invoice_reference'], '000-FACT-EXCHANGE')

    def test_generic_status_and_timeline_cannot_bypass_billing_after_status_detour(self):
        for state in ('ready_for_delivery', 'closed'):
            self.assertEqual(self.api.patch(f'/api/requests/{self.request.pk}/', {'status': state}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'pending'}, format='json').status_code, 200)
        response = self.api.post(f'/api/requests/{self.request.pk}/timeline/', {'kind': 'status_changed', 'status_after': 'closed', 'observation': 'Tentative de clôture sans facturation.'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(self.request.pk, [row['id'] for row in self.api.get('/api/exchanges/').data])

    def test_approval_ready_billing_and_closure_replays_are_idempotent(self):
        self.prepare()
        self.validate()
        timestamps = []
        for action in ('validate', 'ready'):
            self.api.post(self.endpoint(action), {}, format='json')
            before = (OperationEvent.objects.count(), Equipment.objects.count(), AuditLog.objects.count())
            again = self.api.post(self.endpoint(action), {}, format='json')
            self.assertEqual(again.status_code, 200, again.data)
            self.assertEqual(before, (OperationEvent.objects.count(), Equipment.objects.count(), AuditLog.objects.count()))
        self.bill()
        before = (OperationEvent.objects.count(), AuditLog.objects.count())
        self.bill()
        self.assertEqual(before, (OperationEvent.objects.count(), AuditLog.objects.count()))
        response = self.api.post(self.endpoint('close'), {}, format='json')
        closed_at = response.data['closed_at']
        before = (OperationEvent.objects.count(), AuditLog.objects.count())
        response = self.api.post(self.endpoint('close'), {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['closed_at'], closed_at)
        self.assertEqual(before, (OperationEvent.objects.count(), AuditLog.objects.count()))

    def test_invoiced_evidence_and_approved_identity_cannot_be_edited(self):
        self.prepare()
        self.validate()
        self.assertEqual(self.api.patch(self.endpoint(), {'replacement_serial_number': 'ALTERED'}, format='json').status_code, 400)
        process = ExchangeProcess.objects.get(service_request=self.request)
        for unit in (self.original, process.replacement_equipment):
            self.assertEqual(self.api.patch(f'/api/equipment/{unit.pk}/', {'serial_number': 'ALTERED-SERIAL'}, format='json').status_code, 400)
        self.ready()
        self.bill()
        self.assertEqual(self.api.post(self.endpoint('billing'), {'invoice_reference': 'OTHER', 'invoiced_on': timezone.localdate().isoformat()}, format='json').status_code, 400)
        self.assertEqual(self.api.post(self.endpoint('reset'), {'reason': 'Correction'}, format='json').status_code, 400)

    def test_reset_requires_reason_and_releases_reservation_but_keeps_history(self):
        self.prepare()
        self.validate()
        self.ready()
        process = ExchangeProcess.objects.get(service_request=self.request)
        replacement = process.replacement_equipment
        self.assertEqual(self.api.post(self.endpoint('reset'), {}, format='json').status_code, 400)
        response = self.api.post(self.endpoint('reset'), {'reason': 'REASON-PRIVATE-EXCHANGE'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'exchange')
        self.assertFalse(response.data['exchange']['is_validated'])
        process.refresh_from_db()
        self.assertFalse(process.reservation_active)
        self.assertTrue(replacement.related_operation_events.filter(kind='exchange_validated').exists())
        self.assertTrue(replacement.related_operation_events.filter(kind='exchange_reset').exists())
        self.assertEqual(self.api.post(self.endpoint('ready'), {}, format='json').status_code, 400)

    def test_new_equipment_and_approval_roll_back_if_audit_fails(self):
        self.prepare()
        before = Equipment.objects.count()
        with patch('core.exchange_workflow._audit', side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaises(RuntimeError):
                self.api.post(self.endpoint('validate'), {}, format='json')
        self.assertEqual(Equipment.objects.count(), before)
        self.assertIsNone(ExchangeProcess.objects.get(service_request=self.request).validated_at)

    def test_client_cannot_probe_drafts_or_read_invoice_identifiers(self):
        self.prepare()
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get('/api/exchanges/?q=EXCHANGE-NEW-001').data, [])
        data = self.api.get(self.endpoint()).data['exchange']
        self.assertEqual(data['replacement_serial_number'], '')
        self.assertNotIn('validated_by', data)
        self.assertNotIn('invoice_reference', data)
        self.api.force_authenticate(self.manager)
        self.validate()
        self.ready()
        self.bill()
        self.api.force_authenticate(self.customer)
        data = self.api.get(self.endpoint()).data['exchange']
        self.assertEqual(data['replacement_serial_number'], 'EXCHANGE-NEW-001')
        self.assertTrue(data['is_invoiced'])
        self.assertNotIn('invoice_reference', data)
        self.assertNotIn('billing_notes', data)
        self.assertEqual(self.api.get('/api/exchanges/billing/').status_code, 403)

    def test_foreign_requests_are_not_found_and_clients_cannot_mutate(self):
        foreign_request = ServiceRequest.objects.create(equipment=self.foreign_unit, subject='Autre échange', status='exchange')
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get(self.endpoint(request=foreign_request)).status_code, 404)
        self.assertEqual(self.api.post(self.endpoint('validate', request=foreign_request), {}, format='json').status_code, 404)
        self.assertEqual(self.api.patch(self.endpoint(), {'validated_at': '2025-01-01'}, format='json').status_code, 403)

    def test_an_exchange_cannot_be_added_after_closing_a_nonexchange_request(self):
        closed = ServiceRequest.objects.create(equipment=self.original, subject='Dossier déjà clôturé', status='closed')
        response = self.api.post('/api/interventions/', {'service_request': closed.pk, 'kind': 'exchange'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ExchangeProcess.objects.filter(service_request=closed).exists())


@skipUnless(connection.vendor == 'postgresql', 'Les verrous et réservations concurrentes exigent PostgreSQL.')
class ExchangeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Concurrence échange fictive')
        self.actor = User.objects.create_user('exchange-concurrent-manager', role='manager')
        self.first = Equipment.objects.create(client=self.company, serial_number='EXC-CONCURRENT-OLD-A', model='Fictif A')
        self.second = Equipment.objects.create(client=self.company, serial_number='EXC-CONCURRENT-OLD-B', model='Fictif B')
        self.requests = [ServiceRequest.objects.create(equipment=unit, subject='Échange concurrent fictif', status='exchange') for unit in (self.first, self.second)]

    def test_two_users_cannot_reserve_the_same_new_serial_for_two_exchanges(self):
        for record in self.requests:
            prepare_exchange(record.pk, {'replacement_serial_number': 'EXC-CONCURRENT-SHARED', 'replacement_model': 'Modèle fictif commun'}, actor=self.actor)
        barrier = Barrier(2)
        def reserve(identifier):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                try:
                    validate_exchange(identifier, actor=actor)
                    return 'validated'
                except ValidationError:
                    return 'reserved'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, [record.pk for record in self.requests], timeout=30))
        self.assertCountEqual(results, ['validated', 'reserved'])
        self.assertEqual(Equipment.objects.filter(serial_number='EXC-CONCURRENT-SHARED').count(), 1)
        self.assertEqual(ExchangeProcess.objects.filter(reservation_active=True).count(), 1)

    def test_two_validations_of_one_dossier_create_one_approval_and_one_unit(self):
        record = self.requests[0]
        prepare_exchange(record.pk, {'replacement_serial_number': 'EXC-CONCURRENT-RETRY', 'replacement_model': 'Modèle fictif de reprise'}, actor=self.actor)
        barrier = Barrier(2)
        def approve(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return validate_exchange(record.pk, actor=User.objects.get(pk=self.actor.pk)).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, range(2), timeout=30))
        self.assertEqual(results, [record.pk, record.pk])
        self.assertEqual(Equipment.objects.filter(serial_number='EXC-CONCURRENT-RETRY').count(), 1)
        self.assertEqual(OperationEvent.objects.filter(service_request=record, kind='exchange_validated').count(), 1)
