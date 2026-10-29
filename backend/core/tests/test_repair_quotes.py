from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader
from rest_framework.test import APIClient

from core.disposition_models import DispositionProcess
from core.models import Client, Equipment, Intervention, OperationEvent, Part, ServiceRequest, StockMovement
from core.notification_models import InAppNotification
from core.notification_service import notification_payload
from core.repair_quote_models import RepairQuote, RepairQuoteBook, RepairQuoteDecision
from core.repair_quote_service import QuoteConflict, create_draft, decide_quote, issue_quote, quote_payload

User = get_user_model()
BASE = '/api/repair-quotes/'


class QuoteFactory:
    def fixture(self):
        self.manager = User.objects.create_user('repair-manager', role='manager')
        self.customer_company = Client.objects.create(name='Centre devis fictif', address='Adresse fictive', tax_id='TVA-FICTIVE', contact_name='Contact public', email='public@example.test', phone='001122')
        self.customer = User.objects.create_user('repair-customer', role='client', client=self.customer_company)
        self.tech = User.objects.create_user('repair-technician', role='technician')
        self.equipment = Equipment.objects.create(client=self.customer_company, serial_number='REPAIR-SYNTHETIC-001', brand='Laboratoire', model='UPS synthétique')
        self.record = ServiceRequest.objects.create(equipment=self.equipment, subject='SAV synthétique', warranty_status='quotation', client_reference='000-RX', description='PRIVATE_REQUEST_DESCRIPTION')

    def draft(self, **extra):
        data = {'service_request': self.record.pk, 'request_key': str(uuid4()),
                'lines': [{'description': 'Réparation synthétique', 'quantity': '2', 'unit_ht': '100.000'}],
                'currency': 'TND', 'vat_rate': '19', 'discount_kind': 'percent', 'discount_value': '10', 'terms': 'Conditions publiques', **extra}
        quote, _ = create_draft(self.manager, **data)
        return quote

    def issued(self):
        quote = self.draft()
        return issue_quote(self.manager, quote.pk, request_key=uuid4(), expected_revision=quote.revision)[0]

    def choose(self, quote, decision='accepted', **extra):
        return decide_quote(self.customer, quote.pk, request_key=uuid4(), expected_revision=RepairQuoteBook.objects.get(pk=quote.book_id).decision_revision, decision=decision, **extra)[0]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RepairQuoteTests(QuoteFactory, TestCase):
    def setUp(self):
        self.fixture()
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def test_public_snapshot_real_pdf_discount_and_no_financial_effect(self):
        part = Part.objects.create(sku='REPAIR-STOCK', name='Pièce fictive', stock_quantity=4)
        quote = self.issued()
        self.assertEqual(quote.amounts['subtotal_ht'], '200.000')
        self.assertEqual(quote.amounts['discount_ht'], '20.000')
        self.assertEqual(quote.amounts['net_ht'], '180.000')
        self.assertEqual(quote.amounts['vat_amount'], '34.200')
        self.assertEqual(quote.amounts['total_ttc'], '214.200')
        self.api.force_authenticate(self.customer)
        first = self.api.get(f'{BASE}{quote.pk}/pdf/')
        second = self.api.get(f'{BASE}{quote.pk}/pdf/')
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.content, second.content)
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(first.content)).pages)
        self.assertIn('REPAIR-SYNTHETIC-001', text)
        self.assertNotIn('PRIVATE_REQUEST_DESCRIPTION', text)
        self.assertEqual(quote.snapshot['client']['tax_id'], 'TVA-FICTIVE')
        self.assertFalse(DispositionProcess.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(Intervention.objects.exists())
        part.refresh_from_db()
        self.assertEqual(part.stock_quantity, 4)

    def test_current_client_opinion_can_reverse_repeatedly_and_is_append_only(self):
        quote = self.issued()
        self.choose(quote)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'approved')
        self.choose(quote, 'refused')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'rejected')
        self.choose(quote, 'accepted')
        data = quote_payload(RepairQuote.objects.select_related('book__service_request__equipment', 'book__current_decision', 'client').get(pk=quote.pk), self.customer)
        self.assertEqual([row['decision'] for row in data['history']], ['accepted', 'refused', 'accepted'])
        self.assertEqual(data['decision'], 'accepted')
        self.assertEqual(OperationEvent.objects.filter(kind='repair_quote_decision', service_request=self.record).count(), 3)

    def test_draft_does_not_cancel_agreement_new_issue_does_even_same_price(self):
        first = self.issued()
        self.choose(first)
        second = self.draft()
        book = RepairQuoteBook.objects.get(pk=first.book_id)
        self.assertEqual(book.current_quote_id, first.pk)
        self.assertEqual(book.current_decision.decision, 'accepted')
        issue_quote(self.manager, second.pk, request_key=uuid4(), expected_revision=0)
        book.refresh_from_db()
        self.assertEqual(book.current_quote_id, second.pk)
        self.assertIsNone(book.current_decision_id)
        self.assertTrue(RepairQuoteDecision.objects.filter(quote=first, decision='accepted').exists())
        with self.assertRaises(QuoteConflict):
            decide_quote(self.customer, first.pk, request_key=uuid4(), expected_revision=book.decision_revision, decision='accepted')
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get(f'{BASE}{first.pk}/pdf/').status_code, 200)

    def test_cas_and_all_three_transport_replays_do_not_duplicate(self):
        key = uuid4()
        first = self.draft(request_key=str(key))
        replay = self.draft(request_key=str(key))
        self.assertEqual(first.pk, replay.pk)
        issue_key = uuid4()
        issued, created = issue_quote(self.manager, first.pk, request_key=issue_key, expected_revision=0)
        again, repeated = issue_quote(self.manager, first.pk, request_key=issue_key, expected_revision=0)
        self.assertTrue(created)
        self.assertFalse(repeated)
        revision = issued.book.decision_revision
        decision_key = uuid4()
        decide_quote(self.customer, issued.pk, request_key=decision_key, expected_revision=revision, decision='accepted')
        decide_quote(self.customer, issued.pk, request_key=decision_key, expected_revision=revision, decision='accepted')
        self.assertEqual(RepairQuoteDecision.objects.count(), 1)
        with self.assertRaises(QuoteConflict):
            decide_quote(self.customer, issued.pk, request_key=uuid4(), expected_revision=revision, decision='refused')
        with self.assertRaises(QuoteConflict):
            decide_quote(self.customer, issued.pk, request_key=decision_key, expected_revision=revision, decision='refused')

    def test_already_performed_states_and_finance_remain_intact_on_change_of_mind(self):
        quote = self.issued()
        for status in ('maintenance', 'testing', 'resolved', 'ready_for_delivery', 'return_to_client', 'closed'):
            with self.subTest(status=status):
                ServiceRequest.objects.filter(pk=self.record.pk).update(status=status)
                self.choose(quote, 'accepted')
                self.choose(quote, 'refused')
                self.record.refresh_from_db()
                self.assertEqual(self.record.status, status)
                self.assertFalse(RepairQuoteDecision.objects.order_by('-pk').first().status_changed)
        self.assertFalse(DispositionProcess.objects.exists())

    def test_legacy_commercial_status_with_real_intervention_is_not_rewound(self):
        quote = self.issued()
        Intervention.objects.create(service_request=self.record, technician=self.tech, status='completed', completed_at=timezone.now())
        ServiceRequest.objects.filter(pk=self.record.pk).update(status='quotation')
        self.choose(quote)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quotation')

    def test_real_commit_only_notices_are_deduplicated_and_private_after_role_change(self):
        with self.captureOnCommitCallbacks(execute=True):
            quote = self.issued()
        client_notice = InAppNotification.objects.get(recipient=self.customer, kind='repair_quote')
        self.assertEqual(notification_payload(client_notice, self.customer)['target_id'], quote.pk)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.manager, kind='repair_quote').count(), 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.choose(quote)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.manager, kind='repair_quote').count(), 1)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.tech, kind='repair_quote').count(), 0)
        from core.repair_quote_service import send_quote_notices
        send_quote_notices(quote.pk, 'issued', quote.pk)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.customer, kind='repair_quote').count(), 1)
        self.customer.role, self.customer.client_id = 'technician', None
        self.customer.save()
        payload = notification_payload(client_notice, self.customer)
        self.assertFalse(payload['actionable'])
        self.assertEqual(payload['details'], {})

    def test_rollback_never_notifies_or_keeps_half_issued_quote(self):
        quote = self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    issue_quote(self.manager, quote.pk, request_key=uuid4(), expected_revision=0)
                    raise RuntimeError('Rollback deliberately')
            except RuntimeError:
                pass
        quote.refresh_from_db()
        self.assertEqual(quote.state, 'draft')
        self.assertFalse(InAppNotification.objects.exists())
        self.assertFalse(OperationEvent.objects.filter(kind='repair_quote_issued').exists())

    def test_edit_cas_and_unknown_fields_are_strict(self):
        quote = self.draft()
        edit = self.api.patch(f'{BASE}{quote.pk}/', {'expected_revision': 0, 'discount_kind': 'fixed', 'discount_value': '30.000'}, format='json')
        self.assertEqual(edit.status_code, 200, edit.data)
        self.assertEqual(edit.data['revision'], 1)
        self.assertEqual(edit.data['amounts']['net_ht'], '170.000')
        stale = self.api.patch(f'{BASE}{quote.pk}/', {'expected_revision': 0, 'terms': 'Stale'}, format='json')
        self.assertEqual(stale.status_code, 409)
        forged = self.api.patch(f'{BASE}{quote.pk}/', {'expected_revision': 1, 'state': 'issued'}, format='json')
        self.assertEqual(forged.status_code, 400)
        malformed = self.api.patch(f'{BASE}{quote.pk}/', {'expected_revision': True, 'terms': 'X'}, format='json')
        self.assertEqual(malformed.status_code, 400)

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL SQL triggers')
    def test_issued_content_pdf_and_decisions_are_immutable_even_raw_sql(self):
        quote = self.issued()
        self.choose(quote)
        decision = RepairQuoteDecision.objects.get(quote=quote)
        for sql, params in [
            ('UPDATE core_repairquote SET terms=%s WHERE id=%s', ['Forged', quote.pk]),
            ('UPDATE core_repairquote SET pdf_data=%s WHERE id=%s', [b'Fake', quote.pk]),
            ('DELETE FROM core_repairquote WHERE id=%s', [quote.pk]),
            ('UPDATE core_repairquotedecision SET decision=%s WHERE id=%s', ['refused', decision.pk]),
            ('DELETE FROM core_repairquotedecision WHERE id=%s', [decision.pk]),
        ]:
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, params)

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL SQL current revision guards')
    def test_sql_cannot_reactivate_an_old_quote_or_erase_current_client_opinion(self):
        first = self.issued()
        self.choose(first)
        second = self.draft()
        issue_quote(self.manager, second.pk, request_key=uuid4(), expected_revision=0)
        self.choose(second)
        book = RepairQuoteBook.objects.get(pk=first.book_id)
        for sql, params in [
            ('UPDATE core_repairquotebook SET current_quote_id=%s,current_decision_id=NULL,decision_revision=decision_revision+1 WHERE id=%s', [first.pk, book.pk]),
            ('UPDATE core_repairquotebook SET current_quote_id=NULL,current_decision_id=NULL,decision_revision=decision_revision+1 WHERE id=%s', [book.pk]),
            ('UPDATE core_repairquotebook SET current_decision_id=NULL WHERE id=%s', [book.pk]),
        ]:
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, params)
        book.refresh_from_db()
        self.assertEqual(book.current_quote_id, second.pk)
        self.assertIsNotNone(book.current_decision_id)


@skipUnless(connection.vendor == 'postgresql', 'Real PostgreSQL row locking')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RepairQuoteConcurrencyTests(QuoteFactory, TransactionTestCase):
    def setUp(self):
        self.fixture()

    def race(self, functions):
        gate = Barrier(len(functions))
        def run(function):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                gate.wait(timeout=10)
                function()
                return 'saved'
            except QuoteConflict:
                return 'conflict'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions))

    def test_two_simultaneous_decisions_have_one_winner(self):
        quote = self.issued()
        revision = quote.book.decision_revision
        results = self.race([lambda: decide_quote(self.customer, quote.pk, request_key=uuid4(), expected_revision=revision, decision='accepted'),
                             lambda: decide_quote(self.customer, quote.pk, request_key=uuid4(), expected_revision=revision, decision='refused')])
        self.assertCountEqual(results, ['saved', 'conflict'])
        self.assertEqual(RepairQuoteDecision.objects.count(), 1)

    def test_concurrent_same_creation_key_returns_one_identical_draft(self):
        key = uuid4()
        results = self.race([lambda: self.draft(request_key=str(key)), lambda: self.draft(request_key=str(key))])
        self.assertEqual(results, ['saved', 'saved'])
        self.assertEqual(RepairQuote.objects.count(), 1)

    def test_reissue_and_old_decision_never_transfer_acceptance_to_new_price(self):
        first = self.issued()
        second = self.draft()
        revision = first.book.decision_revision
        results = self.race([lambda: issue_quote(self.manager, second.pk, request_key=uuid4(), expected_revision=0),
                             lambda: decide_quote(self.customer, first.pk, request_key=uuid4(), expected_revision=revision, decision='accepted')])
        self.assertEqual(results[0], 'saved')
        book = RepairQuoteBook.objects.get(pk=first.book_id)
        self.assertEqual(book.current_quote_id, second.pk)
        self.assertIsNone(book.current_decision_id)
