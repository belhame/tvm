"""SAV dashboard and integration guards, using fictional business data."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, Part, ServiceRequest, StockMovement, User
from core.request_assignment import assign_request, confirm_assignment


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SAVPriorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('sav-priority-admin', role='admin')
        cls.tech = User.objects.create_user('sav-priority-tech', role='technician')
        cls.other = User.objects.create_user('sav-priority-other', role='technician')
        cls.company = Client.objects.create(name='Centre SAV prioritaire fictif')
        cls.foreign_company = Client.objects.create(name='PRIVATE_FOREIGN_SAV_CENTRE')
        cls.portal = User.objects.create_user('sav-priority-portal', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='SAV-PRIORITY-LAB', model='Modèle fictif')
        cls.foreign_unit = Equipment.objects.create(client=cls.foreign_company, serial_number='PRIVATE_FOREIGN_SAV_SERIAL', model='Autre fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_dashboard_counts_business_requests_until_actual_closure(self):
        new = ServiceRequest.objects.create(equipment=self.unit, subject='Sans technicien')
        assigned = assign_request(new.pk, actor=self.admin, technician_id=self.tech.pk, expected_revision=0)
        assigned = confirm_assignment(assigned.pk, actor=self.tech, expected_revision=assigned.assignment_revision, accept=True)
        waiting = ServiceRequest.objects.create(equipment=self.unit, subject='Attente confirmation', status='pending', assigned_technician=self.other)
        ServiceRequest.objects.create(equipment=self.unit, subject='Traité reste ouvert', status='resolved')
        ServiceRequest.objects.create(equipment=self.unit, subject='Refusé reste ouvert', status='rejected')
        ServiceRequest.objects.create(equipment=self.unit, subject='Clôturé', status='closed')
        response = self.api.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['metrics']['request_count'], 5)
        self.assertEqual(response.data['metrics']['open_requests'], 4)
        self.assertEqual(response.data['metrics']['unassigned_requests'], 3)
        self.assertEqual(response.data['metrics']['accepted_requests'], 1)
        self.assertEqual(response.data['metrics']['awaiting_acceptance_requests'], 1)
        by_id = {row['id']: row for row in response.data['recent_requests']}
        self.assertTrue(by_id[assigned.pk]['assignment']['accepted'])
        self.assertFalse(by_id[waiting.pk]['assignment']['accepted'])
        self.assertEqual(sum(row['count'] for row in response.data['request_status_distribution']), 5)

    def test_portal_dashboard_omits_other_centres_and_internal_acceptance_metadata(self):
        own = ServiceRequest.objects.create(equipment=self.unit, subject='Dossier du centre', status='pending', assigned_technician=self.tech)
        ServiceRequest.objects.create(equipment=self.foreign_unit, subject='PRIVATE_FOREIGN_SAV_REQUEST', status='pending')
        self.api.force_authenticate(self.portal)
        response = self.api.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['metrics']['request_count'], 1)
        self.assertEqual([row['id'] for row in response.data['recent_requests']], [own.pk])
        self.assertNotIn('PRIVATE_FOREIGN', str(response.data))
        for field in ('assignment', 'assignment_accepted_by', 'assignment_accepted_at', 'assignment_revision'):
            self.assertNotIn(field, response.data['recent_requests'][0])

    def test_acceptance_produces_only_its_explicit_private_event(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Acceptation sans bruit public', status='pending', assigned_technician=self.tech)
        before = set(record.operation_events.values_list('id', flat=True))
        confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True)
        events = list(record.operation_events.exclude(pk__in=before))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, 'assignment_accepted')
        self.assertTrue(events[0].is_internal)

    def test_stock_out_cannot_use_historical_intervention_after_reassignment(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Pièce réservée au technicien courant', status='pending', assigned_technician=self.tech)
        record = confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True)
        visit = Intervention.objects.create(service_request=record, technician=self.tech)
        part = Part.objects.create(sku='SAV-PRIORITY-PART', name='Pièce fictive')
        self.api.post('/api/stock-movements/', {'part': part.pk, 'quantity': 2, 'kind': 'in'}, format='json')
        assign_request(record.pk, actor=self.admin, technician_id=self.other.pk, expected_revision=record.assignment_revision)
        self.api.force_authenticate(self.tech)
        rejected = self.api.post('/api/stock-movements/', {'part': part.pk, 'intervention': visit.pk, 'quantity': -1, 'kind': 'out'}, format='json')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(StockMovement.objects.filter(part=part, kind='out').count(), 0)
        part.refresh_from_db()
        self.assertEqual(part.stock_quantity, 2)

    def test_technician_cannot_skip_acceptance_by_creating_an_already_processed_request(self):
        self.api.force_authenticate(self.tech)
        for status in ('maintenance', 'testing', 'resolved', 'closed', 'quotation', 'exchange'):
            with self.subTest(status=status):
                denied = self.api.post('/api/requests/', {'equipment': self.unit.pk, 'subject': 'Dossier non pris en charge', 'status': status}, format='json')
                self.assertEqual(denied.status_code, 400)
        self.assertFalse(ServiceRequest.objects.exists())
        received = self.api.post('/api/requests/', {'equipment': self.unit.pk, 'subject': 'Réception initiale légitime'}, format='json')
        self.assertEqual(received.status_code, 201)
        self.assertEqual(received.data['status'], 'new')
        self.assertIsNone(received.data['assigned_technician'])
        self.assertFalse(received.data['assignment']['accepted'])
