"""Real preventive visits are counted separately from a campaign target."""
from datetime import date
import shutil
import subprocess
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, ServiceRequest
from core.pdf import intervention_report, service_request_report
from core.preventive_visits import preventive_visit_progress, with_preventive_counts
from core.serializers import InterventionSerializer, ServiceRequestSerializer


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PreventiveVisitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.manager = User.objects.create_user('preventive-manager', role='manager')
        cls.tech = User.objects.create_user('preventive-tech', role='technician')
        cls.company = Client.objects.create(name='Campagne préventive fictive')
        cls.other_company = Client.objects.create(name='Autre campagne fictive')
        cls.customer = User.objects.create_user('preventive-client', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='PREVENTIVE-LAB-001', model='Modèle de laboratoire')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='PREVENTIVE-OTHER-001', model='Autre modèle fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Campagne de laboratoire')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def endpoint(self, request=None):
        return f'/api/requests/{(request or self.request).pk}/'

    def visit(self, **changes):
        return Intervention.objects.create(service_request=self.request, kind='preventive', **changes)

    def test_old_request_has_unknown_target_and_zero_real_visits(self):
        data = self.api.get(self.endpoint()).data
        self.assertIsNone(data['planned_visit_count'])
        self.assertIsNone(data['preventive_remaining_visit_count'])
        self.assertEqual(data['preventive_completed_visit_count'], 0)
        self.assertEqual(data['preventive_total_visit_count'], 0)

    def test_target_does_not_create_visits_and_changes_are_logged(self):
        response = self.api.patch(self.endpoint(), {'planned_visit_count': 3}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['planned_visit_count'], 3)
        self.assertEqual(response.data['preventive_remaining_visit_count'], 3)
        self.assertFalse(self.request.interventions.exists())
        self.assertTrue(self.request.operation_events.filter(summary__contains='Visites préventives prévues : non renseignées → 3').exists())
        response = self.api.patch(self.endpoint(), {'planned_visit_count': None}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data['preventive_remaining_visit_count'])
        self.assertTrue(self.request.operation_events.filter(summary__contains='3 → non renseignées').exists())

    def test_invalid_targets_are_rejected_by_api_and_database(self):
        for target in (0, -1, 1001, 1.5, True, 'three'):
            with self.subTest(target=target):
                response = self.api.patch(self.endpoint(), {'planned_visit_count': target}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        for target in (0, 1001):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ServiceRequest.objects.filter(pk=self.request.pk).update(planned_visit_count=target)

    def test_only_manager_or_admin_can_define_a_target(self):
        self.api.force_authenticate(self.tech)
        response = self.api.post('/api/requests/', {'equipment': self.equipment.pk, 'subject': 'Nouvelle campagne', 'planned_visit_count': 3}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('responsable', str(response.data))
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.patch(self.endpoint(), {'planned_visit_count': 3}, format='json').status_code, 403)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.planned_visit_count)

    def test_counts_include_completed_preventive_only_in_same_dossier(self):
        self.request.planned_visit_count = 3
        self.request.save(update_fields=['planned_visit_count'])
        self.visit(status='completed', performed_on=date(2025, 1, 1), work_done='Contrôles réalisés')
        self.visit(status='scheduled')
        self.visit(status='cancelled')
        Intervention.objects.create(service_request=self.request, kind='commissioning', status='completed')
        other_dossier = ServiceRequest.objects.create(equipment=self.equipment, subject='Autre dossier sur le même onduleur')
        Intervention.objects.create(service_request=other_dossier, kind='preventive', status='completed')
        progress = self.api.get(self.endpoint()).data
        self.assertEqual(progress['preventive_completed_visit_count'], 1)
        self.assertEqual(progress['preventive_total_visit_count'], 2)
        self.assertEqual(progress['preventive_remaining_visit_count'], 2)
        raw = preventive_visit_progress(ServiceRequest.objects.get(pk=self.request.pk))
        self.assertEqual({key: progress[key] for key in raw}, raw)

    def test_completion_cancellation_and_reopening_recalculate_actual_progress(self):
        self.api.patch(self.endpoint(), {'planned_visit_count': 1}, format='json')
        first = self.api.post('/api/interventions/', {'service_request': self.request.pk, 'kind': 'preventive', 'status': 'scheduled'}, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        endpoint = f'/api/interventions/{first.data["id"]}/'
        done = self.api.patch(endpoint, {'status': 'completed', 'performed_on': '2025-01-01', 'work_done': 'Contrôles effectués'}, format='json')
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['preventive_completed_visit_count'], 1)
        self.assertEqual(done.data['preventive_remaining_visit_count'], 0)
        self.visit(status='completed', performed_on=date(2025, 1, 2), work_done='Visite supplémentaire')
        progress = self.api.get(self.endpoint()).data
        self.assertEqual(progress['preventive_completed_visit_count'], 2)
        self.assertEqual(progress['preventive_remaining_visit_count'], 0)
        reopened = self.api.patch(endpoint, {'status': 'scheduled'}, format='json')
        self.assertEqual(reopened.data['preventive_completed_visit_count'], 1)
        cancelled = self.api.patch(endpoint, {'status': 'cancelled'}, format='json')
        self.assertEqual(cancelled.data['preventive_total_visit_count'], 1)

    def test_derived_counts_cannot_be_forged_and_intervention_target_is_readonly(self):
        self.api.patch(self.endpoint(), {'planned_visit_count': 3}, format='json')
        response = self.api.patch(self.endpoint(), {'preventive_completed_visit_count': 3, 'preventive_remaining_visit_count': 0}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['preventive_completed_visit_count'], 0)
        visit = self.visit(status='scheduled')
        response = self.api.patch(f'/api/interventions/{visit.pk}/', {'planned_visit_count': 99, 'preventive_total_visit_count': 99}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['planned_visit_count'], 3)
        self.assertEqual(response.data['preventive_total_visit_count'], 1)

    def test_client_sees_own_progress_only(self):
        self.api.patch(self.endpoint(), {'planned_visit_count': 3}, format='json')
        own = self.visit(status='scheduled')
        other = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Progression privée', planned_visit_count=11)
        other_visit = Intervention.objects.create(service_request=other, kind='preventive', status='completed')
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get(self.endpoint()).data['planned_visit_count'], 3)
        self.assertEqual(self.api.get(f'/api/interventions/{own.pk}/').data['planned_visit_count'], 3)
        self.assertEqual(self.api.get(self.endpoint(other)).status_code, 404)
        self.assertEqual(self.api.get(f'/api/interventions/{other_visit.pk}/').status_code, 404)

    def test_request_category_counts_are_not_multiplied_by_visits(self):
        self.visit(status='scheduled')
        self.visit(status='completed')
        self.visit(status='cancelled')
        data = self.api.get('/api/requests/categories/').data
        self.assertEqual(data['total'], 1)
        self.assertEqual(next(item for item in data['categories'] if item['key'] == 'all')['count'], 1)

    def test_annotated_lists_do_not_issue_one_progress_query_per_row(self):
        self.visit(status='completed')
        self.visit(status='scheduled')
        requests = with_preventive_counts(ServiceRequest.objects.select_related('equipment__client', 'assigned_technician'))
        with self.assertNumQueries(1):
            data = ServiceRequestSerializer(requests, many=True).data
        self.assertEqual(data[0]['preventive_completed_visit_count'], 1)
        visits = with_preventive_counts(Intervention.objects.select_related('service_request__equipment__client', 'technician', 'contract', 'extension_warranty', 'replacement_equipment'), 'service_request__interventions')
        with self.assertNumQueries(1):
            data = InterventionSerializer(visits, many=True).data
        self.assertEqual(data[0]['preventive_completed_visit_count'], 1)

    def test_intake_preserves_target_and_rejects_technician_planning(self):
        payload = {'request_key': str(uuid4()), 'equipment': self.equipment.pk, 'serial_number': self.equipment.serial_number, 'subject': 'Nouvelle campagne par réception', 'planned_visit_count': 3}
        response = self.api.post('/api/requests/intake/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        saved = ServiceRequest.objects.get(intake_key=payload['request_key'])
        self.assertEqual(saved.planned_visit_count, 3)
        self.assertFalse(saved.interventions.exists())
        self.api.force_authenticate(self.tech)
        response = self.api.post('/api/requests/intake/', {**payload, 'request_key': str(uuid4())}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('planned_visit_count', response.data)

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler le PDF réellement produit.')
    def test_pdf_preventive_progress_and_commissioning_recap_are_database_values(self):
        self.api.patch(self.endpoint(), {'planned_visit_count': 3}, format='json')
        self.request.refresh_from_db()
        visit = self.visit(status='completed', performed_on=date(2025, 1, 1), work_done='Contrôles de laboratoire')
        for data in (intervention_report(visit), service_request_report(self.request)):
            text = subprocess.run(['pdftotext', '-', '-'], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode()
            text = ' '.join(text.split())
            self.assertIn('VISITES PRÉVENTIVES DU DOSSIER', text)
            self.assertIn('Visites réalisées 1 / 3 prévues', text)
            self.assertIn('Visites restant à réaliser 2', text)
        commissioning = Intervention.objects.create(service_request=self.request, kind='commissioning', site='SITE-FICTIF-PDF', cabinet_serial='ARMOIRE-FICTIVE-PDF')
        data = intervention_report(commissioning)
        text = ' '.join(subprocess.run(['pdftotext', '-', '-'], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode().split())
        self.assertIn('FICHE DE MISE EN SERVICE', text)
        self.assertIn('Date de réalisation Non renseignée', text)
        self.assertIn('SITE-FICTIF-PDF', text)
        self.assertIn('ARMOIRE-FICTIVE-PDF', text)
