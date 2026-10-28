"""Follow-up is atomic, private by default, and tied to a current acceptance."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.request_assignment import assign_request, confirm_assignment
from core.request_tracking import write_followup
from core.workflow_events import current_actor


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RequestTrackingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('tracking-admin', role='admin')
        cls.manager = User.objects.create_user('tracking-manager', role='manager')
        cls.tech = User.objects.create_user('tracking-tech', role='technician', first_name='Technicien', last_name='Laboratoire')
        cls.other_tech = User.objects.create_user('tracking-other-tech', role='technician')
        cls.company = Client.objects.create(name='Client du suivi fictif')
        cls.customer = User.objects.create_user('tracking-customer', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='TRACKING-LAB-001', model='Modèle de suivi fictif')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='Dossier sans intervention')
        cls.record = assign_request(cls.record.pk, actor=cls.manager, technician_id=cls.tech.pk, expected_revision=cls.record.assignment_revision)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.tech)

    def endpoint(self):
        return f'/api/requests/{self.record.pk}/followup/'

    def accept(self):
        self.record = confirm_assignment(self.record.pk, actor=self.tech, expected_revision=self.record.assignment_revision, accept=True)

    def payload(self, **changes):
        self.record.refresh_from_db()
        return {'status': 'maintenance', 'expected_status': self.record.status, 'assignment_revision': self.record.assignment_revision, 'observation': 'Recherche de la panne au laboratoire.', **changes}

    def test_pending_confirmation_blocks_followup_without_creating_events(self):
        before = self.record.operation_events.count()
        response = self.api.post(self.endpoint(), self.payload(), format='json')
        self.assertEqual(response.status_code, 403, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'pending')
        self.assertEqual(self.record.operation_events.count(), before)

    def test_accepted_technician_updates_without_a_scheduled_intervention(self):
        self.accept()
        self.assertFalse(self.record.interventions.exists())
        response = self.api.post(self.endpoint(), self.payload(summary='Synthèse privée du dossier.'), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['request']['status'], 'maintenance')
        self.assertEqual(len(response.data['events']), 2)
        public, private = response.data['events']
        self.assertEqual((public['kind'], public['is_internal'], public['observation']), ('status_changed', False, ''))
        self.assertEqual((private['kind'], private['is_internal']), ('summary', True))
        self.assertEqual(private['summary'], 'Synthèse privée du dossier.')
        self.assertEqual(private['source'], 'followup')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(self.record.interventions.exists())
        self.assertEqual(self.record.operation_events.filter(kind='status_changed', status_before='pending', status_after='maintenance').count(), 1)

    def test_private_note_and_summary_never_reach_client_portal(self):
        self.accept()
        response = self.api.post(self.endpoint(), self.payload(observation='PRIVATE-TRACKING-OBSERVATION', summary='PRIVATE-TRACKING-SUMMARY'), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.api.force_authenticate(self.customer)
        history = self.api.get(f'/api/requests/{self.record.pk}/timeline/')
        self.assertEqual(history.status_code, 200)
        self.assertNotIn('PRIVATE-TRACKING', str(history.data))
        self.assertTrue(any(event['status_after'] == 'maintenance' for event in history.data))
        self.assertTrue(all(event['actor_name'] == 'Équipe SAV' for event in history.data))

    def test_explicit_public_followup_shares_only_the_supplied_text(self):
        self.accept()
        response = self.api.post(self.endpoint(), self.payload(is_internal=False, observation='PUBLIC-TRACKING-NOTE', summary='PUBLIC-TRACKING-SUMMARY'), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data['events']), 1)
        self.api.force_authenticate(self.customer)
        history = self.api.get(f'/api/requests/{self.record.pk}/timeline/')
        self.assertIn('PUBLIC-TRACKING-NOTE', str(history.data))
        self.assertIn('PUBLIC-TRACKING-SUMMARY', str(history.data))

    def test_observation_is_required_on_every_transition(self):
        self.accept()
        for observation in ('', '   ', None, 123):
            response = self.api.post(self.endpoint(), self.payload(observation=observation, summary='Une synthèse ne remplace pas le motif.'), format='json')
            self.assertEqual(response.status_code, 400, response.data)
        response = self.api.post(self.endpoint(), {key: value for key, value in self.payload().items() if key != 'observation'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'pending')

    def test_same_state_accepts_summary_only_and_does_not_add_status_event(self):
        self.accept()
        before = self.record.operation_events.filter(kind='status_changed').count()
        response = self.api.post(self.endpoint(), self.payload(status='pending', observation='', summary='Synthèse finale conservée.'), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data['events']), 1)
        self.assertEqual(response.data['events'][0]['kind'], 'summary')
        self.assertEqual(self.record.operation_events.filter(kind='status_changed').count(), before)
        empty = self.api.post(self.endpoint(), self.payload(status='pending', observation='', summary=''), format='json')
        self.assertEqual(empty.status_code, 400)

    def test_status_and_assignment_preconditions_reject_stale_forms(self):
        self.accept()
        initial = self.payload()
        for changes in ({'expected_status': 'testing'}, {'assignment_revision': self.record.assignment_revision + 1}):
            response = self.api.post(self.endpoint(), {**initial, **changes}, format='json')
            self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.api.post(self.endpoint(), initial, format='json').status_code, 201)
        repeated = self.api.post(self.endpoint(), initial, format='json')
        self.assertEqual(repeated.status_code, 409, repeated.data)

    def test_strict_input_rejects_forged_actors_dates_and_scalar_types(self):
        self.accept()
        for changes in ({'actor': self.manager.pk}, {'created_at': '2001-01-01'}, {'summary': 42}, {'observation': 'x' * 10001}, {'summary': 'x' * 10001}, {'is_internal': 'false'}, {'assignment_revision': True}, {'assignment_revision': 1.0}, {'assignment_revision': '1'}, {'observation': 'bad\x00text'}):
            response = self.api.post(self.endpoint(), self.payload(**changes), format='json')
            self.assertEqual(response.status_code, 400, response.data)
        for missing in ('status', 'expected_status', 'assignment_revision'):
            response = self.api.post(self.endpoint(), {key: value for key, value in self.payload().items() if key != missing}, format='json')
            self.assertEqual(response.status_code, 400, response.data)

    def test_reassignment_revokes_old_intervention_and_previous_acceptance(self):
        self.accept()
        Intervention.objects.create(service_request=self.record, technician=self.tech)
        stale_payload = self.payload()
        self.record = assign_request(self.record.pk, actor=self.manager, technician_id=self.other_tech.pk, expected_revision=self.record.assignment_revision)
        before = self.record.operation_events.count()
        self.assertEqual(self.api.post(self.endpoint(), stale_payload, format='json').status_code, 403)
        self.assertEqual(self.api.post(f'/api/requests/{self.record.pk}/timeline/', {'kind': 'observation', 'observation': 'Ancien technicien'}, format='json').status_code, 403)
        self.assertEqual(self.record.operation_events.count(), before)
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.api.post(self.endpoint(), self.payload(), format='json').status_code, 403)

    def test_admin_and_manager_can_follow_up_without_accepting_for_the_technician(self):
        for actor in (self.admin, self.manager):
            self.api.force_authenticate(actor)
            response = self.api.post(self.endpoint(), self.payload(status='pending', observation=f'Observation interne {actor.role}.'), format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.record.refresh_from_db()
            self.assertIsNone(self.record.assignment_accepted_at)

    def test_clients_and_anonymous_users_cannot_write_followup(self):
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.post(self.endpoint(), self.payload(), format='json').status_code, 403)
        self.api.force_authenticate(None)
        self.assertIn(self.api.post(self.endpoint(), self.payload(), format='json').status_code, (401, 403))

    def test_deactivated_or_changed_role_actor_is_rechecked_under_lock(self):
        self.accept()
        User = get_user_model()
        User.objects.filter(pk=self.tech.pk).update(is_active=False)
        # The original authenticated object is intentionally still active in
        # memory: the mutation must read the real user again inside its lock.
        self.assertTrue(self.tech.is_active)
        with self.assertRaises(PermissionDenied):
            write_followup(self.record.pk, self.payload(), actor=self.tech)

    def test_state_and_all_history_roll_back_when_audit_fails(self):
        self.accept()
        before = self.record.operation_events.count()
        with patch('core.request_tracking.AuditLog.objects.create', side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaises(RuntimeError):
                write_followup(self.record.pk, self.payload(), actor=self.tech)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'pending')
        self.assertEqual(self.record.operation_events.count(), before)
        self.assertIsNone(current_actor())

    def test_actor_label_and_timestamp_are_server_snapshots(self):
        self.accept()
        response = self.api.post(self.endpoint(), self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        event = OperationEvent.objects.get(pk=response.data['events'][-1]['id'])
        self.assertEqual(event.actor_id, self.tech.pk)
        self.assertEqual(event.actor_label, 'Technicien Laboratoire')
        self.assertIsNotNone(event.created_at)
        get_user_model().objects.filter(pk=self.tech.pk).update(first_name='Nouveau nom')
        event.refresh_from_db()
        self.assertEqual(event.actor_label, 'Technicien Laboratoire')

    def test_existing_timeline_requires_reason_and_tech_preconditions(self):
        self.accept()
        url = f'/api/requests/{self.record.pk}/timeline/'
        missing = self.api.post(url, {'kind': 'status_changed', 'status_after': 'testing', 'observation': 'Motif réel'}, format='json')
        self.assertEqual(missing.status_code, 400, missing.data)
        payload = self.payload(status='testing')
        payload['kind'] = 'status_changed'
        payload['status_after'] = payload.pop('status')
        response = self.api.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['kind'], 'status_changed')
        self.assertEqual(response.data['observation'], '')
        self.api.force_authenticate(self.manager)
        response = self.api.post(url, {'kind': 'status_changed', 'status_after': 'maintenance', 'summary': 'Pas de motif'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_legacy_note_does_not_revert_a_state_changed_since_the_first_read(self):
        self.accept()
        ServiceRequest.objects.filter(pk=self.record.pk).update(status='testing')
        result = write_followup(self.record.pk, {'status': 'pending', 'observation': 'Note sans transition'}, actor=self.tech, require_preconditions=False, keep_status=True)
        self.assertEqual(result.service_request.status, 'testing')
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].kind, 'observation')

    def test_followup_does_not_manufacture_finance_ready_or_return_evidence(self):
        self.api.force_authenticate(self.admin)
        for state in ('ready_for_delivery', 'return_to_client'):
            before = self.record.operation_events.count()
            response = self.api.post(self.endpoint(), self.payload(status=state), format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(self.record.operation_events.count(), before)
        self.record.status = 'exchange'
        self.record.save(update_fields=['status'])
        response = self.api.post(self.endpoint(), self.payload(status='closed'), format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'exchange')
