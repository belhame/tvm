from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import AuditLog, Client, Contract, DeliveryLine, DeliveryNote, Equipment, Intervention, Part, ServiceRequest, StockMovement, Warranty

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Entreprise Alpha')
        cls.other_company = Client.objects.create(name='Entreprise Bêta')
        cls.admin = User.objects.create_user('admin-test', password='LongTestingPhrase42!', role='admin')
        cls.manager = User.objects.create_user('manager-test', password='LongTestingPhrase42!', role='manager')
        cls.tech = User.objects.create_user('tech-test', password='LongTestingPhrase42!', role='technician')
        cls.other_tech = User.objects.create_user('tech-other', password='LongTestingPhrase42!', role='technician')
        cls.customer = User.objects.create_user('client-test', password='LongTestingPhrase42!', role='client', client=cls.company)
        cls.other_customer = User.objects.create_user('client-other', password='LongTestingPhrase42!', role='client', client=cls.other_company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='ALPHA-001', model='93PM')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='BETA-001', model='9PX')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Batterie faible')
        cls.other_request = ServiceRequest.objects.create(equipment=cls.other_equipment, subject='Autre dossier')
        cls.intervention = Intervention.objects.create(service_request=cls.request, technician=cls.tech, internal_notes='CONFIDENTIEL_INTERNE', diagnosis='Diagnostic public')
        cls.other_intervention = Intervention.objects.create(service_request=cls.other_request, technician=cls.other_tech, internal_notes='SECRET_BETA')
        cls.part = Part.objects.create(sku='BAT-9', name='Batterie test', stock_quantity=5, min_stock=2, unit_price=Decimal('12.50'))
        for company, equipment, intervention in [(cls.company, cls.equipment, cls.intervention), (cls.other_company, cls.other_equipment, cls.other_intervention)]:
            Contract.objects.create(number=f'CTR-{company.pk}', client=company, equipment=equipment, starts_on=date(2026, 1, 1), ends_on=date(2027, 1, 1))
            Warranty.objects.create(equipment=equipment, starts_on=date(2026, 1, 1), ends_on=date(2027, 1, 1))
            note = DeliveryNote.objects.create(client=company, intervention=intervention)
            DeliveryLine.objects.create(delivery_note=note, part=cls.part, description='Une batterie', quantity=1)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_full_client_equipment_request_intervention_pdf_flow(self):
        response = self.api.post('/api/clients/', {'name': 'Client parcours', 'email': 'contact@example.invalid'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        company = response.data['id']
        response = self.api.post('/api/equipment/', {'client': company, 'serial_number': 'FLOW-001', 'brand': 'Eaton', 'model': '93PM', 'power_kva': '100.00'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        equipment = response.data['id']
        response = self.api.post('/api/requests/', {'equipment': equipment, 'subject': 'Alarme batterie', 'priority': 'high'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        request_id = response.data['id']
        response = self.api.post('/api/interventions/', {'service_request': request_id, 'technician': self.tech.pk, 'scheduled_at': timezone.now().isoformat(), 'status': 'in_progress', 'diagnosis': 'Batterie défectueuse'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        intervention = response.data['id']
        response = self.api.patch(f'/api/interventions/{intervention}/', {'status': 'completed', 'work_done': 'Remplacement et test de charge', 'recommendations': 'Contrôle dans six mois'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(response.data['completed_at'])
        self.assertEqual(ServiceRequest.objects.get(pk=request_id).status, 'resolved')
        pdf = self.api.get(f'/api/interventions/{intervention}/report/')
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        self.assertGreater(len(pdf.content), 1500)
        # Une seconde session de navigateur retrouve les données serveur.
        browser_two = APIClient()
        browser_two.force_authenticate(self.manager)
        self.assertEqual(browser_two.get(f'/api/equipment/{equipment}/').data['serial_number'], 'FLOW-001')

    def test_unauthenticated_api_is_denied(self):
        self.api.force_authenticate(user=None)
        for endpoint in ('clients', 'equipment', 'requests', 'interventions', 'parts', 'users', 'dashboard', 'search'):
            self.assertIn(self.api.get(f'/api/{endpoint}/').status_code, (401, 403))

    def test_customer_sees_only_own_resources(self):
        self.api.force_authenticate(self.customer)
        for endpoint in ('clients', 'equipment', 'requests', 'interventions', 'contracts', 'warranties', 'delivery-notes'):
            response = self.api.get(f'/api/{endpoint}/')
            self.assertEqual(response.status_code, 200, (endpoint, response.data))
            self.assertEqual(len(response.data), 1, endpoint)
            self.assertNotIn('BETA', str(response.data))
        intervention = self.api.get('/api/interventions/').data[0]
        self.assertNotIn('internal_notes', intervention)
        self.assertNotIn('legacy_id', intervention)
        delivery = self.api.get('/api/delivery-notes/').data[0]
        self.assertNotIn('part', delivery['lines'][0])

    def test_customer_cannot_guess_other_ids_or_download_reports(self):
        self.api.force_authenticate(self.customer)
        for endpoint, pk in [('clients', self.other_company.pk), ('equipment', self.other_equipment.pk), ('requests', self.other_request.pk), ('interventions', self.other_intervention.pk)]:
            self.assertEqual(self.api.get(f'/api/{endpoint}/{pk}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/interventions/{self.other_intervention.pk}/report/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/interventions/{self.intervention.pk}/report/').status_code, 200)

    def test_customer_all_writes_and_internal_resources_denied(self):
        self.api.force_authenticate(self.customer)
        for endpoint in ('clients', 'equipment', 'requests', 'interventions', 'contracts', 'warranties', 'delivery-notes'):
            self.assertEqual(self.api.post(f'/api/{endpoint}/', {}, format='json').status_code, 403, endpoint)
        for endpoint in ('parts', 'stock-movements', 'users', 'audit', 'integrations'):
            self.assertEqual(self.api.get(f'/api/{endpoint}/').status_code, 403, endpoint)
        self.assertEqual(self.api.post(f'/api/interventions/{self.intervention.pk}/use-part/', {'part': self.part.pk, 'quantity': 1}, format='json').status_code, 403)

    def test_customer_search_and_dashboard_cannot_leak_other_client(self):
        self.api.force_authenticate(self.customer)
        results = self.api.get('/api/search/?q=BETA').data
        self.assertEqual(results, {'equipment': [], 'clients': [], 'requests': [], 'interventions': []})
        dashboard = self.api.get('/api/dashboard/').data
        self.assertEqual(dashboard['metrics']['client_count'], 1)
        self.assertEqual(dashboard['metrics']['equipment_count'], 1)
        self.assertIsNone(dashboard['metrics']['critical_stock'])
        self.assertNotIn('internal_notes', str(dashboard))
        self.assertNotIn('SECRET_BETA', str(dashboard))

    def test_technician_cannot_manage_clients_accounts_or_other_interventions(self):
        self.api.force_authenticate(self.tech)
        self.assertEqual(self.api.post('/api/clients/', {'name': 'No'}, format='json').status_code, 403)
        self.assertEqual(self.api.post('/api/users/', {}, format='json').status_code, 403)
        self.assertEqual(self.api.patch(f'/api/interventions/{self.other_intervention.pk}/', {'diagnosis': 'Non'}, format='json').status_code, 403)
        self.assertEqual(self.api.patch(f'/api/interventions/{self.intervention.pk}/', {'diagnosis': 'Diagnostic modifié'}, format='json').status_code, 200)
        self.assertEqual(self.api.patch(f'/api/interventions/{self.intervention.pk}/', {'technician': self.other_tech.pk}, format='json').status_code, 400)
        self.assertEqual(self.api.delete(f'/api/interventions/{self.intervention.pk}/').status_code, 403)

    def test_staff_directory_is_limited_and_manager_cannot_create_accounts(self):
        self.api.force_authenticate(self.manager)
        response = self.api.get('/api/users/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('client-test', str(response.data))
        self.assertNotIn('password', str(response.data))
        self.assertNotIn('email', str(response.data))
        self.assertEqual(self.api.post('/api/users/', {}, format='json').status_code, 403)

    def test_customer_user_requires_client_and_password_is_never_returned(self):
        response = self.api.post('/api/users/', {'username': 'new-customer', 'role': 'client', 'password': 'UniqueTestingPhrase42!'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.post('/api/users/', {'username': 'new-customer', 'role': 'client', 'client': self.company.pk, 'password': 'UniqueTestingPhrase42!'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('password', response.data)
        self.assertTrue(User.objects.get(username='new-customer').check_password('UniqueTestingPhrase42!'))

    def test_stock_is_atomic_and_insufficient_stock_rolls_back(self):
        response = self.api.post('/api/stock-movements/', {'part': self.part.pk, 'quantity': -4, 'kind': 'out'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        response = self.api.post('/api/stock-movements/', {'part': self.part.pk, 'quantity': -3, 'kind': 'out'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        # Le champ en lecture seule ne permet pas de contourner le registre.
        self.api.patch(f'/api/parts/{self.part.pk}/', {'stock_quantity': 999}, format='json')
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 1)

    def test_use_part_requires_integer_and_records_assigned_intervention(self):
        self.api.force_authenticate(self.tech)
        for invalid in (1.9, True, 0, -2, 'bad'):
            response = self.api.post(f'/api/interventions/{self.intervention.pk}/use-part/', {'part': self.part.pk, 'quantity': invalid}, format='json')
            self.assertEqual(response.status_code, 400, (invalid, response.data))
        response = self.api.post(f'/api/interventions/{self.intervention.pk}/use-part/', {'part': self.part.pk, 'quantity': 2}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 3)
        self.assertEqual(StockMovement.objects.get().intervention, self.intervention)
        self.assertEqual(self.api.post(f'/api/interventions/{self.other_intervention.pk}/use-part/', {'part': self.part.pk, 'quantity': 1}, format='json').status_code, 403)

    def test_serial_is_case_insensitively_unique(self):
        response = self.api.post('/api/equipment/', {'client': self.company.pk, 'serial_number': 'alpha-001', 'model': 'Autre'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_contract_and_delivery_client_mismatch_rejected(self):
        response = self.api.post('/api/contracts/', {'number': 'BAD', 'client': self.company.pk, 'equipment': self.other_equipment.pk, 'starts_on': '2026-01-01', 'ends_on': '2027-01-01'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.post('/api/delivery-notes/', {'client': self.company.pk, 'intervention': self.other_intervention.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_dates_and_completion_requirements_validated(self):
        response = self.api.post('/api/warranties/', {'equipment': self.equipment.pk, 'starts_on': '2027-01-01', 'ends_on': '2026-01-01'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.patch(f'/api/interventions/{self.intervention.pk}/', {'status': 'completed'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_transfer_blocked_when_contract_or_historical_dossier_exists(self):
        response = self.api.patch(f'/api/equipment/{self.equipment.pk}/', {'client': self.other_company.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'equipment': self.other_equipment.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_completion_does_not_hide_other_active_intervention_or_reopen_closed_request(self):
        second = Intervention.objects.create(service_request=self.request, technician=self.tech, status='in_progress')
        response = self.api.patch(f'/api/interventions/{self.intervention.pk}/', {'status': 'completed', 'work_done': 'Fait'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'in_progress')
        self.request.status = 'closed'
        self.request.save()
        self.api.patch(f'/api/interventions/{self.intervention.pk}/', {'recommendations': 'Mise à jour'}, format='json')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'closed')

    def test_failed_delete_does_not_leave_false_audit(self):
        before = AuditLog.objects.filter(action='delete').count()
        response = self.api.delete(f'/api/clients/{self.company.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AuditLog.objects.filter(action='delete').count(), before)

    def test_audit_detail_and_integrations_are_honest(self):
        log = AuditLog.objects.create(actor=self.admin, action='test', resource='client', resource_id=str(self.company.pk))
        self.assertEqual(self.api.get(f'/api/audit/{log.pk}/').status_code, 200)
        integration = self.api.get('/api/integrations/').data
        self.assertFalse(integration['ai']['operational'])
        self.assertFalse(integration['whatsapp']['operational'])

    def test_last_admin_cannot_be_disabled_or_demoted(self):
        self.assertEqual(self.api.patch(f'/api/users/{self.admin.pk}/', {'is_active': False}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(f'/api/users/{self.admin.pk}/', {'role': 'manager'}, format='json').status_code, 400)

    def test_superuser_created_with_admin_role(self):
        user = User.objects.create_superuser('super-test', 'super@example.invalid', 'StrongRootPhrase42!')
        self.assertEqual(user.role, 'admin')
        self.assertEqual(user.effective_role, 'admin')

    def test_api_missing_route_is_json_not_spa(self):
        response = self.api.get('/api/does-not-exist/')
        self.assertEqual(response.status_code, 404)
        self.assertIn('application/json', response['Content-Type'])
