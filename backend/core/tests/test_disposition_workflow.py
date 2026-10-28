"""Diagnostic approval and quotations remain correct under real concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.disposition_workflow import (close_disposition, confirm_diagnostic_invoice, edit_quote_draft, issue_quote,
    mark_nonrepairable, mark_repaired)
from core.models import AuditLog, Client, DiagnosticQuote, DiagnosticQuoteSequence, DispositionProcess, Equipment, OperationEvent, ServiceRequest
from core.request_assignment import confirm_assignment


User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DispositionWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Laboratoire Diagnostic Fictif')
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='DIAG-UNIT-FICTIVE', model='Modèle fictif')
        cls.manager = User.objects.create_user('diagnostic-manager', role='manager')
        cls.tech = User.objects.create_user('diagnostic-tech', role='technician')
        cls.finance = User.objects.create_user('diagnostic-finance', role='technician', can_validate_billing=True)
        cls.request = ServiceRequest.objects.create(equipment=cls.unit, subject='Diagnostic fictif', status='testing',
                                                    client_reference='000-CLIENT-DIAG', assigned_technician=cls.tech)
        cls.request = confirm_assignment(cls.request.pk, actor=cls.tech, expected_revision=cls.request.assignment_revision, accept=True)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def url(self, action=''):
        return f'/api/requests/{self.request.pk}/disposition/' + (f'{action}/' if action else '')

    def post(self, action, data=None):
        return self.api.post(self.url(action), {} if data is None else data, format='json')

    def classified(self, *, free=False):
        response = self.post('nonrepairable', {'diagnosis': 'Carte de laboratoire non réparable.', 'fee_mode': 'free' if free else 'billable', 'free_reason': 'Proposition fictive de gratuité' if free else ''})
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def quote(self, *, free=False):
        self.classified(free=free)
        draft = self.api.patch(self.url(), {'price_ht': '0.000' if free else '100.125', 'vat_rate': '19.00', 'currency': 'TND'}, format='json')
        self.assertEqual(draft.status_code, 200, draft.data)
        result = self.post('quote/issue')
        self.assertEqual(result.status_code, 200, result.data)
        return result.data['disposition']['quote']

    def test_pending_read_has_action_permissions_without_creating_any_evidence(self):
        before = DispositionProcess.objects.count(), DiagnosticQuote.objects.count(), OperationEvent.objects.count()
        result = self.api.get(self.url())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['disposition']['outcome'], 'pending')
        self.assertTrue(result.data['disposition']['can_mark_repaired'])
        self.assertTrue(result.data['disposition']['can_mark_nonrepairable'])
        self.assertFalse(result.data['disposition']['tests_passed'])
        self.assertEqual(before, (DispositionProcess.objects.count(), DiagnosticQuote.objects.count(), OperationEvent.objects.count()))

    def test_repair_confirmation_is_idempotent_and_does_not_invent_a_visit(self):
        payload = {'diagnosis': 'Réparation et tests de laboratoire terminés.', 'tests_passed': True, 'tested_on': timezone.localdate().isoformat()}
        self.api.force_authenticate(self.tech)
        first = self.post('repair', payload)
        self.assertEqual(first.status_code, 200, first.data)
        count = OperationEvent.objects.count()
        classified_at = first.data['disposition']['classified_at']
        second = self.post('repair', payload)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data['disposition']['classified_at'], classified_at)
        self.assertEqual(OperationEvent.objects.count(), count)
        self.assertEqual(second.data['dispatch_kind'], 'repair')
        self.assertFalse(self.request.interventions.exists())

    def test_paid_diagnostic_keeps_call_numbers_and_stays_return_until_explicit_close(self):
        reference = self.request.reference
        quote = self.quote()
        self.assertEqual(quote['price_ht'], '100.125')
        self.assertEqual(quote['vat_amount'], '19.024')
        self.assertEqual(quote['total_ttc'], '119.149')
        self.assertEqual(self.post('close').status_code, 400)
        self.api.force_authenticate(self.finance)
        billed = self.post('invoice', {'invoice_reference': '000-FACT-DIAG', 'invoiced_on': timezone.localdate().isoformat(), 'billing_notes': 'Finance fictive privée'})
        self.assertEqual(billed.status_code, 200, billed.data)
        self.assertEqual(billed.data['status'], 'return_to_client')
        self.assertEqual(billed.data['reference'], reference)
        self.assertEqual(billed.data['client_reference'], '000-CLIENT-DIAG')
        self.assertIsNone(billed.data['closed_at'])
        self.assertIn(self.request.pk, [row['id'] for row in self.api.get('/api/dispatch/billing/').data])
        closed = self.post('close')
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(closed.data['status'], 'closed')
        self.assertIsNotNone(closed.data['closed_at'])

    def test_free_diagnostic_has_no_fake_invoice_and_requires_separate_finance_approval(self):
        quote = self.quote(free=True)
        self.assertEqual(quote['total_ttc'], '0.000')
        self.assertEqual(self.post('free', {'reason': 'Décision non autorisée'}).status_code, 403)
        self.assertEqual(self.post('close').status_code, 400)
        self.api.force_authenticate(self.finance)
        self.assertEqual(self.post('invoice', {'invoice_reference': 'NE-PAS-CREER', 'invoiced_on': timezone.localdate().isoformat()}).status_code, 400)
        approved = self.post('free', {'reason': 'Geste commercial autorisé pour le diagnostic fictif.'})
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['disposition']['state'], 'free_approved')
        process = DispositionProcess.objects.get(service_request=self.request)
        self.assertEqual(process.invoice_reference, '')
        self.assertIsNone(process.invoiced_on)
        self.assertEqual(self.post('close').status_code, 200)

    def test_quote_emission_replays_do_not_allocate_a_second_number_or_snapshot(self):
        quote = self.quote()
        before = DiagnosticQuote.objects.count(), DiagnosticQuoteSequence.objects.get(year=timezone.localdate().year).last_value, OperationEvent.objects.count()
        repeated = self.post('quote/issue')
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['disposition']['quote'], quote)
        self.assertEqual(before, (DiagnosticQuote.objects.count(), DiagnosticQuoteSequence.objects.get(year=timezone.localdate().year).last_value, OperationEvent.objects.count()))

    def test_failed_issue_audit_rolls_back_quote_sequence_and_process_pointer(self):
        self.classified()
        self.api.patch(self.url(), {'price_ht': '100.000', 'vat_rate': '19'}, format='json')
        with patch('core.disposition_workflow._audit', side_effect=RuntimeError('Synthetic quote audit failure')):
            with self.assertRaises(RuntimeError):
                self.post('quote/issue')
        self.assertFalse(DiagnosticQuote.objects.exists())
        self.assertIsNone(DispositionProcess.objects.get(service_request=self.request).current_quote_id)
        self.assertFalse(DiagnosticQuoteSequence.objects.exists())

    def test_quote_is_protected_by_database_even_from_direct_sql_update_and_delete(self):
        from django.db import IntegrityError
        quote = self.quote()
        for statement in ('UPDATE core_diagnosticquote SET number = %s WHERE id = %s', 'DELETE FROM core_diagnosticquote WHERE number = %s AND id = %s'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(statement, [quote['number'], quote['id']])
        self.assertTrue(DiagnosticQuote.objects.filter(pk=quote['id'], number=quote['number']).exists())

    def test_technician_list_capabilities_do_not_query_visits_for_every_request(self):
        from core.disposition_workflow import disposition_related
        from core.exchange_workflow import exchange_related, workflow_permission_hints
        from core.preventive_visits import with_preventive_counts
        from core.serializers import ServiceRequestSerializer
        for index in range(4):
            ServiceRequest.objects.create(equipment=self.unit, subject=f'Autre diagnostic fictif {index}', status='testing')
        queryset = workflow_permission_hints(disposition_related(exchange_related(with_preventive_counts(
            ServiceRequest.objects.select_related('equipment__client', 'assigned_technician', 'assignment_accepted_by')))), self.tech)
        with self.assertNumQueries(1):
            records = ServiceRequestSerializer(queryset, many=True, context={'request': SimpleNamespace(user=self.tech)}).data
        self.assertEqual(len(records), 5)
        allowed = [row['id'] for row in records if row['disposition']['can_mark_repaired']]
        self.assertEqual(allowed, [self.request.pk])


@skipUnless(connection.vendor == 'postgresql', 'La concurrence de la facturation exige les verrous PostgreSQL.')
class DiagnosticConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Concurrence diagnostic fictive')
        self.manager = User.objects.create_user('diag-concurrent-manager', role='manager')
        self.finance = User.objects.create_user('diag-concurrent-finance', role='technician', can_validate_billing=True)
        self.unit = Equipment.objects.create(client=self.company, serial_number='DIAG-CONCURRENT-UNIT', model='Laboratoire fictif')
        self.records = [ServiceRequest.objects.create(equipment=self.unit, subject=f'Diagnostic fictif {index}', status='testing') for index in range(2)]
        for record in self.records:
            mark_nonrepairable(record.pk, {'diagnosis': 'Diagnostic concurrent fictif', 'fee_mode': 'billable'}, actor=self.manager)
            edit_quote_draft(record.pk, {'price_ht': Decimal('10.000'), 'vat_rate': Decimal('19.00')}, actor=self.manager)

    def worker(self, identifier, barrier):
        close_old_connections()
        try:
            actor = User.objects.get(pk=self.manager.pk)
            barrier.wait(timeout=10)
            return issue_quote(identifier, actor=actor).pk
        finally:
            connections.close_all()

    def test_two_issuers_of_one_dossier_keep_one_quote_and_one_number(self):
        record = self.records[0]
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, record.pk, barrier) for _ in range(2)]
            self.assertEqual([future.result(timeout=30) for future in futures], [record.pk, record.pk])
        self.assertEqual(DiagnosticQuote.objects.count(), 1)
        self.assertEqual(DiagnosticQuoteSequence.objects.get(year=timezone.localdate().year).last_value, 1)
        self.assertEqual(OperationEvent.objects.filter(service_request=record, kind='diagnostic_quote_issued').count(), 1)

    def test_two_dossiers_receive_distinct_quote_numbers_from_the_annual_sequence(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, record.pk, barrier) for record in self.records]
            self.assertEqual(len({future.result(timeout=30) for future in futures}), 2)
        self.assertEqual(DiagnosticQuote.objects.count(), 2)
        self.assertEqual(len(set(DiagnosticQuote.objects.values_list('number', flat=True))), 2)
        self.assertEqual(DiagnosticQuoteSequence.objects.get(year=timezone.localdate().year).last_value, 2)

    def test_close_waits_for_the_financial_transaction_instead_of_reading_partial_evidence(self):
        from core import disposition_workflow
        record = self.records[0]
        issue_quote(record.pk, actor=self.manager)
        finance_paused, close_started, release_finance = Event(), Event(), Event()
        original_audit = disposition_workflow._audit
        def controlled_audit(process, actor, action):
            if action == 'diagnostic_invoice':
                finance_paused.set()
                if not release_finance.wait(timeout=15):
                    raise RuntimeError('Synthetic finance transaction timed out')
            return original_audit(process, actor, action)
        def invoice():
            close_old_connections()
            try:
                return confirm_diagnostic_invoice(record.pk, {'invoice_reference': '000-CONCURRENT-INV', 'invoiced_on': timezone.localdate()}, actor=User.objects.get(pk=self.finance.pk)).pk
            finally:
                connections.close_all()
        def close():
            close_old_connections()
            try:
                close_started.set()
                return close_disposition(record.pk, actor=User.objects.get(pk=self.manager.pk)).pk
            finally:
                connections.close_all()
        with patch('core.disposition_workflow._audit', side_effect=controlled_audit), ThreadPoolExecutor(max_workers=2) as pool:
            billed = pool.submit(invoice)
            self.assertTrue(finance_paused.wait(timeout=10))
            closed = pool.submit(close)
            self.assertTrue(close_started.wait(timeout=10))
            self.assertFalse(closed.done())
            release_finance.set()
            self.assertEqual(billed.result(timeout=30), record.pk)
            self.assertEqual(closed.result(timeout=30), record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, 'closed')
        self.assertTrue(DispositionProcess.objects.get(service_request=record).finance_validated_at)
