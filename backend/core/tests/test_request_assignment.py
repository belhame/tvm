from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.request_assignment import (AssignmentConflict, assign_request, assignment_is_accepted,
    assignment_payload, confirm_assignment, require_accepted_assignment, require_internal_actor,
    technician_has_accepted_assignment)

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RequestAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('assignment-manager', role='manager')
        cls.admin = User.objects.create_user('assignment-admin', role='admin')
        cls.tech = User.objects.create_user('assignment-tech', role='technician')
        cls.other = User.objects.create_user('assignment-other', role='technician')
        cls.inactive = User.objects.create_user('assignment-inactive', role='technician', is_active=False)
        cls.courier = User.objects.create_user('assignment-courier', role='courier')
        cls.company = Client.objects.create(name='Centre affectations fictif')
        cls.customer = User.objects.create_user('assignment-client', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='ASSIGNMENT-LAB-001', model='Fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Prise en charge fictive')

    def assign(self, technician=None, *, actor=None, expected_revision=None):
        self.request.refresh_from_db()
        return assign_request(self.request.pk, actor=actor or self.manager,
                              technician_id=(technician or self.tech).pk,
                              expected_revision=self.request.assignment_revision if expected_revision is None else expected_revision)

    def accept(self, record, *, actor=None, **kwargs):
        return confirm_assignment(record.pk, actor=actor or self.tech,
                                  expected_revision=record.assignment_revision, accept=True, **kwargs)

    def test_assignment_is_revisioned_pending_and_awaits_explicit_acceptance(self):
        before = timezone.now()
        record = self.assign()
        self.assertEqual((record.assignment_revision, record.status), (1, 'pending'))
        self.assertGreaterEqual(record.assigned_at, before)
        self.assertIsNone(record.assignment_accepted_at)
        self.assertFalse(assignment_is_accepted(record))
        event = record.operation_events.get(kind='assignment_changed')
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertTrue(event.is_internal)
        self.assertIn('Non affecté → assignment-tech', event.summary)

    def test_acceptance_confirms_only_current_revision_without_changing_status(self):
        record = self.assign()
        before = timezone.now()
        accepted = self.accept(record)
        self.assertEqual(accepted.status, 'pending')
        self.assertEqual(accepted.assignment_accepted_revision, record.assignment_revision)
        self.assertEqual(accepted.assignment_accepted_by_id, self.tech.pk)
        self.assertGreaterEqual(accepted.assignment_accepted_at, before)
        self.assertTrue(technician_has_accepted_assignment(self.tech, accepted))
        self.assertFalse(technician_has_accepted_assignment(self.other, accepted))

    def test_no_cancels_without_any_write_or_event(self):
        record = self.assign()
        stamp = record.updated_at
        count = OperationEvent.objects.count()
        result = confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=False)
        self.assertFalse(assignment_is_accepted(result))
        result.refresh_from_db()
        self.assertEqual(result.updated_at, stamp)
        self.assertEqual(OperationEvent.objects.count(), count)

    def test_retry_acceptance_is_idempotent(self):
        record = self.accept(self.assign())
        stamp = record.assignment_accepted_at
        count = record.operation_events.filter(kind='assignment_accepted').count()
        again = self.accept(record)
        self.assertEqual(again.assignment_accepted_at, stamp)
        self.assertEqual(again.operation_events.filter(kind='assignment_accepted').count(), count)

    def test_reassign_away_and_back_invalidates_old_acceptance_and_old_revision(self):
        first = self.accept(self.assign())
        second = assign_request(first.pk, actor=self.manager, technician_id=self.other.pk, expected_revision=first.assignment_revision)
        self.assertEqual(second.assignment_revision, 2)
        self.assertFalse(assignment_is_accepted(second))
        current = assign_request(first.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=second.assignment_revision)
        self.assertEqual(current.assignment_revision, 3)
        self.assertIsNone(current.assignment_accepted_at)
        with self.assertRaises(AssignmentConflict):
            confirm_assignment(current.pk, actor=self.tech, expected_revision=first.assignment_revision, accept=True)
        self.assertFalse(technician_has_accepted_assignment(self.tech, current))

    def test_same_assignment_is_noop_but_obsolete_same_choice_is_conflict(self):
        record = self.accept(self.assign())
        before = OperationEvent.objects.count()
        same = assign_request(record.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=record.assignment_revision)
        self.assertEqual(same.assignment_accepted_at, record.assignment_accepted_at)
        self.assertEqual(OperationEvent.objects.count(), before)
        with self.assertRaises(AssignmentConflict):
            assign_request(record.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=0)

    def test_unassignment_resets_acceptance_without_restarting_status(self):
        record = self.accept(self.assign())
        result = assign_request(record.pk, actor=self.manager, technician_id=None, expected_revision=record.assignment_revision)
        self.assertEqual(result.status, 'pending')
        self.assertIsNone(result.assigned_technician_id)
        self.assertIsNone(result.assigned_at)
        self.assertIsNone(result.assignment_accepted_at)
        self.assertEqual(result.assignment_revision, 2)

    def test_technician_cannot_self_assign_or_confirm_another_technician(self):
        with self.assertRaises(PermissionDenied):
            self.assign(actor=self.tech)
        record = self.assign()
        with self.assertRaises(PermissionDenied):
            self.accept(record, actor=self.other)
        with self.assertRaises(PermissionDenied):
            self.accept(record, actor=self.manager)

    def test_manager_and_admin_can_be_assigned_and_confirm_their_own_work(self):
        for actor in [self.manager, self.admin]:
            record = self.assign(actor)
            accepted = self.accept(record, actor=actor)
            self.assertTrue(assignment_is_accepted(accepted))

    def test_admin_proxy_requires_reason_and_has_separate_private_trace(self):
        record = self.assign()
        with self.assertRaises(ValidationError):
            self.accept(record, actor=self.admin, on_behalf=True)
        with self.assertRaises(PermissionDenied):
            self.accept(record, actor=self.manager, on_behalf=True, reason='Motif non autorisé')
        result = self.accept(record, actor=self.admin, on_behalf=True, reason='PRIVATE_OVERRIDE_REASON')
        self.assertEqual(result.assignment_accepted_by_id, self.admin.pk)
        override = result.operation_events.get(kind='assignment_override')
        self.assertEqual(override.observation, 'PRIVATE_OVERRIDE_REASON')
        self.assertTrue(override.is_internal)
        payload = assignment_payload(result, self.customer)
        self.assertIsNone(payload['accepted_by'])
        self.assertEqual(payload['accepted_by_name'], 'Équipe SAV')
        self.assertNotIn('PRIVATE_OVERRIDE_REASON', str(payload))

    def test_inactive_external_and_forged_targets_are_rejected(self):
        for user in [self.inactive, self.customer, self.courier]:
            with self.assertRaises(ValidationError):
                self.assign(user)
        for identifier in [True, 1.5, '1', -1]:
            with self.assertRaises(ValidationError):
                assign_request(self.request.pk, actor=self.manager, technician_id=identifier, expected_revision=0)

    def test_actor_is_reloaded_when_disabled_or_changed_after_authentication(self):
        record = self.assign()
        User.objects.filter(pk=self.tech.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.accept(record)
        User.objects.filter(pk=self.manager.pk).update(role='technician')
        with self.assertRaises(PermissionDenied):
            assign_request(record.pk, actor=self.manager, technician_id=self.other.pk, expected_revision=record.assignment_revision)

    def test_admin_and_manager_writes_do_not_require_acceptance_but_refresh_role(self):
        record = self.assign()
        self.assertEqual(require_accepted_assignment(self.manager, record).pk, self.manager.pk)
        self.assertEqual(require_accepted_assignment(self.admin, record).pk, self.admin.pk)
        User.objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            require_accepted_assignment(self.manager, record)

    def test_old_visit_assignment_alone_never_grants_current_write_permission(self):
        Intervention.objects.create(service_request=self.request, technician=self.tech)
        self.assertFalse(technician_has_accepted_assignment(self.tech, self.request))
        with self.assertRaises(PermissionDenied):
            require_accepted_assignment(self.tech, self.request)
        current = self.accept(self.assign(self.other), actor=self.other)
        self.assertFalse(technician_has_accepted_assignment(self.tech, current))

    def test_model_save_covers_generic_reassignment_and_resets_every_acceptance_field(self):
        record = self.accept(self.assign())
        record.assigned_technician = self.other
        record.save(update_fields=['assigned_technician'])
        record.refresh_from_db()
        self.assertEqual(record.assignment_revision, 2)
        self.assertIsNone(record.assignment_accepted_at)
        self.assertIsNone(record.assignment_accepted_by_id)
        self.assertIsNone(record.assignment_accepted_revision)
        self.assertEqual(record.operation_events.filter(kind='assignment_changed').count(), 2)

    def test_acceptance_metadata_cannot_be_forged_through_ordinary_save(self):
        record = self.assign()
        record.assignment_accepted_at = timezone.now()
        record.assignment_accepted_by = self.tech
        record.assignment_accepted_revision = record.assignment_revision
        with self.assertRaises(AssignmentConflict):
            record.save()

    def test_legacy_assignee_remains_unconfirmed_without_fabricating_assignment_date(self):
        record = self.assign()
        ServiceRequest.objects.filter(pk=record.pk).update(assignment_revision=0, assigned_at=None)
        record.refresh_from_db()
        self.assertFalse(assignment_is_accepted(record))
        self.assertIsNone(record.assigned_at)
        confirmed = self.accept(record)
        self.assertIsNone(confirmed.assigned_at)
        self.assertEqual(confirmed.assignment_accepted_revision, 0)
        self.assertTrue(assignment_is_accepted(confirmed))

    def test_strict_revision_boolean_and_reason_validation(self):
        record = self.assign()
        for revision in [True, 1.1, '1', -1]:
            with self.assertRaises(ValidationError):
                confirm_assignment(record.pk, actor=self.tech, expected_revision=revision, accept=True)
        for accept in ['true', 1, None]:
            with self.assertRaises(ValidationError):
                confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=accept)
        for reason in [1, 'x' * 2001, '\x00', '\ud800']:
            with self.assertRaises(ValidationError):
                confirm_assignment(record.pk, actor=self.admin, expected_revision=record.assignment_revision, accept=True, on_behalf=True, reason=reason)

    def test_database_constraints_reject_partial_or_obsolete_acceptance(self):
        record = self.assign()
        for values in [dict(assignment_accepted_at=timezone.now()),
                       dict(assignment_accepted_at=timezone.now(), assignment_accepted_by=self.tech),
                       dict(assignment_accepted_at=timezone.now(), assignment_accepted_by=self.tech, assignment_accepted_revision=0)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                ServiceRequest.objects.filter(pk=record.pk).update(**values)

    def test_read_capabilities_do_not_query_users_per_list_row(self):
        record = self.accept(self.assign())
        record = ServiceRequest.objects.select_related('assigned_technician', 'assignment_accepted_by').get(pk=record.pk)
        with self.assertNumQueries(0):
            self.assertTrue(technician_has_accepted_assignment(self.tech, record))
            payload = assignment_payload(record, self.tech)
        self.assertTrue(payload['accepted'])
        self.assertTrue(payload['can_write_followup'])
        self.assertFalse(payload['can_confirm'])

    def test_mutation_refreshes_actor_even_if_read_capability_was_previous_true(self):
        record = self.accept(self.assign())
        self.assertTrue(technician_has_accepted_assignment(self.tech, record))
        User.objects.filter(pk=self.tech.pk).update(role='courier')
        with self.assertRaises(PermissionDenied):
            require_accepted_assignment(self.tech, record)
        with self.assertRaises(PermissionDenied):
            require_internal_actor(self.tech)


@skipUnless(connection.vendor == 'postgresql', 'Verrous PostgreSQL réels')
class ConcurrentRequestAssignmentTests(TransactionTestCase):
    def setUp(self):
        self.manager = User.objects.create_user('concurrent-assignment-manager', role='manager')
        self.tech = User.objects.create_user('concurrent-assignment-tech', role='technician')
        self.other = User.objects.create_user('concurrent-assignment-other', role='technician')
        company = Client.objects.create(name='Centre concurrence affectation fictif')
        equipment = Equipment.objects.create(client=company, serial_number='ASSIGNMENT-CONCURRENT-LAB', model='Fictif')
        self.request = ServiceRequest.objects.create(equipment=equipment, subject='Concurrence prise en charge')

    def run_threads(self, functions):
        ready = Barrier(len(functions))
        def execute(function):
            try:
                ready.wait(timeout=10)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(execute, functions, timeout=30))

    def test_same_revision_two_assignments_have_one_winner_and_one_conflict(self):
        def assign(tech):
            def run():
                try:
                    result = assign_request(self.request.pk, actor=self.manager, technician_id=tech.pk, expected_revision=0)
                    return result.assigned_technician_id
                except AssignmentConflict:
                    return 'conflict'
            return run
        results = self.run_threads([assign(self.tech), assign(self.other)])
        self.assertEqual(results.count('conflict'), 1)
        self.request.refresh_from_db()
        self.assertEqual(self.request.assignment_revision, 1)
        self.assertEqual(self.request.operation_events.filter(kind='assignment_changed').count(), 1)

    def test_simultaneous_confirmation_retry_creates_exactly_one_event(self):
        record = assign_request(self.request.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=0)
        def confirm():
            return confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True).assignment_accepted_at
        results = self.run_threads([confirm, confirm])
        self.assertEqual(results[0], results[1])
        self.assertEqual(record.operation_events.filter(kind='assignment_accepted').count(), 1)

    def test_reassignment_racing_confirmation_never_keeps_old_acceptance(self):
        record = assign_request(self.request.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=0)
        def confirm():
            try:
                confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True)
                return 'accepted'
            except AssignmentConflict:
                return 'conflict'
        def reassign():
            return assign_request(record.pk, actor=self.manager, technician_id=self.other.pk, expected_revision=record.assignment_revision).assignment_revision
        outcomes = self.run_threads([confirm, reassign])
        self.assertIn(outcomes[0], ('accepted', 'conflict'))
        self.request.refresh_from_db()
        self.assertEqual(self.request.assigned_technician_id, self.other.pk)
        self.assertEqual(self.request.assignment_revision, 2)
        self.assertIsNone(self.request.assignment_accepted_at)
        self.assertFalse(assignment_is_accepted(self.request))
