"""Structured WINDEV-inspired sheets, using fictional equipment only."""

from datetime import date, timedelta
from io import BytesIO
import shutil
import subprocess
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from reportlab.platypus import Paragraph
from rest_framework.test import APIClient

from core.intervention_workflow import report_checklists, validate_structured_data
from core.models import Client, Contract, Equipment, Intervention, ServiceRequest, Warranty
from core.pdf import intervention_report


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StructuredInterventionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Client fiches de laboratoire', contact_name='Contact de laboratoire', phone='0102030405')
        cls.other_company = Client.objects.create(name='Autre client fiches')
        cls.admin = User.objects.create_user('sheets-admin', role='admin', password='SheetsTesting42!')
        cls.tech = User.objects.create_user('sheets-tech', role='technician', password='SheetsTesting42!')
        cls.other_tech = User.objects.create_user('sheets-other-tech', role='technician', password='SheetsTesting42!')
        cls.customer = User.objects.create_user('sheets-client', role='client', client=cls.company, password='SheetsTesting42!')
        cls.other_customer = User.objects.create_user('sheets-other-client', role='client', client=cls.other_company, password='SheetsTesting42!')
        cls.original = Equipment.objects.create(client=cls.company, serial_number='ORIGINAL-SHEET-001', model='Modèle original')
        cls.replacement = Equipment.objects.create(client=cls.company, serial_number='REPLACEMENT-SHEET-002', model='Modèle de remplacement')
        cls.other = Equipment.objects.create(client=cls.other_company, serial_number='PRIVATE-OTHER-003', model='Autre modèle')
        cls.request = ServiceRequest.objects.create(equipment=cls.original, subject='Fiche fictive à compléter')
        cls.other_request = ServiceRequest.objects.create(equipment=cls.other, subject='Dossier autre client')
        cls.contract = Contract.objects.create(
            number='CTR-SHEETS-001', client=cls.company, equipment=cls.original,
            starts_on=date(2025, 1, 1), ends_on=date(2027, 1, 1), status='active',
        )
        cls.company_contract = Contract.objects.create(
            number='CTR-CLIENT-WIDE', client=cls.company, equipment=None,
            starts_on=date(2025, 1, 1), ends_on=date(2027, 1, 1), status='active',
        )
        cls.wrong_contract = Contract.objects.create(
            number='CTR-OTHER-SHEETS', client=cls.other_company, equipment=cls.other,
            starts_on=date(2025, 1, 1), ends_on=date(2027, 1, 1), status='active',
        )
        cls.extension = Warranty.objects.create(
            equipment=cls.original, provider='Extension contractuelle fictive', scope='batteries',
            starts_on=date(2025, 1, 1), ends_on=date(2028, 1, 1), terms='Conditions fictives de couverture.',
        )
        cls.wrong_extension = Warranty.objects.create(
            equipment=cls.replacement, starts_on=date(2025, 1, 1), ends_on=date(2028, 1, 1),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.payload = {
            'service_request': self.request.pk, 'technician': self.tech.pk,
            'diagnosis': 'Diagnostic de laboratoire', 'work_done': 'Travaux réalisés au laboratoire',
        }

    def post(self, **changes):
        return self.api.post('/api/interventions/', {**self.payload, **changes}, format='json')

    def exchange(self, **changes):
        return self.post(
            **{
                'kind': 'exchange', 'status': 'completed', 'performed_on': '2025-10-15',
                'replacement_equipment': self.replacement.pk, 'contract': self.contract.pk,
                'extension_warranty': self.extension.pk, 'summary': 'Échange confirmé au laboratoire.',
                'conclusion': 'completed', **changes,
            }
        )

    def test_structured_sheet_round_trip_preserves_public_fields(self):
        data = {
            'maintenance': {
                'battery_failure': True, 'electronics_failure': False,
                'replace_batteries': True, 'battery_replaced_count': 2,
                'comment': 'Batteries contrôlées et remplacées.',
            },
            'commissioning': {'electrical_protection': True, 'cable_section': True, 'normal_operation_test': True},
            'preventive': {'environment': True, 'power_cables': True, 'dusting': True, 'comment': 'Environnement contrôlé.'},
        }
        response = self.post(
            kind='maintenance', status='completed', structured_data=data,
            cabinet_serial='CABINET-SHEET-001', battery_count=4,
            site='Atelier du laboratoire', end_customer='Client final renseigné',
            contact_name='Référent technique', contact_phone='+330102030405',
            summary='Synthèse publique des travaux.', conclusion='follow_up', conclusion_notes='Contrôle de suivi prévu.',
        )
        self.assertEqual(response.status_code, 201, response.data)
        intervention = Intervention.objects.get(pk=response.data['id'])
        self.assertEqual(intervention.structured_data, data)
        self.assertEqual(intervention.cabinet_serial, 'CABINET-SHEET-001')
        self.assertEqual(intervention.battery_count, 4)
        self.assertEqual(intervention.summary, 'Synthèse publique des travaux.')
        self.api.force_authenticate(self.customer)
        detail = self.api.get(f'/api/interventions/{intervention.pk}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['structured_data'], data)
        self.assertEqual(detail.data['summary'], 'Synthèse publique des travaux.')

    def test_completed_exchange_keeps_original_serial_and_links_new_equipment(self):
        response = self.exchange()
        self.assertEqual(response.status_code, 201, response.data)
        intervention = Intervention.objects.get(pk=response.data['id'])
        self.original.refresh_from_db()
        self.replacement.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.original.serial_number, 'ORIGINAL-SHEET-001')
        self.assertEqual(self.replacement.serial_number, 'REPLACEMENT-SHEET-002')
        self.assertEqual(self.request.equipment_id, self.original.pk)
        self.assertEqual(intervention.replacement_equipment_id, self.replacement.pk)
        self.assertEqual(response.data['equipment_serial'], self.original.serial_number)
        self.assertEqual(response.data['replacement_equipment_serial'], self.replacement.serial_number)
        self.assertEqual(intervention.performed_on, date(2025, 10, 15))
        self.assertEqual(intervention.contract_id, self.contract.pk)
        self.assertEqual(intervention.extension_warranty_id, self.extension.pk)

    def test_exchange_rejects_foreign_client_and_same_equipment(self):
        for replacement in (self.other.pk, self.original.pk):
            with self.subTest(replacement=replacement):
                response = self.exchange(replacement_equipment=replacement)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('replacement_equipment', response.data)
        self.assertFalse(Intervention.objects.exists())

    def test_exchange_completion_requires_new_equipment_and_actual_date(self):
        response = self.exchange(replacement_equipment=None)
        self.assertEqual(response.status_code, 400)
        self.assertIn('replacement_equipment', response.data)
        response = self.exchange(performed_on=None)
        self.assertEqual(response.status_code, 400)
        self.assertIn('performed_on', response.data)
        self.assertFalse(Intervention.objects.exists())

    def test_nonexchange_cannot_silently_keep_replacement_equipment(self):
        response = self.post(kind='maintenance', replacement_equipment=self.replacement.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('replacement_equipment', response.data)
        created = self.exchange()
        response = self.api.patch(f'/api/interventions/{created.data["id"]}/', {'kind': 'maintenance'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.patch(f'/api/interventions/{created.data["id"]}/', {'kind': 'maintenance', 'replacement_equipment': None}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_commissioning_and_preventive_can_be_planned_but_need_actual_date_to_complete(self):
        for kind in ('commissioning', 'preventive'):
            with self.subTest(kind=kind):
                planned = self.post(kind=kind, status='scheduled')
                self.assertEqual(planned.status_code, 201, planned.data)
                response = self.api.patch(f'/api/interventions/{planned.data["id"]}/', {'status': 'completed'}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('performed_on', response.data)
                response = self.api.patch(f'/api/interventions/{planned.data["id"]}/', {'status': 'completed', 'performed_on': '2025-10-15'}, format='json')
                self.assertEqual(response.status_code, 200, response.data)

    def test_actual_date_cannot_be_future(self):
        response = self.post(performed_on=(timezone.localdate() + timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn('performed_on', response.data)

    def test_existing_maintenance_closure_does_not_invent_a_historical_date(self):
        response = self.post(status='completed')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['kind'], 'maintenance')
        self.assertIsNone(response.data['performed_on'])
        self.assertEqual(response.data['structured_data'], {})

    def test_billing_conclusion_is_a_justified_manual_choice(self):
        self.original.warranty_until = date(2001, 1, 1)
        self.original.save(update_fields=['warranty_until'])
        ordinary = self.post()
        self.assertEqual(ordinary.status_code, 201)
        self.assertEqual(ordinary.data['conclusion'], '')
        response = self.post(conclusion='not_applicable_billable')
        self.assertEqual(response.status_code, 400)
        self.assertIn('conclusion_notes', response.data)
        response = self.post(conclusion='not_applicable_billable', conclusion_notes='Décision de traitement saisie après contrôle du dossier.')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['conclusion'], 'not_applicable_billable')

    def test_checklists_reject_unknown_keys_sections_and_nonboolean_values(self):
        values = [
            {'unknown': {'environment': True}},
            {'maintenance': {'internal_notes': 'PRIVATE-NOT-A-CHECKLIST'}},
            {'preventive': {'environment': 'true'}},
            {'preventive': {'environment': 1}},
            {'maintenance': []},
            {'maintenance': {'comment': 'x' * 4001}},
            {'maintenance': {'comment': 'Commentaire\x00invalide'}},
        ]
        for data in values:
            with self.subTest(data_type=type(data).__name__):
                response = self.post(structured_data=data)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('structured_data', response.data)
        self.assertFalse(Intervention.objects.exists())

    def test_battery_action_and_quantity_are_consistent_before_completion(self):
        for data in (
            {'replace_batteries': True},
            {'replace_batteries': True, 'battery_replaced_count': 0},
            {'battery_replaced_count': 2},
            {'replace_batteries': True, 'battery_replaced_count': True},
            {'replace_batteries': True, 'battery_replaced_count': -1},
        ):
            response = self.post(status='completed', structured_data={'maintenance': data})
            self.assertEqual(response.status_code, 400, response.data)
        response = self.post(status='completed', structured_data={'maintenance': {'replace_batteries': True, 'battery_replaced_count': 2}})
        self.assertEqual(response.status_code, 201, response.data)

    def test_material_and_text_bounds_are_enforced(self):
        for changes in ({'battery_count': 100001}, {'battery_count': -1}, {'summary': 'x' * 10001}, {'conclusion_notes': 'x' * 4001}):
            response = self.post(**changes)
            self.assertEqual(response.status_code, 400, response.data)

    def test_contract_and_extension_must_belong_to_original_equipment_or_client(self):
        for changes in ({'contract': self.wrong_contract.pk}, {'extension_warranty': self.wrong_extension.pk}):
            response = self.post(**changes)
            self.assertEqual(response.status_code, 400, response.data)
        response = self.post(contract=self.company_contract.pk, extension_warranty=self.extension.pk)
        self.assertEqual(response.status_code, 201, response.data)

    def test_reported_equipment_contract_and_extension_cannot_be_reparented(self):
        created = self.exchange(contract=self.company_contract.pk)
        self.assertEqual(created.status_code, 201, created.data)
        operations = [
            (f'/api/equipment/{self.replacement.pk}/', {'client': self.other_company.pk}),
            (f'/api/contracts/{self.company_contract.pk}/', {'client': self.other_company.pk}),
            (f'/api/warranties/{self.extension.pk}/', {'equipment': self.other.pk}),
        ]
        for url, data in operations:
            response = self.api.patch(url, data, format='json')
            self.assertEqual(response.status_code, 400, (url, response.data))
        self.replacement.refresh_from_db()
        self.company_contract.refresh_from_db()
        self.extension.refresh_from_db()
        self.assertEqual(self.replacement.client_id, self.company.pk)
        self.assertEqual(self.company_contract.client_id, self.company.pk)
        self.assertEqual(self.extension.equipment_id, self.original.pk)

    def test_technician_can_edit_only_own_sheet_and_client_cannot_write(self):
        first = self.post()
        self.api.force_authenticate(self.tech)
        response = self.api.patch(f'/api/interventions/{first.data["id"]}/', {'structured_data': {'preventive': {'dusting': True}}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.api.patch(f'/api/interventions/{first.data["id"]}/', {'summary': 'Non autorisé'}, format='json').status_code, 403)
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.post(kind='commissioning').status_code, 403)

    def test_client_cannot_read_another_clients_sheet_or_private_notes(self):
        own = self.post(internal_notes='INTERNAL-SHEET-SECRET', summary='Synthèse visible du client')
        other = self.post(service_request=self.other_request.pk, internal_notes='OTHER-SHEET-SECRET')
        self.api.force_authenticate(self.customer)
        response = self.api.get(f'/api/interventions/{own.data["id"]}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('internal_notes', response.data)
        self.assertNotIn('INTERNAL-SHEET-SECRET', str(response.data))
        self.assertEqual(self.api.get(f'/api/interventions/{other.data["id"]}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/interventions/{other.data["id"]}/report/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/interventions/{own.data["id"]}/report/').status_code, 200)

    def test_pdf_builds_whitelisted_content_and_never_private_notes(self):
        intervention = Intervention.objects.create(
            service_request=self.request, kind='maintenance', work_done='Travaux publics',
            internal_notes='SECRET_INTERNAL_SHEET',
            structured_data={'maintenance': {'battery_failure': True, 'internal_notes': 'SECRET_JSON_SHEET'}, 'private_section': {'comment': 'SECRET_SECTION_SHEET'}},
        )
        with patch('core.pdf.Paragraph', wraps=Paragraph) as paragraphs:
            data = intervention_report(intervention)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertGreater(len(data), 1000)
        text = '\n'.join(str(call.args[0]) for call in paragraphs.call_args_list)
        self.assertIn('[X] Défaillance des batteries', text)
        for secret in ('SECRET_INTERNAL_SHEET', 'SECRET_JSON_SHEET', 'SECRET_SECTION_SHEET'):
            self.assertNotIn(secret, text)

    @skipUnless(shutil.which('pdftotext'), 'Le contrôle du texte PDF requiert pdftotext (Poppler).')
    def test_rendered_exchange_pdf_contains_serials_sections_and_manual_conclusion(self):
        created = self.exchange(
            cabinet_serial='CABINET-PDF-010', battery_count=0,
            structured_data={
                'maintenance': {'battery_failure': True, 'configure': False, 'comment': 'Commentaire maintenance public.'},
                'commissioning': {'normal_operation_test': True},
                'preventive': {'dusting': True, 'comment': 'Nettoyage prévu et réalisé.'},
            },
            conclusion='not_applicable_billable', conclusion_notes='Appréciation manuelle justifiée.',
            internal_notes='HIDDEN_PDF_INTERNAL_777',
        )
        self.assertEqual(created.status_code, 201, created.data)
        response = self.api.get(f'/api/interventions/{created.data["id"]}/report/')
        self.assertEqual(response.status_code, 200)
        extracted = subprocess.run(['pdftotext', '-', '-'], input=response.content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode('utf-8')
        for expected in (
            'Fiche d’échange', self.original.serial_number, self.replacement.serial_number,
            self.contract.number, 'Extension contractuelle fictive', 'CABINET-PDF-010',
            'Échange confirmé au laboratoire.', 'Défaillance des batteries', 'Test de fonctionnement normal',
            'Travaux préventifs', 'Dépoussiérage', 'Appréciation manuelle justifiée.',
        ):
            self.assertIn(expected, extracted)
        self.assertNotIn('HIDDEN_PDF_INTERNAL_777', extracted)


class ChecklistReportTests(SimpleTestCase):
    def test_report_projection_ignores_unrecognized_fields_even_from_legacy_json(self):
        sections = report_checklists({'maintenance': {'battery_failure': True, 'private': 'SECRET'}, 'private': {'comment': 'SECRET'}})
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]['checks'], [{'label': 'Défaillance des batteries', 'checked': True}])
        self.assertNotIn('SECRET', str(sections))

    def test_true_and_false_are_preserved_without_inventing_missing_controls(self):
        sections = report_checklists({'preventive': {'environment': True, 'dusting': False}})
        self.assertEqual([item['checked'] for item in sections[0]['checks']], [True, False])
        self.assertEqual(len(sections[0]['checks']), 2)
        self.assertEqual(validate_structured_data({'preventive': {'environment': True}}), {'preventive': {'environment': True}})
