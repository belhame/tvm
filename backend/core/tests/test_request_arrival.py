from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Equipment, OperationEvent, ServiceRequest

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TIME_ZONE='Africa/Lagos')
class RequestArrivalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('arrival-manager', role='manager')
        cls.tech = User.objects.create_user('arrival-tech', role='technician')
        cls.company = Client.objects.create(name='Réception fictive')
        cls.other_company = Client.objects.create(name='Autre réception fictive')
        cls.customer = User.objects.create_user('arrival-client', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='ARRIVAL-LAB-001', model='Laboratoire fictif')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='ARRIVAL-OTHER-001', model='Autre fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Fiche réception fictive')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def endpoint(self, request=None):
        return f'/api/requests/{(request or self.request).pk}/'

    def test_creation_does_not_imply_arrival(self):
        response = self.api.get(self.endpoint())
        self.assertIsNone(response.data['arrived_at'])
        self.assertEqual(response.data['timing']['timer_state'], 'unknown')
        self.assertIsNone(response.data['timing']['elapsed_days'])

    def test_followup_metadata_is_shared_and_explicit(self):
        arrived = timezone.now() - timedelta(hours=3)
        payload = {'arrived_at': arrived.isoformat(), 'client_reference': 'LAB-EXTERNAL-001', 'end_customer': 'Client final fictif',
                   'return_flag': True, 'packaging': 'Carton conservé', 'service_location': 'workshop', 'delivered_by': 'courier',
                   'courier_name': 'Transport fictif', 'accessories': 'Câble secteur', 'warranty_status': 'quotation',
                   'contact_name': 'Contact fictif', 'contact_phone': '0000000000', 'contact_email': 'contact@example.invalid'}
        response = self.api.patch(self.endpoint(), payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        second = APIClient()
        second.force_authenticate(self.tech)
        saved = second.get(self.endpoint()).data
        for field in payload:
            if field != 'arrived_at':
                self.assertEqual(saved[field], payload[field])
        self.assertTrue(self.request.operation_events.filter(summary__contains='Arrivée réelle').exists())

    def test_future_arrival_and_invalid_metadata_are_rejected(self):
        cases = [{'arrived_at': (timezone.now() + timedelta(days=1)).isoformat()}, {'return_flag': 'false'},
                 {'client_reference': 123}, {'service_location': 'unknown-place'}, {'contact_email': 'invalid'}]
        for payload in cases:
            self.assertEqual(self.api.patch(self.endpoint(), payload, format='json').status_code, 400)

    def test_closure_is_server_recorded_frozen_and_reopening_clears_it(self):
        arrived = timezone.now() - timedelta(days=5)
        self.api.patch(self.endpoint(), {'arrived_at': arrived.isoformat()}, format='json')
        before = timezone.now()
        response = self.api.patch(self.endpoint(), {'status': 'closed'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        closed = self.request.closed_at
        self.assertGreaterEqual(closed, before)
        self.assertEqual(response.data['timing']['timer_state'], 'closed')
        frozen = response.data['timing']['elapsed_hours']
        self.api.patch(self.endpoint(), {'description': 'Commentaire postérieur'}, format='json')
        self.request.refresh_from_db()
        self.assertEqual(self.request.closed_at, closed)
        self.assertEqual(self.api.get(self.endpoint()).data['timing']['elapsed_hours'], frozen)
        self.assertEqual(self.api.patch(self.endpoint(), {'closed_at': (closed - timedelta(hours=1)).isoformat()}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(self.endpoint(), {'status': 'pending'}, format='json').status_code, 200)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.closed_at)
        self.assertEqual(self.api.get(self.endpoint()).data['timing']['timer_state'], 'running')

    def test_timeline_closure_uses_same_model_lifecycle(self):
        self.api.patch(self.endpoint(), {'arrived_at': (timezone.now() - timedelta(days=3)).isoformat()}, format='json')
        response = self.api.post(self.endpoint() + 'timeline/', {'kind': 'status_changed', 'status_after': 'closed', 'observation': 'Clôture réelle après réception vérifiée.'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.request.refresh_from_db()
        self.assertIsNotNone(self.request.closed_at)
        self.api.post(self.endpoint() + 'timeline/', {'kind': 'status_changed', 'status_after': 'pending', 'observation': 'Réouverture explicite pour complément de suivi.'}, format='json')
        self.request.refresh_from_db()
        self.assertIsNone(self.request.closed_at)

    def test_old_closed_request_does_not_acquire_fake_closure_date(self):
        old = timezone.now() - timedelta(days=20)
        ServiceRequest.objects.filter(pk=self.request.pk).update(status='closed', arrived_at=old, closed_at=None)
        response = self.api.patch(self.endpoint(), {'description': 'Texte sans date historique'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data['closed_at'])
        self.assertEqual(response.data['timing']['timer_state'], 'unknown')
        real_closure = old + timedelta(days=3)
        response = self.api.patch(self.endpoint(), {'closed_at': real_closure.isoformat()}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.request.refresh_from_db()
        self.assertEqual(self.request.closed_at, real_closure)
        self.assertEqual(response.data['timing']['timer_state'], 'closed')

    def test_closure_completion_must_follow_arrival_and_not_be_future(self):
        arrived = timezone.now() - timedelta(days=10)
        ServiceRequest.objects.filter(pk=self.request.pk).update(status='closed', arrived_at=arrived, closed_at=None)
        for closed in [arrived - timedelta(seconds=1), timezone.now() + timedelta(days=1)]:
            self.assertEqual(self.api.patch(self.endpoint(), {'closed_at': closed.isoformat()}, format='json').status_code, 400)

    def test_technician_and_client_cannot_patch_arrival_or_historical_closure(self):
        for user in [self.tech, self.customer]:
            self.api.force_authenticate(user)
            self.assertEqual(self.api.patch(self.endpoint(), {'arrived_at': (timezone.now() - timedelta(days=1)).isoformat()}, format='json').status_code, 403)
        self.assertEqual(self.api.get(self.endpoint()).status_code, 200)

    def test_overdue_category_uses_business_duration_not_manual_due_date(self):
        now = datetime(2026, 10, 27, 9, 1, tzinfo=datetime_timezone.utc)  # Tuesday 10:01 Lagos.
        arrived = datetime(2026, 10, 23, 9, tzinfo=datetime_timezone.utc)
        late = ServiceRequest.objects.create(equipment=self.equipment, subject='Arrivé vendredi', arrived_at=arrived, status='resolved')
        manual_due = ServiceRequest.objects.create(equipment=self.equipment, subject='Échéance dépassée sans arrivée', due_on=now.date() - timedelta(days=1))
        other = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Autre client en retard', arrived_at=arrived)
        closed = ServiceRequest.objects.create(equipment=self.equipment, subject='Clôturé après retard', arrived_at=arrived)
        ServiceRequest.objects.filter(pk=closed.pk).update(status='closed', closed_at=now - timedelta(seconds=1))
        with patch('django.utils.timezone.now', return_value=now):
            response = self.api.get('/api/requests/?category=overdue')
            self.assertEqual({row['id'] for row in response.data}, {late.pk, other.pk})
            self.assertFalse(self.api.get(self.endpoint(manual_due)).data['is_overdue'])
            self.assertTrue(self.api.get(self.endpoint(manual_due)).data['is_due_overdue'])
            historical = self.api.get(self.endpoint(closed)).data
            self.assertFalse(historical['is_overdue'])
            self.assertTrue(historical['timing']['is_overdue_48h'])
            self.api.force_authenticate(self.customer)
            self.assertEqual({row['id'] for row in self.api.get('/api/requests/?category=overdue').data}, {late.pk})
            categories = self.api.get('/api/requests/categories/').data['categories']
            self.assertEqual(next(row['count'] for row in categories if row['key'] == 'overdue'), 1)

    def test_intake_arrival_is_idempotent_and_different_followup_conflicts(self):
        self.api.force_authenticate(self.tech)
        payload = {'request_key': str(uuid4()), 'serial_number': self.equipment.serial_number, 'equipment': self.equipment.pk,
                   'subject': 'Réception par technicien', 'arrived_at': (timezone.now() - timedelta(hours=1)).isoformat(),
                   'client_reference': 'LAB-INTAKE-ARRIVAL', 'return_flag': True, 'accessories': 'Câble fictif'}
        first = self.api.post('/api/requests/intake/', payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        count = OperationEvent.objects.count()
        second = self.api.post('/api/requests/intake/', payload, format='json')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data['request']['id'], second.data['request']['id'])
        self.assertEqual(first.data['request']['arrived_at'], second.data['request']['arrived_at'])
        self.assertEqual(OperationEvent.objects.count(), count)
        different = {**payload, 'accessories': 'Autre accessoire'}
        self.assertEqual(self.api.post('/api/requests/intake/', different, format='json').status_code, 409)

    def test_old_intake_without_arrival_remains_idempotent(self):
        payload = {'request_key': str(uuid4()), 'serial_number': self.equipment.serial_number, 'equipment': self.equipment.pk, 'subject': 'Intake ancien format'}
        first = self.api.post('/api/requests/intake/', payload, format='json')
        second = self.api.post('/api/requests/intake/', payload, format='json')
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertIsNone(second.data['request']['arrived_at'])
