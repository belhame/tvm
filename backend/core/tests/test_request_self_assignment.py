from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.request_assignment import (AssignmentConflict, MAX_REVISION, assign_request, assignment_payload,
    claim_request, confirm_assignment, takeover_request, technician_has_accepted_assignment)
from core.request_tracking import write_followup
from core.workflow_events import actor_context

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RequestSelfAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('self-assignment-manager', role='manager')
        cls.admin = User.objects.create_user('self-assignment-admin', role='admin')
        cls.tech = User.objects.create_user('self-assignment-tech', role='technician')
        cls.other = User.objects.create_user('self-assignment-other', role='technician')
        cls.third = User.objects.create_user('self-assignment-third', role='technician')
        cls.inactive = User.objects.create_user('self-assignment-inactive', role='technician', is_active=False)
        cls.courier = User.objects.create_user('self-assignment-courier', role='courier')
        cls.company = Client.objects.create(name='Centre prise en charge personnelle fictif')
        cls.customer = User.objects.create_user('self-assignment-client', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='SELF-ASSIGNMENT-LAB-001', model='Fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Prise en charge personnelle fictive')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.tech)

    def path(self, mode='claim'):
        return f'/api/requests/{self.request.pk}/assignment/{mode}/'

    def assign_old(self, *, accepted=True, technician=None):
        technician = technician or self.other
        self.request.refresh_from_db()
        record = assign_request(self.request.pk, actor=self.manager, technician_id=technician.pk,
                                expected_revision=self.request.assignment_revision)
        if accepted:
            record = confirm_assignment(record.pk, actor=technician, expected_revision=record.assignment_revision, accept=True)
        return record

    def test_claim_assigns_and_accepts_atomically_with_server_actor(self):
        response = self.api.post(self.path(), {'expected_revision': 0}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        record = ServiceRequest.objects.get(pk=self.request.pk)
        self.assertEqual((record.assigned_technician_id, record.assignment_revision, record.status), (self.tech.pk, 1, 'pending'))
        self.assertEqual(record.assignment_accepted_by_id, self.tech.pk)
        self.assertEqual(record.assignment_accepted_revision, record.assignment_revision)
        self.assertGreaterEqual(record.assignment_accepted_at, record.assigned_at)
        self.assertTrue(response.data['assignment']['accepted'])
        self.assertTrue(response.data['assignment']['can_write_followup'])
        self.assertFalse(response.data['assignment']['can_confirm'])
        self.assertFalse(response.data['assignment']['can_claim'])
        self.assertFalse(response.data['assignment']['can_takeover'])
        kinds = set(record.operation_events.values_list('kind', flat=True))
        self.assertTrue({'assignment_changed', 'assignment_accepted', 'assignment_claimed'} <= kinds)

    def test_takeover_preserves_state_previous_sheets_authors_and_private_history(self):
        old = self.assign_old()
        old.status = 'testing'
        old.save(update_fields=['status'])
        visit = Intervention.objects.create(service_request=old, technician=self.other, diagnosis='Diagnostic ancien conservé', internal_notes='PRIVATE_OLD_SHEET')
        old_events = list(old.operation_events.values('id', 'actor_id', 'kind', 'summary', 'observation', 'created_at'))
        response = self.api.post(self.path('takeover'), {'expected_revision': old.assignment_revision, 'reason': 'PRIVATE_RELAY_REASON'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        current = ServiceRequest.objects.get(pk=old.pk)
        self.assertEqual(current.status, 'testing')
        self.assertEqual(current.assignment_revision, old.assignment_revision + 1)
        self.assertEqual(current.assignment_accepted_by_id, self.tech.pk)
        visit.refresh_from_db()
        self.assertEqual((visit.technician_id, visit.diagnosis), (self.other.pk, 'Diagnostic ancien conservé'))
        self.assertEqual(list(current.operation_events.filter(pk__in=[event['id'] for event in old_events]).values('id', 'actor_id', 'kind', 'summary', 'observation', 'created_at')), old_events)
        relay = current.operation_events.get(kind='assignment_taken_over')
        self.assertTrue(relay.is_internal)
        self.assertEqual(relay.actor_id, self.tech.pk)
        self.assertIn(self.other.username, relay.summary)
        self.assertTrue(current.operation_events.filter(kind='assignment_changed', observation='PRIVATE_RELAY_REASON', is_internal=True).exists())
        self.api.force_authenticate(self.customer)
        timeline = self.api.get(f'/api/requests/{old.pk}/timeline/').data
        self.assertNotIn('PRIVATE_RELAY_REASON', str(timeline))
        self.assertNotIn('PRIVATE_OLD_SHEET', str(timeline))
        self.assertNotIn('assignment_taken_over', str(timeline))

    def test_relay_can_follow_up_and_create_own_visit_but_neither_actor_can_edit_old_visit(self):
        old = self.assign_old()
        old_visit = Intervention.objects.create(service_request=old, technician=self.other, diagnosis='Version antérieure')
        new = takeover_request(old.pk, actor=self.tech, expected_revision=old.assignment_revision, reason='Relais de laboratoire')
        self.assertTrue(technician_has_accepted_assignment(self.tech, new))
        self.assertFalse(technician_has_accepted_assignment(self.other, new))
        payload = {'status': 'maintenance', 'expected_status': new.status, 'assignment_revision': new.assignment_revision,
                   'observation': 'Contrôle de la panne repris par le nouveau technicien.'}
        followed = self.api.post(f'/api/requests/{new.pk}/followup/', payload, format='json')
        self.assertEqual(followed.status_code, 201, followed.data)
        self.assertEqual(self.api.patch(f'/api/interventions/{old_visit.pk}/', {'diagnosis': 'Écrasé'}, format='json').status_code, 403)
        own = self.api.post('/api/interventions/', {'service_request': new.pk, 'diagnosis': 'Nouvelle visite de relais'}, format='json')
        self.assertEqual(own.status_code, 201, own.data)
        self.assertEqual(own.data['technician'], self.tech.pk)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.patch(f'/api/interventions/{old_visit.pk}/', {'diagnosis': 'Ancien auteur'}, format='json').status_code, 403)
        self.assertEqual(self.api.post(f'/api/requests/{new.pk}/followup/', payload, format='json').status_code, 403)
        old_visit.refresh_from_db()
        self.assertEqual(old_visit.diagnosis, 'Version antérieure')

    def test_claim_refuses_any_existing_assignee_including_self_unconfirmed(self):
        old = self.assign_old(accepted=False, technician=self.tech)
        count = OperationEvent.objects.count()
        response = self.api.post(self.path(), {'expected_revision': old.assignment_revision}, format='json')
        self.assertEqual(response.status_code, 409)
        response = self.api.post(self.path('takeover'), {'expected_revision': old.assignment_revision, 'reason': 'Même personne'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(OperationEvent.objects.count(), count)
        old.refresh_from_db()
        self.assertIsNone(old.assignment_accepted_at)
        self.assertTrue(assignment_payload(old, self.tech)['can_confirm'])

    def test_takeover_requires_existing_different_assignee(self):
        self.assertEqual(self.api.post(self.path('takeover'), {'expected_revision': 0, 'reason': 'Sans personne précédente'}, format='json').status_code, 409)
        old = self.assign_old(accepted=False)
        current = takeover_request(old.pk, actor=self.tech, expected_revision=old.assignment_revision, reason='Reprise sans confirmation antérieure')
        self.assertTrue(technician_has_accepted_assignment(self.tech, current))

    def test_takeover_can_resolve_an_inactive_previous_assignee(self):
        old = self.assign_old()
        User.objects.filter(pk=self.other.pk).update(is_active=False)
        result = takeover_request(old.pk, actor=self.tech, expected_revision=old.assignment_revision, reason='Ancien intervenant indisponible')
        self.assertEqual(result.assignment_accepted_by_id, self.tech.pk)

    def test_closed_claim_and_takeover_are_rejected_without_mutation(self):
        ServiceRequest.objects.filter(pk=self.request.pk).update(status='closed')
        self.assertEqual(self.api.post(self.path(), {'expected_revision': 0}, format='json').status_code, 409)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.assigned_technician_id)
        # Historical closure with an assignee is also not a relay opportunity.
        self.request.status = 'pending'
        self.request.save(update_fields=['status'])
        old = self.assign_old()
        ServiceRequest.objects.filter(pk=old.pk).update(status='closed')
        count = OperationEvent.objects.count()
        response = self.api.post(self.path('takeover'), {'expected_revision': old.assignment_revision, 'reason': 'Tentative clôturée'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(OperationEvent.objects.count(), count)

    def test_stale_claim_takeover_and_previous_followup_do_not_mutate(self):
        old = self.assign_old()
        self.assertEqual(self.api.post(self.path(), {'expected_revision': 0}, format='json').status_code, 409)
        self.assertEqual(self.api.post(self.path('takeover'), {'expected_revision': 0, 'reason': 'Ancienne révision'}, format='json').status_code, 409)
        stale_followup = {'status': 'maintenance', 'expected_status': old.status, 'assignment_revision': old.assignment_revision, 'observation': 'Ancien formulaire'}
        current = takeover_request(old.pk, actor=self.tech, expected_revision=old.assignment_revision, reason='Reprise courante')
        # Even if a former technician later takes the relay back, a stale
        # follow-up at the old revision must not become valid again.
        back = takeover_request(old.pk, actor=self.other, expected_revision=current.assignment_revision, reason='Deuxième relais')
        count = OperationEvent.objects.count()
        self.api.force_authenticate(self.other)
        response = self.api.post(f'/api/requests/{back.pk}/followup/', stale_followup, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(OperationEvent.objects.count(), count)

    def test_only_active_technicians_can_use_self_service_and_actor_is_refreshed(self):
        for actor in [self.admin, self.manager, self.customer, self.courier, self.inactive]:
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.post(self.path(), {'expected_revision': 0}, format='json').status_code, 403)
            with self.assertRaises(PermissionDenied):
                claim_request(self.request.pk, actor=actor, expected_revision=0)
        for changes in [{'is_active': False}, {'role': 'manager'}]:
            User.objects.filter(pk=self.tech.pk).update(**changes)
            with self.assertRaises(PermissionDenied):
                claim_request(self.request.pk, actor=self.tech, expected_revision=0)
            User.objects.filter(pk=self.tech.pk).update(is_active=True, role='technician')

    def test_strict_inputs_reject_targets_forged_tokens_and_invalid_revisions_or_reason(self):
        for payload in [{'expected_revision': 0, 'technician': self.other.pk}, {'expected_revision': 0, '_self_assignment_token': True},
                        {'expected_revision': True}, {'expected_revision': 0.0}, {'expected_revision': '0'}, {},
                        {'expected_revision': 0, 'accept': True}]:
            self.assertEqual(self.api.post(self.path(), payload, format='json').status_code, 400)
        old = self.assign_old()
        for reason in ['', '  ', 123, '\x00', 'x' * 2001]:
            self.assertEqual(self.api.post(self.path('takeover'), {'expected_revision': old.assignment_revision, 'reason': reason}, format='json').status_code, 400)
        malformed_unicode = ('{"expected_revision":' + str(old.assignment_revision) + ',"reason":"\\ud800"}').encode('ascii')
        self.assertEqual(self.api.post(self.path('takeover'), malformed_unicode, content_type='application/json').status_code, 400)

    def test_read_capabilities_are_role_scoped_without_user_queries(self):
        record = ServiceRequest.objects.select_related('assigned_technician', 'assignment_accepted_by').get(pk=self.request.pk)
        with self.assertNumQueries(0):
            own = assignment_payload(record, self.tech)
            self.assertTrue(own['can_claim'])
            self.assertFalse(own['can_takeover'])
            for actor in [self.manager, self.admin, self.customer, self.courier, self.inactive]:
                flags = assignment_payload(record, actor)
                self.assertFalse(flags['can_claim'])
                self.assertFalse(flags['can_takeover'])
        old = self.assign_old()
        flags = assignment_payload(old, self.tech)
        self.assertTrue(flags['can_takeover'])
        self.assertFalse(flags['can_claim'])
        old.status = 'closed'
        self.assertFalse(assignment_payload(old, self.tech)['can_takeover'])

    def test_generic_assignment_is_still_forbidden_and_forged_model_token_does_not_work(self):
        with self.assertRaises(PermissionDenied):
            assign_request(self.request.pk, actor=self.tech, technician_id=self.tech.pk, expected_revision=0)
        response = self.api.patch(f'/api/requests/{self.request.pk}/', {'assigned_technician': self.tech.pk, 'status': 'pending'}, format='json')
        self.assertEqual(response.status_code, 403)
        for token in ['_SELF_ASSIGNMENT_TOKEN', object()]:
            record = ServiceRequest.objects.get(pk=self.request.pk)
            record.assigned_technician = self.tech
            record._self_assignment_token = token
            with actor_context(self.tech), self.assertRaises(PermissionDenied):
                record.save(update_fields=['assigned_technician'])

    def test_assignment_and_all_events_roll_back_if_acceptance_fails(self):
        count = OperationEvent.objects.count()
        with patch('core.request_assignment.confirm_assignment', side_effect=ValidationError('Refus synthétique pour tester atomicité')):
            with self.assertRaises(ValidationError):
                claim_request(self.request.pk, actor=self.tech, expected_revision=0)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.assigned_technician_id)
        self.assertEqual(self.request.assignment_revision, 0)
        self.assertIsNone(self.request.assignment_accepted_at)
        self.assertEqual(OperationEvent.objects.count(), count)

    def test_revision_exhaustion_never_wraps_or_writes_history(self):
        ServiceRequest.objects.filter(pk=self.request.pk).update(assignment_revision=MAX_REVISION)
        count = OperationEvent.objects.count()
        with self.assertRaises(ValidationError):
            claim_request(self.request.pk, actor=self.tech, expected_revision=MAX_REVISION)
        self.request.refresh_from_db()
        self.assertIsNone(self.request.assigned_technician_id)
        self.assertEqual(OperationEvent.objects.count(), count)

    def test_self_service_requires_csrf_for_a_real_session(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.tech)
        self.assertEqual(client.post(self.path(), {'expected_revision': 0}, format='json').status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Verrous PostgreSQL réels')
class ConcurrentRequestSelfAssignmentTests(TransactionTestCase):
    def setUp(self):
        self.manager = User.objects.create_user('self-concurrent-manager', role='manager')
        self.tech = User.objects.create_user('self-concurrent-tech', role='technician')
        self.other = User.objects.create_user('self-concurrent-other', role='technician')
        self.third = User.objects.create_user('self-concurrent-third', role='technician')
        company = Client.objects.create(name='Centre concurrence relais fictif')
        equipment = Equipment.objects.create(client=company, serial_number='SELF-ASSIGNMENT-CONCURRENT', model='Fictif')
        self.request = ServiceRequest.objects.create(equipment=equipment, subject='Relais concurrents')

    def concurrent(self, functions):
        ready = Barrier(len(functions))
        def execute(function):
            try:
                ready.wait(timeout=10)
                return function()
            except AssignmentConflict:
                return 'conflict'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(execute, functions, timeout=30))

    def test_two_claims_have_exactly_one_winner_and_one_current_acceptance(self):
        outcomes = self.concurrent([
            lambda: claim_request(self.request.pk, actor=self.tech, expected_revision=0).assigned_technician_id,
            lambda: claim_request(self.request.pk, actor=self.other, expected_revision=0).assigned_technician_id,
        ])
        self.assertEqual(outcomes.count('conflict'), 1)
        self.request.refresh_from_db()
        self.assertEqual(self.request.assignment_revision, 1)
        self.assertEqual(self.request.assignment_accepted_by_id, self.request.assigned_technician_id)
        self.assertEqual(self.request.operation_events.filter(kind='assignment_claimed').count(), 1)
        self.assertEqual(self.request.operation_events.filter(kind='assignment_accepted').count(), 1)

    def test_two_takeovers_at_same_revision_have_one_winner_and_no_old_acceptance(self):
        first = claim_request(self.request.pk, actor=self.tech, expected_revision=0)
        outcomes = self.concurrent([
            lambda: takeover_request(first.pk, actor=self.other, expected_revision=first.assignment_revision, reason='Relais B').assigned_technician_id,
            lambda: takeover_request(first.pk, actor=self.third, expected_revision=first.assignment_revision, reason='Relais C').assigned_technician_id,
        ])
        self.assertEqual(outcomes.count('conflict'), 1)
        self.request.refresh_from_db()
        self.assertEqual(self.request.assignment_revision, 2)
        self.assertNotEqual(self.request.assigned_technician_id, self.tech.pk)
        self.assertEqual(self.request.assignment_accepted_by_id, self.request.assigned_technician_id)
        self.assertEqual(self.request.operation_events.filter(kind='assignment_taken_over').count(), 1)

    def test_followup_racing_takeover_is_linear_and_old_technician_loses_future_writes(self):
        first = claim_request(self.request.pk, actor=self.tech, expected_revision=0)
        payload = {'status': 'maintenance', 'expected_status': first.status, 'assignment_revision': first.assignment_revision,
                   'observation': 'Contrôle en cours avant relais éventuel.'}
        def followup():
            try:
                return write_followup(first.pk, payload, actor=self.tech).service_request.status
            except PermissionDenied:
                return 'denied'
        outcomes = self.concurrent([
            followup,
            lambda: takeover_request(first.pk, actor=self.other, expected_revision=first.assignment_revision, reason='Relais simultané').assigned_technician_id,
        ])
        self.assertIn(outcomes[0], ('maintenance', 'denied'))
        self.request.refresh_from_db()
        self.assertEqual(self.request.assigned_technician_id, self.other.pk)
        self.assertTrue(technician_has_accepted_assignment(self.other, self.request))
        with self.assertRaises(PermissionDenied):
            write_followup(first.pk, {**payload, 'assignment_revision': self.request.assignment_revision, 'expected_status': self.request.status}, actor=self.tech)
