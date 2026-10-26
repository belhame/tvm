"""Independent dispatch/quote security checks; every record here is fictional."""

from datetime import date
from io import BytesIO
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest


def pdf_text(data):
    return ' '.join(' '.join(page.extract_text() or '' for page in PdfReader(BytesIO(data)).pages).split())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentDispositionReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Laboratoire Sorties Fictif', contact_name='Contact devis fictif', tax_id='00000042/FICTIF', address='Adresse de laboratoire', notes='PRIVATE_CLIENT_NOTE_DISPOSITION')
        cls.other_company = Client.objects.create(name='Autre Centre Sorties Fictif')
        cls.admin = User.objects.create_user('PRIVATE_DISPOSITION_APPROVER', role='admin')
        cls.manager = User.objects.create_user('disposition-review-manager', role='manager')
        cls.tech = User.objects.create_user('disposition-review-tech', role='technician')
        cls.finance = User.objects.create_user('PRIVATE_DISPOSITION_FINANCE', role='technician', can_validate_billing=True)
        cls.customer = User.objects.create_user('disposition-review-client', role='client', client=cls.company)
        cls.other_customer = User.objects.create_user('disposition-review-other-client', role='client', client=cls.other_company)
        cls.original = Equipment.objects.create(client=cls.company, serial_number='DISPOSITION-ORIGINAL-FICTION', model='Onduleur fictif')
        cls.foreign = Equipment.objects.create(client=cls.other_company, serial_number='DISPOSITION-FOREIGN-FICTION', model='Autre onduleur fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.request = self.new_request()

    def new_request(self, **changes):
        fields = dict(equipment=self.original, subject='Dossier de sortie fictif', status='testing', assigned_technician=self.tech, client_reference='000042-CLIENT-FICTIF')
        fields.update(changes)
        return ServiceRequest.objects.create(**fields)

    def url(self, action='', record=None):
        return f'/api/requests/{(record or self.request).pk}/disposition/' + (f'{action}/' if action else '')

    def post(self, action, data=None, record=None):
        return self.api.post(self.url(action, record), {} if data is None else data, format='json')

    def irreparable(self, *, mode='billable', record=None):
        response = self.post('nonrepairable', {'diagnosis': 'DIAGNOSTIC_PUBLIC_FICTIF', 'fee_mode': mode, 'free_reason': 'PRIVATE_FREE_PROPOSAL_FICTION' if mode == 'free' else ''}, record)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def prices(self, *, amount='10.005', vat='19.00', currency='TND', record=None):
        response = self.api.patch(self.url(record=record), {'price_ht': amount, 'vat_rate': vat, 'currency': currency, 'quote_notes': 'Condition commerciale fictive'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def issue(self, *, record=None):
        response = self.post('quote/issue', record=record)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(response.data['disposition']['quote'])
        return response.data['disposition']['quote']

    def billable_quote(self, *, record=None, amount='10.005', vat='19.00'):
        self.irreparable(record=record)
        self.prices(record=record, amount=amount, vat=vat)
        return self.issue(record=record)

    def test_new_ready_status_requires_explicit_repair_tests_in_every_write_path(self):
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {
            'status': 'ready_for_delivery',
            'disposition': {'outcome': 'repaired', 'tests_passed': True, 'tested_on': '2025-10-15', 'classified_at': '2025-10-15T10:00:00Z'},
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        response = self.api.post(f'/api/requests/{self.request.pk}/timeline/', {'kind': 'status_changed', 'status_after': 'ready_for_delivery'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.request.status = 'ready_for_delivery'
        with self.assertRaises(ValidationError):
            self.request.save(update_fields=['status'])
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'testing')

    def test_repaired_outcome_requires_true_tests_and_actual_date_without_fake_visit(self):
        for body in (
            {'diagnosis': 'Réparation fictive', 'tests_passed': False, 'tested_on': '2025-10-15'},
            {'diagnosis': 'Réparation fictive', 'tests_passed': 'true', 'tested_on': '2025-10-15'},
            {'diagnosis': 'Réparation fictive', 'tests_passed': 1, 'tested_on': '2025-10-15'},
            {'diagnosis': 'Réparation fictive', 'tests_passed': True},
            {'diagnosis': '', 'tests_passed': True, 'tested_on': '2025-10-15'},
            {'diagnosis': 'Réparation fictive', 'tests_passed': True, 'tested_on': '2999-10-15'},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post('repair', body).status_code, 400)
        self.api.force_authenticate(self.tech)
        response = self.post('repair', {'diagnosis': 'Réparation et tests fictifs réussis', 'tests_passed': True, 'tested_on': '2025-10-15'})
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'ready_for_delivery')
        self.assertTrue(response.data['disposition']['tests_passed'])
        self.assertEqual(Intervention.objects.filter(service_request=self.request).count(), 0)

    def test_legacy_ready_read_stays_unchanged_and_dispatch_uses_actual_status(self):
        from core.models import DispositionProcess

        legacy = self.new_request(subject='Ancien dossier prêt fictif')
        ServiceRequest.objects.filter(pk=legacy.pk).update(status='ready_for_delivery')
        legacy.refresh_from_db()
        before = DispositionProcess.objects.count(), OperationEvent.objects.count(), Intervention.objects.count()
        response = self.api.get('/api/dispatch/ready/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data], [legacy.pk])
        detail = self.api.get(self.url(record=legacy))
        self.assertEqual(detail.status_code, 200, detail.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, 'ready_for_delivery')
        self.assertEqual((DispositionProcess.objects.count(), OperationEvent.objects.count(), Intervention.objects.count()), before)

    def test_ready_queue_combines_tested_repairs_and_ready_exchanges_without_guessing(self):
        response = self.post('repair', {'diagnosis': 'Réparation fictive réussie', 'tests_passed': True, 'tested_on': '2025-10-15'})
        self.assertEqual(response.status_code, 200, response.data)
        exchange = self.new_request(subject='Échange groupé fictif', status='exchange', assigned_technician=None)
        base = f'/api/requests/{exchange.pk}/exchange/'
        prepared = self.api.patch(base, {'replacement_serial_number': 'DISPATCH-NEW-EXCHANGE-FICTION', 'replacement_model': 'Remplacement fictif'}, format='json')
        self.assertEqual(prepared.status_code, 200, prepared.data)
        response = self.api.post(base + 'validate/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'exchange')
        ready = self.api.get('/api/dispatch/ready/')
        self.assertEqual([row['id'] for row in ready.data], [self.request.pk])
        response = self.api.post(base + 'validate/', {'mark_ready': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'ready_for_delivery')
        ready = self.api.get('/api/dispatch/ready/')
        self.assertEqual({row['id']: row['dispatch_kind'] for row in ready.data}, {self.request.pk: 'repair', exchange.pk: 'exchange'})
        self.assertFalse(Intervention.objects.filter(service_request=exchange).exists())

    def test_combined_exchange_validation_and_readiness_roll_back_together_on_failure(self):
        exchange = self.new_request(subject='Échange atomique fictif', status='exchange', assigned_technician=None)
        base = f'/api/requests/{exchange.pk}/exchange/'
        response = self.api.patch(base, {'replacement_serial_number': 'DISPATCH-ROLLBACK-FICTION', 'replacement_model': 'Remplacement fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        with patch('core.exchange_views.ready_exchange', side_effect=ValidationError('Synthetic readiness failure')):
            response = self.api.post(base + 'validate/', {'mark_ready': True}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Equipment.objects.filter(serial_number='DISPATCH-ROLLBACK-FICTION').exists())
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, 'exchange')
        self.assertIsNone(exchange.exchange_process.validated_at)
        self.assertFalse(OperationEvent.objects.filter(service_request=exchange, kind='exchange_validated').exists())

    def test_irreparable_cannot_become_ready_or_close_via_generic_detours(self):
        self.irreparable()
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'return_to_client')
        for status in ('ready_for_delivery', 'pending', 'closed'):
            response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': status}, format='json')
            if status == 'pending':
                self.assertIn(response.status_code, (200, 400), response.data)
            else:
                self.assertEqual(response.status_code, 400, response.data)
        response = self.api.post(f'/api/requests/{self.request.pk}/timeline/', {'kind': 'status_changed', 'status_after': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.request.status = 'closed'
        with self.assertRaises(ValidationError):
            self.request.save(update_fields=['status'])
        self.request.refresh_from_db()
        self.assertNotEqual(self.request.status, 'closed')
        self.assertIsNone(self.request.closed_at)

    def test_reset_does_not_erase_the_existing_diagnostic_finance_requirement(self):
        self.irreparable()
        response = self.post('reset', {'reason': 'Nouvelle vérification fictive'})
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        self.assertTrue(self.request.disposition_process.requires_diagnostic_billing)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_missing_explicit_vat_cannot_issue_a_quote(self):
        from core.models import DiagnosticQuote

        self.irreparable()
        response = self.api.patch(self.url(), {'price_ht': '10.005'}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        self.assertEqual(self.post('quote/issue').status_code, 400)
        self.assertFalse(DiagnosticQuote.objects.exists())

    def test_money_rejects_nonfinite_negative_exponent_unknown_currency_and_excess_precision(self):
        self.irreparable()
        valid = {'price_ht': '10.005', 'vat_rate': '19.00', 'currency': 'TND'}
        for field, value in (
            ('price_ht', 'NaN'), ('price_ht', 'Infinity'), ('price_ht', '-0.001'),
            ('price_ht', '1e3'), ('price_ht', True), ('price_ht', '1.0001'),
            ('vat_rate', 'NaN'), ('vat_rate', '-1'), ('vat_rate', '100.01'),
            ('vat_rate', '19.001'), ('currency', 'UNSUPPORTED'),
        ):
            with self.subTest(field=field, value=value):
                response = self.api.patch(self.url(), {**valid, field: value}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.disposition_process.current_quote_id)

    def test_tnd_quote_values_use_three_decimal_places_without_float_rounding(self):
        quote = self.billable_quote()
        self.assertEqual(quote['price_ht'], '10.005')
        self.assertEqual(quote['vat_amount'], '1.901')
        self.assertEqual(quote['total_ttc'], '11.906')
        self.assertEqual(quote['currency'], 'TND')

    def test_currency_change_never_silently_rounds_an_existing_draft_and_eur_round_trips(self):
        self.irreparable()
        self.prices()
        response = self.api.patch(self.url(), {'currency': 'EUR'}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        if response.status_code == 200:
            self.assertEqual(self.post('quote/issue').status_code, 400)
        self.prices(amount='19.99', vat='19.00', currency='EUR')
        quote = self.issue()
        self.assertEqual(quote['price_ht'], '19.99')
        self.assertEqual(quote['vat_amount'], '3.80')
        self.assertEqual(quote['total_ttc'], '23.79')
        self.assertEqual(quote['currency'], 'EUR')

    def test_zero_billable_quote_is_not_implicit_free_approval(self):
        self.irreparable()
        self.prices(amount='0.000', vat='0.00')
        # A zero billable draft may be rejected as inconsistent, or remain an
        # explicit zero quote. Neither interpretation grants a free approval.
        response = self.post('quote/issue')
        self.assertIn(response.status_code, (200, 400), response.data)
        self.api.force_authenticate(self.finance)
        self.assertEqual(self.post('free', {'reason': 'Tentative de gratuité sur devis facturable'}).status_code, 400)
        self.assertEqual(self.post('close').status_code, 400)
        self.request.refresh_from_db()
        self.assertNotEqual(self.request.status, 'closed')

    def test_free_requires_issued_zero_quote_explicit_reason_and_financial_permission(self):
        self.irreparable(mode='free')
        response = self.api.patch(self.url(), {'price_ht': '1.000', 'vat_rate': '0.00', 'currency': 'TND'}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        if response.status_code == 200:
            self.assertEqual(self.post('quote/issue').status_code, 400)
        self.prices(amount='0.000', vat='0.00')
        self.issue()
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.post('free', {'reason': 'Motif de gratuité fictif'}).status_code, 403)
        self.api.force_authenticate(self.finance)
        self.assertEqual(self.post('free', {'reason': ''}).status_code, 400)
        response = self.post('free', {'reason': 'PRIVATE_FREE_APPROVAL_FICTION'})
        self.assertEqual(response.status_code, 200, response.data)
        response = self.post('close')
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'closed')

    def test_finance_fields_forged_in_generic_request_do_not_unlock_closure(self):
        self.billable_quote()
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'disposition': {
            'fee_mode': 'free', 'finance_validated_at': '2025-10-15T10:00:00Z',
            'finance_free_reason': 'FORGED', 'invoice_reference': 'FORGED', 'invoiced_on': '2025-10-15',
        }}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        self.assertEqual(self.post('close').status_code, 400)
        self.api.force_authenticate(self.finance)
        response = self.post('invoice', {'invoice_reference': 'PRIVATE-DIAGNOSTIC-INVOICE', 'invoiced_on': '2025-10-15', 'billing_notes': 'PRIVATE_DIAGNOSTIC_FINANCE_NOTES'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.post('close').status_code, 200)

    def test_issued_quote_is_immutable_at_api_and_model_boundaries(self):
        from core.models import DiagnosticQuote

        reference = self.billable_quote()
        quote = DiagnosticQuote.objects.get(pk=reference['id'])
        before = json.loads(json.dumps(quote.snapshot))
        for change in ({'price_ht': '0.000', 'vat_rate': '0.00'}, {'diagnosis': 'Diagnostic remplacé'}, {'currency': 'USD'}, {'fee_mode': 'free'}):
            response = self.api.patch(self.url(), change, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.post('reset', {'reason': 'Tentative après émission'}).status_code, 400)
        quote.snapshot = {**quote.snapshot, 'price_ht': '0.000'}
        with self.assertRaises((ValidationError, DjangoValidationError)):
            quote.save(update_fields=['snapshot'])
        quote.refresh_from_db()
        self.assertEqual(quote.snapshot, before)

    def test_quote_pdf_uses_issued_snapshot_and_never_private_notes_or_actors(self):
        quote = self.billable_quote()
        first = self.api.get(quote['pdf_url'])
        self.assertEqual(first.status_code, 200)
        original = pdf_text(first.content)
        for value in ('DIAGNOSTIC_PUBLIC_FICTIF', self.company.name, self.original.serial_number, self.request.reference, '000042-CLIENT-FICTIF', '11.906'):
            self.assertIn(value, original)
        Client.objects.filter(pk=self.company.pk).update(name='Nom société modifié après émission', contact_name='Nouveau contact')
        ServiceRequest.objects.filter(pk=self.request.pk).update(client_reference='REF-CHANGEE-APRES-EMISSION')
        second = self.api.get(quote['pdf_url'])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(pdf_text(second.content), original)
        for private in ('PRIVATE_CLIENT_NOTE_DISPOSITION', self.admin.username, 'PRIVATE_FREE_PROPOSAL_FICTION', 'PRIVATE_DIAGNOSTIC_FINANCE_NOTES'):
            self.assertNotIn(private, original)

    def test_issued_quote_cannot_be_reparented_to_another_client_through_model_or_api(self):
        self.billable_quote()
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'equipment': self.foreign.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.equipment = self.foreign
        with self.assertRaises(ValidationError):
            self.request.save(update_fields=['equipment'])
        self.request.refresh_from_db()
        self.assertEqual(self.request.equipment_id, self.original.pk)
        self.original.client = self.other_company
        with self.assertRaises(ValidationError):
            self.original.save(update_fields=['client'])
        self.original.refresh_from_db()
        self.assertEqual(self.original.client_id, self.company.pk)

    def test_portal_quotes_are_issued_only_owner_scoped_and_hide_finance_details(self):
        self.irreparable()
        self.prices()
        self.api.force_authenticate(self.customer)
        preview = self.api.get(self.url())
        self.assertEqual(preview.status_code, 200, preview.data)
        disposition = preview.data['disposition']
        self.assertNotIn('price_ht', disposition)
        self.assertNotIn('vat_rate', disposition)
        self.assertNotIn('quote_notes', disposition)
        self.api.force_authenticate(self.admin)
        quote = self.issue()
        self.api.force_authenticate(self.finance)
        self.assertEqual(self.post('invoice', {'invoice_reference': 'PRIVATE-DIAGNOSTIC-INVOICE', 'invoiced_on': '2025-10-15', 'billing_notes': 'PRIVATE_DIAGNOSTIC_FINANCE_NOTES'}).status_code, 200)
        self.api.force_authenticate(self.customer)
        response = self.api.get(quote['pdf_url'])
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        detail = self.api.get(self.url())
        for key in ('invoice_reference', 'invoiced_on', 'billing_notes', 'finance_free_reason', 'finance_validated_by'):
            self.assertNotIn(key, detail.data['disposition'])
        timeline = self.api.get(f'/api/requests/{self.request.pk}/timeline/')
        for private in ('PRIVATE-DIAGNOSTIC-INVOICE', 'PRIVATE_DIAGNOSTIC_FINANCE_NOTES', self.finance.username, self.admin.username):
            self.assertNotIn(private, str(timeline.data))
            self.assertNotIn(private, pdf_text(response.content))
        self.api.force_authenticate(self.other_customer)
        self.assertEqual(self.api.get(quote['pdf_url']).status_code, 404)
        self.assertEqual(self.api.get(self.url()).status_code, 404)
        self.api.force_authenticate(None)
        self.assertIn(self.api.get(quote['pdf_url']).status_code, (401, 403))

    def test_exchange_invoice_obligation_cannot_be_replaced_by_diagnostic_gratuity(self):
        exchange = self.new_request(subject='Échange fictif distinct', status='exchange', assigned_technician=None)
        response = self.post('nonrepairable', {'diagnosis': 'Diagnostic fictif', 'fee_mode': 'free', 'free_reason': 'Tentative de gratuité'}, exchange)
        self.assertEqual(response.status_code, 400, response.data)
        self.api.force_authenticate(self.finance)
        self.assertEqual(self.post('free', {'reason': 'Tentative de gratuité'}, exchange).status_code, 400)
        self.assertEqual(self.post('close', record=exchange).status_code, 400)
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.patch(f'/api/requests/{exchange.pk}/', {'status': 'closed'}, format='json').status_code, 400)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
class IndependentDispositionConcurrencyReviewTests(TransactionTestCase):
    def test_qualification_waits_for_an_identity_change_already_past_its_guard(self):
        from core import disposition_workflow

        company = Client.objects.create(name='Laboratoire Concurrence Qualification Fictif')
        actor = get_user_model().objects.create_user('qualification-concurrency-review', role='manager')
        unit = Equipment.objects.create(client=company, serial_number='QUALIFICATION-CONCURRENT-FICTION', model='Modèle initial fictif')
        record = ServiceRequest.objects.create(equipment=unit, subject='Qualification concurrente fictive', status='testing')
        identity_guard_passed = Event()
        release_identity_write = Event()
        qualification_boundary = Event()
        qualification_completed = Event()
        real_guard = disposition_workflow.guard_disposition_equipment_update

        def paused_identity_guard(instance, update_fields=None):
            result = real_guard(instance, update_fields)
            if instance.pk == unit.pk:
                identity_guard_passed.set()
                if not release_identity_write.wait(timeout=15):
                    raise TimeoutError('Synthetic identity write was not released.')
            return result

        def mutate_identity():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                current = Equipment.objects.get(pk=unit.pk)
                current.model = 'Modèle corrigé avant qualification'
                current.save(update_fields=['model'])
            finally:
                connections.close_all()

        def qualify():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")

                def observe_lock(execute, sql, params, many, context):
                    if 'core_equipment' in sql and 'FOR' in sql.upper() and 'UPDATE' in sql.upper():
                        qualification_boundary.set()
                    return execute(sql, params, many, context)

                with connection.execute_wrapper(observe_lock):
                    disposition_workflow.mark_repaired(record.pk, {
                        'diagnosis': 'Tests fictifs réussis', 'tests_passed': True,
                        'tested_on': date(2025, 10, 15),
                    }, actor=get_user_model().objects.get(pk=actor.pk))
            finally:
                qualification_completed.set()
                qualification_boundary.set()
                connections.close_all()

        with patch('core.disposition_workflow.guard_disposition_equipment_update', side_effect=paused_identity_guard), ThreadPoolExecutor(max_workers=2) as pool:
            mutation = pool.submit(mutate_identity)
            try:
                self.assertTrue(identity_guard_passed.wait(timeout=10))
                qualification = pool.submit(qualify)
                self.assertTrue(qualification_boundary.wait(timeout=10))
                # A qualifier without the unit lock can finish while the old
                # write is paused, then that write alters an approved identity.
                approved_before_identity_write = qualification_completed.is_set()
            finally:
                release_identity_write.set()
            mutation.result(timeout=20)
            qualification.result(timeout=20)
        self.assertFalse(approved_before_identity_write)
        unit.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(unit.model, 'Modèle corrigé avant qualification')
        self.assertEqual(record.status, 'ready_for_delivery')
        self.assertEqual(record.disposition_process.outcome, 'repaired')
