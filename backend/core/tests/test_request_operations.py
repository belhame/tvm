from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Contract, Equipment, Intervention, OperationEvent, Part, ServiceRequest, Warranty

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RequestOperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('workflow-manager', role='manager')
        cls.tech = User.objects.create_user('workflow-tech', role='technician')
        cls.other_tech = User.objects.create_user('workflow-other-tech', role='technician')
        cls.company = Client.objects.create(name='Client opérations fictif')
        cls.other_company = Client.objects.create(name='Autre client fictif')
        cls.customer = User.objects.create_user('workflow-client', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='OPERATIONS-LAB-001', model='Modèle fictif')
        cls.replacement = Equipment.objects.create(client=cls.company, serial_number='OPERATIONS-LAB-002', model='Remplacement fictif')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='OTHER-SECRET-001', model='Autre fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Demande fictive')
        cls.other_request = ServiceRequest.objects.create(equipment=cls.other_equipment, subject='Dossier autre société')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def timeline(self, request=None):
        return f'/api/requests/{(request or self.request).pk}/timeline/'

    def test_request_creation_and_update_capture_real_actor_and_actual_state(self):
        response = self.api.post('/api/requests/', {'equipment': self.equipment.pk, 'subject': 'Nouveau dossier fictif'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        request = ServiceRequest.objects.get(pk=response.data['id'])
        event = request.operation_events.get()
        self.assertEqual(event.kind, 'created')
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertEqual(event.status_before, '')
        self.assertEqual(event.status_after, 'new')
        response = self.api.patch(f'/api/requests/{request.pk}/', {'status': 'quotation'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        event = request.operation_events.latest('id')
        self.assertEqual((event.status_before, event.status_after), ('new', 'quotation'))

    def test_one_manual_transition_and_separate_private_note(self):
        before = self.request.operation_events.filter(kind='status_changed').count()
        response = self.api.post(self.timeline(), {'kind': 'status_changed', 'status_after': 'testing', 'observation': 'SECRET_TEST_NOTE'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.request.operation_events.filter(kind='status_changed').count(), before + 1)
        self.assertFalse(response.data['is_internal'])
        self.assertNotIn('SECRET_TEST_NOTE', str(response.data))
        self.assertTrue(self.request.operation_events.filter(is_internal=True, observation='SECRET_TEST_NOTE').exists())
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'testing')
        repeat = self.api.post(self.timeline(), {'kind': 'status_changed', 'status_after': 'testing'}, format='json')
        self.assertEqual(repeat.status_code, 400)

    def test_notes_default_private_and_public_synthesis_is_explicit(self):
        private = self.api.post(self.timeline(), {'kind': 'observation', 'observation': 'PRIVE-OPERATIONS'}, format='json')
        self.assertEqual(private.status_code, 201, private.data)
        self.assertTrue(private.data['is_internal'])
        public = self.api.post(self.timeline(), {'kind': 'summary', 'summary': 'Synthèse visible au client', 'is_internal': False}, format='json')
        self.assertEqual(public.status_code, 201, public.data)
        self.api.force_authenticate(self.customer)
        response = self.api.get(self.timeline())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('PRIVE-OPERATIONS', str(response.data))
        self.assertIn('Synthèse visible au client', str(response.data))
        self.assertTrue(all(item['actor_name'] == 'Équipe SAV' for item in response.data))

    def test_customer_cannot_guess_other_timelines_or_write(self):
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get(self.timeline(self.other_request)).status_code, 404)
        self.assertEqual(self.api.get(f'/api/equipment/{self.other_equipment.pk}/timeline/').status_code, 404)
        self.assertEqual(self.api.post(self.timeline(), {'kind': 'observation', 'observation': 'Non'}, format='json').status_code, 403)

    def test_technician_needs_assignment_and_cannot_acquire_it_by_self_assignment(self):
        self.api.force_authenticate(self.tech)
        payload = {'kind': 'observation', 'observation': 'Visite technique'}
        self.assertEqual(self.api.post(self.timeline(), payload, format='json').status_code, 403)
        response = self.api.post('/api/interventions/', {'service_request': self.request.pk, 'technician': self.tech.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.request.status = 'pending'
        self.request.assigned_technician = self.tech
        self.request.save()
        self.assertEqual(self.api.post(self.timeline(), payload, format='json').status_code, 201)
        self.assertEqual(self.api.post(f'/api/equipment/{self.equipment.pk}/timeline/', payload, format='json').status_code, 201)
        self.assertEqual(self.api.post(self.timeline(self.other_request), payload, format='json').status_code, 403)

    def test_assigned_intervention_also_allows_technician_timeline(self):
        Intervention.objects.create(service_request=self.request, technician=self.tech)
        self.api.force_authenticate(self.tech)
        response = self.api.post(self.timeline(), {'kind': 'summary', 'summary': 'Travaux réalisés'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_strict_append_validation_and_no_forged_dates_or_actors(self):
        cases = [
            {'kind': 'observation', 'observation': ''},
            {'kind': 'observation', 'observation': 123},
            {'kind': 'summary', 'summary': 'Texte', 'is_internal': 'false'},
            {'kind': 'summary', 'summary': 'Texte', 'actor': self.tech.pk},
            {'kind': 'summary', 'summary': 'Texte', 'created_at': '2001-01-01'},
            {'kind': 'summary', 'summary': 'Texte', 'status_after': 'closed'},
            {'kind': 'summary', 'summary': 'x' * 10001},
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.api.post(self.timeline(), payload, format='json').status_code, 400)
        self.assertEqual(self.api.post(f'/api/equipment/{self.equipment.pk}/timeline/', {'kind': 'status_changed', 'status_after': 'closed'}, format='json').status_code, 400)

    def test_categories_legacy_aliases_overdue_and_client_counts(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        states = ['maintenance', 'in_progress', 'testing', 'scheduled', 'pending', 'quotation', 'approved', 'rejected', 'exchange', 'resolved', 'closed']
        for state in states:
            ServiceRequest.objects.create(equipment=self.equipment, subject=f'Fictif {state}', status=state, due_on=yesterday)
        counts = {item['key']: item['count'] for item in self.api.get('/api/requests/categories/').data['categories']}
        self.assertEqual(counts['maintenance'], 2)
        self.assertEqual(counts['pending'], 2)
        self.assertEqual(counts['overdue'], 8)
        self.assertEqual(len(self.api.get('/api/requests/?category=overdue').data), 8)
        self.assertEqual(self.api.get('/api/requests/?category=invalid').status_code, 400)
        self.api.force_authenticate(self.customer)
        response = self.api.get('/api/requests/categories/')
        self.assertEqual(response.data['total'], 12)
        self.assertEqual(len(self.api.get('/api/requests/?category=all').data), 12)
        self.assertEqual(len(self.api.get('/api/requests/?q=OTHER-SECRET').data), 0)

    def test_new_status_assignment_consistency_on_both_write_routes(self):
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'assigned_technician': self.tech.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'assigned_technician': self.tech.pk, 'status': 'pending'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.api.post(self.timeline(), {'kind': 'status_changed', 'status_after': 'new'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_commercial_request_status_is_not_overwritten_by_report_edits(self):
        for state in ['quotation', 'pending', 'approved', 'rejected', 'exchange', 'closed']:
            self.request.status = state
            self.request.save()
            response = self.api.post('/api/interventions/', {'service_request': self.request.pk, 'status': 'in_progress'}, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            pk = response.data['id']
            self.api.patch(f'/api/interventions/{pk}/', {'diagnosis': 'Diagnostic actualisé'}, format='json')
            self.request.refresh_from_db()
            self.assertEqual(self.request.status, state)

    def test_checklist_changes_are_named_and_notes_remain_private(self):
        response = self.api.post('/api/interventions/', {'service_request': self.request.pk, 'structured_data': {'maintenance': {'overload': True}}, 'internal_notes': 'SECRET_INTERVENTION'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data['id']
        self.api.patch(f'/api/interventions/{pk}/', {'structured_data': {'maintenance': {'overload': False}}}, format='json')
        public = self.api.get(self.timeline()).data
        self.assertIn('Surcharge : coché', str(public))
        self.assertIn('Surcharge : décoché', str(public))
        self.api.force_authenticate(self.customer)
        public = self.api.get(self.timeline()).data
        self.assertNotIn('SECRET_INTERVENTION', str(public))

    def test_exchange_event_is_on_both_equipment_without_changing_owner(self):
        response = self.api.post('/api/interventions/', {'service_request': self.request.pk, 'kind': 'exchange', 'replacement_equipment': self.replacement.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        for equipment in [self.equipment, self.replacement]:
            timeline = self.api.get(f'/api/equipment/{equipment.pk}/timeline/').data
            self.assertIn('OPERATIONS-LAB-001', str(timeline))
            self.assertIn('OPERATIONS-LAB-002', str(timeline))
        response = self.api.patch(f'/api/equipment/{self.replacement.pk}/', {'client': self.other_company.pk}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_historical_equipment_and_request_cannot_be_reparented(self):
        self.assertEqual(self.api.patch(f'/api/equipment/{self.equipment.pk}/', {'client': self.other_company.pk}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(f'/api/requests/{self.request.pk}/', {'equipment': self.other_equipment.pk}, format='json').status_code, 400)

    def test_actor_name_is_snapshot_and_events_are_immutable(self):
        response = self.api.post(self.timeline(), {'kind': 'observation', 'observation': 'Observation conservée'}, format='json')
        event = OperationEvent.objects.get(pk=response.data['id'])
        old_name = event.actor_label
        self.manager.first_name = 'Renommé'
        self.manager.save()
        event.refresh_from_db()
        self.assertEqual(event.actor_label, old_name)
        event.summary = 'Écrasement'
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            OperationEvent.objects.filter(pk=event.pk).update(summary='Écrasement')
        with self.assertRaises(ValidationError):
            event.delete()

    @skipUnless(connection.vendor == 'postgresql', 'Protection PostgreSQL réelle')
    def test_postgresql_rejects_raw_sql_event_rewrite(self):
        event = self.request.operation_events.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE core_operationevent SET summary=%s WHERE id=%s', ['Écrasement interdit', event.pk])
        event.refresh_from_db()
        self.assertNotEqual(event.summary, 'Écrasement interdit')

    def test_baseline_preserves_known_creation_date_without_fabricating_history(self):
        module = import_module('core.migrations.0005_request_workflow_operationevent')
        before = timezone.now()
        module.baseline(apps, SimpleNamespace(connection=connection))
        event = self.request.operation_events.get(source='baseline', intervention=None)
        self.assertGreaterEqual(event.created_at, before)
        self.assertEqual(event.recorded_created_at, self.request.created_at)
        self.assertEqual(event.status_before, '')
        self.assertIn('ne date pas une transition', event.summary)

    def test_contract_warranty_and_part_consumption_are_real_operations(self):
        today = timezone.localdate()
        Warranty.objects.create(equipment=self.equipment, starts_on=today, ends_on=today + timedelta(days=30))
        Contract.objects.create(number='CTR-OPERATIONS-LAB', client=self.company, equipment=self.equipment, starts_on=today, ends_on=today + timedelta(days=30))
        intervention = Intervention.objects.create(service_request=self.request, technician=self.tech)
        part = Part.objects.create(sku='PART-OPERATIONS-LAB', name='Pièce fictive', stock_quantity=2)
        response = self.api.post(f'/api/interventions/{intervention.pk}/use-part/', {'part': part.pk, 'quantity': 1}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        timeline = self.api.get(f'/api/equipment/{self.equipment.pk}/timeline/').data
        kinds = {row['kind'] for row in timeline}
        self.assertTrue({'contract_created', 'warranty_created', 'part_used'} <= kinds)

    def test_timeline_requires_csrf_for_session_write(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.manager)
        response = client.post(self.timeline(), {'kind': 'observation', 'observation': 'CSRF absent'}, format='json')
        self.assertEqual(response.status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Verrouillage PostgreSQL réel')
class ConcurrentRequestOperationTests(TransactionTestCase):
    def test_concurrent_state_changes_form_one_continuous_history(self):
        manager = User.objects.create_user('concurrent-workflow-manager', role='manager')
        company = Client.objects.create(name='Client concurrence fictif')
        equipment = Equipment.objects.create(client=company, serial_number='CONCURRENT-LAB-ONLY', model='Laboratoire fictif')
        service_request = ServiceRequest.objects.create(equipment=equipment, subject='Deux opérations simultanées')
        ready = Barrier(2)

        def change_status(target):
            try:
                user = User.objects.get(pk=manager.pk)
                client = APIClient()
                client.force_authenticate(user)
                ready.wait(timeout=10)
                response = client.post(f'/api/requests/{service_request.pk}/timeline/', {'kind': 'status_changed', 'status_after': target}, format='json')
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(change_status, ['testing', 'closed']))
        self.assertEqual(statuses, [201, 201])
        events = list(service_request.operation_events.filter(kind='status_changed').order_by('id'))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].status_before, 'new')
        self.assertEqual(events[1].status_before, events[0].status_after)
        service_request.refresh_from_db()
        self.assertEqual(events[-1].status_after, service_request.status)
