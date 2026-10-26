"""Independent exchange-workflow/report review with fictional records only."""

from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client as BrowserClient, TestCase, override_settings
from pypdf import PdfReader
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.pdf import intervention_report, service_request_report


def pdf_text(data):
    return ' '.join(' '.join(page.extract_text() or '' for page in PdfReader(BytesIO(data)).pages).split())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentExchangeReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Laboratoire Échange Fictif', notes='PRIVATE_CLIENT_NOTES_EXCHANGE')
        cls.other_company = Client.objects.create(name='Autre Laboratoire Fictif')
        cls.admin = User.objects.create_user('PRIVATE_EXCHANGE_VALIDATOR', role='admin')
        cls.tech = User.objects.create_user('exchange-public-tech', first_name='Technicien', last_name='Public', role='technician')
        cls.customer = User.objects.create_user('exchange-report-client', role='client', client=cls.company)
        cls.original = Equipment.objects.create(client=cls.company, serial_number='EXCHANGE-ORIGINAL-FICTION', model='Original fictif')
        cls.replacement = Equipment.objects.create(client=cls.company, serial_number='EXCHANGE-REPLACEMENT-FICTION', model='Remplacement fictif')
        cls.foreign = Equipment.objects.create(client=cls.other_company, serial_number='FOREIGN-EXCHANGE-FICTION', model='Autre modèle')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        response = self.api.post('/api/requests/', {'equipment': self.original.pk, 'subject': 'Échange de laboratoire', 'status': 'exchange'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.request = ServiceRequest.objects.get(pk=response.data['id'])

    def action(self, suffix, data=None):
        return self.api.post(f'/api/requests/{self.request.pk}/exchange/{suffix}/', data or {}, format='json')

    def prepare(self):
        response = self.api.patch(f'/api/requests/{self.request.pk}/exchange/', {
            'replacement_equipment': self.replacement.pk,
            'replacement_serial_number': self.replacement.serial_number,
            'replacement_model': self.replacement.model,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def validate_and_ready(self):
        self.prepare()
        response = self.action('validate')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.action('ready')
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()

    def confirm_billing(self):
        response = self.action('billing', {'invoice_reference': 'PRIVATE-INVOICE-000042', 'invoiced_on': '2025-10-15', 'billing_notes': 'PRIVATE_FINANCE_NOTES_EXCHANGE'})
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()

    def visit(self, **changes):
        data = dict(service_request=self.request, technician=self.tech, kind='exchange', status='completed', performed_on=date(2025, 10, 15), replacement_equipment=self.replacement, work_done='Échange matériel fictif', internal_notes='PRIVATE_INTERVENTION_NOTES_EXCHANGE')
        data.update(changes)
        return Intervention.objects.create(**data)

    def test_legacy_completed_visit_is_not_a_technical_or_billing_approval(self):
        visit = self.visit()
        for content in (intervention_report(visit), service_request_report(self.request)):
            text = pdf_text(content)
            self.assertIn('Validation technique Non enregistrée', text)
            self.assertIn('SN de remplacement validé Non enregistré', text)
            self.assertIn('Facturation Non confirmée', text)
            self.assertIn('ancienne fiche', text)
            self.assertNotIn('PRIVATE_INTERVENTION_NOTES_EXCHANGE', text)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_ready_nonexchange_repair_does_not_print_exchange_or_billing_requirements(self):
        ordinary = ServiceRequest.objects.create(equipment=self.original, subject='Réparation ordinaire fictive', status='ready_for_delivery')
        visit = Intervention.objects.create(service_request=ordinary, technician=self.tech, kind='maintenance', status='completed', work_done='Réparation fictive réalisée')
        for content in (intervention_report(visit), service_request_report(ordinary)):
            text = pdf_text(content)
            self.assertNotIn('VALIDATION ET FACTURATION', text)
            self.assertNotIn('Validation technique', text)
            self.assertNotIn('Référence de facture', text)
            self.assertNotIn('Facturation Non confirmée', text)

    def test_draft_serial_is_separate_and_absent_from_client_report(self):
        self.prepare()
        self.request.refresh_from_db()
        internal = pdf_text(service_request_report(self.request))
        public = pdf_text(service_request_report(self.request, for_client=True))
        self.assertIn('SN proposé, non validé', internal)
        self.assertIn(self.replacement.serial_number, internal)
        self.assertNotIn('SN proposé, non validé', public)
        self.assertNotIn(self.replacement.serial_number, public)
        self.assertIn('Validation technique Non enregistrée', public)

    def test_confirmed_facts_print_invoice_only_in_internal_copy_without_notes_or_actors(self):
        visit = self.visit()
        self.validate_and_ready()
        self.confirm_billing()
        visit.refresh_from_db()
        for builder, record in ((intervention_report, visit), (service_request_report, self.request)):
            internal = pdf_text(builder(record))
            public = pdf_text(builder(record, for_client=True))
            for text in (internal, public):
                self.assertIn('Validation technique Enregistrée le', text)
                self.assertIn('Prêt à livrer Confirmé le', text)
                self.assertIn('SN de remplacement validé', text)
                self.assertIn(self.replacement.serial_number, text)
                self.assertIn(self.original.serial_number, text)
                self.assertIn('Facturation Confirmée', text)
                self.assertIn('saisie manuellement', text)
                self.assertNotIn('PRIVATE_FINANCE_NOTES_EXCHANGE', text)
                self.assertNotIn('PRIVATE_INTERVENTION_NOTES_EXCHANGE', text)
                self.assertNotIn('PRIVATE_CLIENT_NOTES_EXCHANGE', text)
                self.assertNotIn(self.admin.username, text)
            self.assertIn('PRIVATE-INVOICE-000042', internal)
            self.assertIn('Date de facture 15/10/2025', internal)
            self.assertNotIn('PRIVATE-INVOICE-000042', public)
            self.assertNotIn('Référence de facture', public)
        self.original.refresh_from_db()
        self.assertEqual(self.original.serial_number, 'EXCHANGE-ORIGINAL-FICTION')

    def test_portal_pdf_and_timeline_do_not_expose_invoice_notes_or_new_actor_identities(self):
        visit = self.visit()
        self.validate_and_ready()
        self.confirm_billing()
        self.api.force_authenticate(self.customer)
        for url in (f'/api/requests/{self.request.pk}/report/', f'/api/interventions/{visit.pk}/report/'):
            response = self.api.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            text = pdf_text(response.content)
            self.assertIn('Facturation Confirmée', text)
            for private in ('PRIVATE-INVOICE-000042', 'PRIVATE_FINANCE_NOTES_EXCHANGE', 'PRIVATE_INTERVENTION_NOTES_EXCHANGE', self.admin.username):
                self.assertNotIn(private, text)
        timeline = self.api.get(f'/api/requests/{self.request.pk}/timeline/')
        self.assertEqual(timeline.status_code, 200)
        for event in timeline.data:
            self.assertEqual(event['actor_name'], 'Équipe SAV')
        for private in ('PRIVATE-INVOICE-000042', 'PRIVATE_FINANCE_NOTES_EXCHANGE', self.admin.username):
            self.assertNotIn(private, str(timeline.data))

    def test_generic_status_detour_cannot_erase_exchange_requirement(self):
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'pending'}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.assertNotEqual(self.request.status, 'closed')
        self.assertIsNone(self.request.closed_at)

    def test_timeline_status_detour_cannot_erase_exchange_requirement(self):
        endpoint = f'/api/requests/{self.request.pk}/timeline/'
        response = self.api.post(endpoint, {'kind': 'status_changed', 'status_after': 'maintenance'}, format='json')
        self.assertIn(response.status_code, (201, 400), response.data)
        response = self.api.post(endpoint, {'kind': 'status_changed', 'status_after': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.assertNotEqual(self.request.status, 'closed')

    def test_forged_workflow_json_and_ready_status_cannot_approve_or_close(self):
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {
            'exchange': {'validated_at': '2025-10-15T08:00:00Z', 'invoice_reference': 'FORGED', 'invoiced_on': '2025-10-15', 'billing_validated_at': '2025-10-15T08:01:00Z'},
            'status': 'ready_for_delivery',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.exchange_process.validated_at)
        self.assertIsNone(self.request.exchange_process.billing_validated_at)

    def test_validated_original_and_replacement_cannot_be_reassigned_or_renamed(self):
        self.validate_and_ready()
        for equipment in (self.original, self.replacement):
            for changes in ({'client': self.other_company.pk}, {'serial_number': f'ALTERED-{equipment.pk}'}, {'model': 'Modèle réécrit'}):
                with self.subTest(equipment=equipment.pk, changes=changes):
                    response = self.api.patch(f'/api/equipment/{equipment.pk}/', changes, format='json')
                    self.assertEqual(response.status_code, 400, response.data)
        self.original.refresh_from_db()
        self.replacement.refresh_from_db()
        self.assertEqual(self.original.serial_number, 'EXCHANGE-ORIGINAL-FICTION')
        self.assertEqual(self.replacement.serial_number, 'EXCHANGE-REPLACEMENT-FICTION')

    def test_changed_selected_replacement_before_validation_is_not_silently_recreated(self):
        self.prepare()
        self.replacement.serial_number = 'EXCHANGE-CHANGED-BEFORE-APPROVAL'
        self.replacement.save(update_fields=['serial_number'])
        count = Equipment.objects.count()
        response = self.action('validate')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Equipment.objects.count(), count)
        self.assertFalse(Equipment.objects.filter(serial_number='EXCHANGE-REPLACEMENT-FICTION').exists())
        self.request.refresh_from_db()
        self.assertIsNone(self.request.exchange_process.validated_at)

    def test_direct_model_save_cannot_reassign_origin_or_close_unbilled_exchange(self):
        self.validate_and_ready()
        self.request.equipment = self.replacement
        with self.assertRaises(ValidationError):
            self.request.save(update_fields=['equipment'])
        self.request.refresh_from_db()
        self.assertEqual(self.request.equipment_id, self.original.pk)
        self.request.status = 'closed'
        with self.assertRaises(ValidationError):
            self.request.save(update_fields=['status'])
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'ready_for_delivery')
        self.assertIsNone(self.request.closed_at)

    def test_direct_model_save_cannot_mutate_validated_equipment_identity(self):
        self.validate_and_ready()
        for equipment in (self.original, self.replacement):
            equipment.model = 'Identité altérée'
            with self.assertRaises(ValidationError):
                equipment.save(update_fields=['model'])
            equipment.refresh_from_db()
            self.assertNotEqual(equipment.model, 'Identité altérée')

    def test_forged_invoice_without_billing_action_does_not_unlock_closure(self):
        self.validate_and_ready()
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'exchange': {'invoice_reference': 'FORGED', 'invoiced_on': '2025-10-15', 'billing_validated_at': '2025-10-15T08:01:00Z'}}, format='json')
        self.assertIn(response.status_code, (200, 400), response.data)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.exchange_process.billing_validated_at)

    def test_portal_cannot_mutate_exchange_or_access_foreign_case(self):
        other_request = ServiceRequest.objects.create(equipment=self.foreign, subject='Autre échange fictif', status='exchange')
        self.api.force_authenticate(self.customer)
        for suffix, body in (('validate', {}), ('ready', {}), ('billing', {'invoice_reference': 'FORGED', 'invoiced_on': '2025-10-15'}), ('close', {}), ('reset', {'reason': 'FORGED'})):
            response = self.action(suffix, body)
            self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.api.get(f'/api/requests/{other_request.pk}/exchange/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/requests/{other_request.pk}/report/').status_code, 404)

    def test_portal_search_cannot_probe_the_hidden_draft_serial(self):
        self.prepare()
        self.api.force_authenticate(self.customer)
        detail = self.api.get(f'/api/requests/{self.request.pk}/exchange/')
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn(self.replacement.serial_number, str(detail.data))
        response = self.api.get('/api/exchanges/', {'q': self.replacement.serial_number})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.action('validate').status_code, 200)
        self.api.force_authenticate(self.customer)
        response = self.api.get('/api/exchanges/', {'q': self.replacement.serial_number})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [self.request.pk])

    def test_revoked_billing_permission_is_effective_on_next_session_request(self):
        self.validate_and_ready()
        User = get_user_model()
        billing_user = User.objects.create_user('exchange-review-billing', role='technician', can_validate_billing=True)
        browser = BrowserClient()
        browser.force_login(billing_user)
        User.objects.filter(pk=billing_user.pk).update(can_validate_billing=False)
        response = browser.post(f'/api/requests/{self.request.pk}/exchange/billing/', {'invoice_reference': 'REVOKED', 'invoiced_on': '2025-10-15'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.exchange_process.billing_validated_at)

    def test_exchange_history_is_append_only_and_public_confirmation_has_private_details(self):
        self.validate_and_ready()
        self.confirm_billing()
        events = OperationEvent.objects.filter(service_request=self.request)
        self.assertTrue(events.filter(kind='exchange_validated', is_internal=False).exists())
        self.assertTrue(events.filter(kind='exchange_ready', is_internal=False).exists())
        self.assertTrue(events.filter(kind='exchange_billed', is_internal=False).exists())
        self.assertTrue(events.filter(kind='exchange_billing_details', is_internal=True).exists())
        public = events.filter(is_internal=False)
        self.assertNotIn('PRIVATE-INVOICE-000042', ' '.join(public.values_list('summary', flat=True)))
        self.assertNotIn('PRIVATE_FINANCE_NOTES_EXCHANGE', ' '.join(public.values_list('observation', flat=True)))

    def test_reset_is_visible_on_replacement_timeline_without_private_reason(self):
        self.validate_and_ready()
        response = self.action('reset', {'reason': 'PRIVATE_RESET_REASON_EXCHANGE'})
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.exchange_process.validated_at)
        self.assertIsNone(self.request.exchange_process.ready_at)
        self.assertEqual(self.request.status, 'exchange')
        event = OperationEvent.objects.get(service_request=self.request, kind='exchange_reset')
        self.assertEqual(event.related_equipment_id, self.replacement.pk)
        self.api.force_authenticate(self.customer)
        timeline = self.api.get(f'/api/equipment/{self.replacement.pk}/timeline/')
        self.assertEqual(timeline.status_code, 200)
        self.assertTrue(any(item['kind'] == 'exchange_reset' for item in timeline.data))
        self.assertNotIn('PRIVATE_RESET_REASON_EXCHANGE', str(timeline.data))
        text = pdf_text(service_request_report(self.request, for_client=True))
        self.assertIn('Validation technique Non enregistrée', text)

    def test_reset_of_draft_does_not_invent_an_approval_or_publish_draft_serial(self):
        self.prepare()
        response = self.action('reset', {'reason': 'PRIVATE_DRAFT_RESET_REASON'})
        self.assertEqual(response.status_code, 200, response.data)
        public = OperationEvent.objects.filter(service_request=self.request, is_internal=False)
        reset = public.get(kind='exchange_reset')
        self.assertIsNone(reset.related_equipment_id)
        self.assertNotIn(self.replacement.serial_number, reset.summary)
        self.assertNotIn('Validation du remplacement', reset.summary)
        self.assertFalse(public.filter(kind='exchange_validated').exists())
        self.api.force_authenticate(self.customer)
        response = self.api.get(f'/api/requests/{self.request.pk}/timeline/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.replacement.serial_number, str(response.data))
        self.assertNotIn('PRIVATE_DRAFT_RESET_REASON', str(response.data))

    def test_reading_closed_legacy_exchange_does_not_backfill_approval_or_events(self):
        from core.models import ExchangeProcess

        legacy = ServiceRequest.objects.create(equipment=self.original, subject='Ancien échange fictif')
        ServiceRequest.objects.filter(pk=legacy.pk).update(status='closed', closed_at=None)
        Intervention.objects.bulk_create([Intervention(
            service_request=legacy, reference='INT-LEGACY-EXCHANGE-REVIEW', technician=self.tech,
            kind='exchange', status='completed', performed_on=date(2025, 10, 15),
            replacement_equipment=self.replacement, work_done='Ancien relevé fictif',
        )])
        legacy.refresh_from_db()
        before = ExchangeProcess.objects.count(), OperationEvent.objects.count()
        response = self.api.get(f'/api/requests/{legacy.pk}/exchange/')
        self.assertEqual(response.status_code, 200, response.data)
        exchange = response.data['exchange']
        self.assertFalse(exchange['is_validated'])
        self.assertFalse(exchange['is_invoiced'])
        text = pdf_text(service_request_report(legacy))
        self.assertIn('Validation technique Non enregistrée', text)
        self.assertIn('Facturation Non confirmée', text)
        self.assertEqual((ExchangeProcess.objects.count(), OperationEvent.objects.count()), before)
        # The same historical record must stay protected in model/admin writes,
        # even though no new approval/marker was invented by its read path.
        legacy.equipment = self.replacement
        with self.assertRaises(ValidationError):
            legacy.save(update_fields=['equipment'])
        legacy.refresh_from_db()
        self.assertEqual(legacy.equipment_id, self.original.pk)
