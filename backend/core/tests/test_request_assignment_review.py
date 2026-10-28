"""Independent write-barrier checks for explicitly accepted SAV assignments."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, Part, ServiceRequest, StockMovement
from core.request_assignment import assign_request, confirm_assignment


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentRequestAssignmentReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Prise En Charge Fictif')
        cls.admin = User.objects.create_user('assignment-review-admin', role='admin')
        cls.manager = User.objects.create_user('assignment-review-manager', role='manager')
        cls.tech = User.objects.create_user('assignment-review-tech', role='technician')
        cls.other_tech = User.objects.create_user('assignment-review-other-tech', role='technician')
        cls.customer = User.objects.create_user('assignment-review-client', role='client', client=cls.company)
        cls.courier = User.objects.create_user('assignment-review-courier', role='courier')
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='ASSIGNMENT-REVIEW-FICTION-001', model='Onduleur fictif')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='Prise en charge fictive', status='pending')
        cls.part = Part.objects.create(sku='ASSIGNMENT-PART-FICTION', name='Pièce de test fictive', stock_quantity=3, min_stock=1)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.tech)
        self.media = TemporaryDirectory(prefix='tvm-assignment-review-')
        self.addCleanup(self.media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=Path(self.media.name)))

    def assign(self, actor=None):
        self.record.refresh_from_db()
        self.record = assign_request(self.record.pk, actor=self.manager,
            technician_id=(actor or self.tech).pk, expected_revision=self.record.assignment_revision)
        return self.record

    def accept(self, actor=None):
        self.record.refresh_from_db()
        self.record = confirm_assignment(self.record.pk, actor=actor or self.tech,
            expected_revision=self.record.assignment_revision, accept=True)
        return self.record

    def followup(self, *, status='maintenance', observation='Observation technique fictive', **changes):
        self.record.refresh_from_db()
        body = {'status': status, 'expected_status': self.record.status,
                'assignment_revision': self.record.assignment_revision, 'observation': observation}
        body.update(changes)
        return self.api.post(f'/api/requests/{self.record.pk}/followup/', body, format='json')

    def denied_write_routes(self, visit):
        bodies = [
            ('patch', f'/api/requests/{self.record.pk}/', {'description': 'FORGED_GENERIC_WRITE'}),
            ('patch', f'/api/interventions/{visit.pk}/', {'diagnosis': 'FORGED_VISIT_WRITE'}),
            ('post', f'/api/requests/{self.record.pk}/timeline/', {'kind': 'observation', 'observation': 'FORGED_TIMELINE_WRITE'}),
            ('post', f'/api/equipment/{self.unit.pk}/timeline/', {'kind': 'summary', 'summary': 'FORGED_EQUIPMENT_TIMELINE_WRITE'}),
            ('post', f'/api/interventions/{visit.pk}/use-part/', {'part': self.part.pk, 'quantity': 1}),
        ]
        for method, url, body in bodies:
            with self.subTest(method=method, url=url):
                response = getattr(self.api, method)(url, body, format='json')
                self.assertEqual(response.status_code, 403, response.json())
        response = self.api.post(f'/api/requests/{self.record.pk}/documents/', {
            'file': SimpleUploadedFile('note-fictive.txt', b'FORGED_DOCUMENT_WRITE', content_type='text/plain')}, format='multipart')
        self.assertEqual(response.status_code, 403, response.json())
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 3)
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(self.record.operation_events.filter(observation__contains='FORGED').exists())

    def test_assignment_without_confirmation_blocks_all_technician_write_paths(self):
        self.assign()
        visit = Intervention.objects.create(service_request=self.record, technician=self.tech)
        self.denied_write_routes(visit)
        self.assertEqual(self.followup().status_code, 403)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.assignment_accepted_at)
        self.assertEqual(self.record.status, 'pending')

    def test_old_intervention_does_not_allow_an_unassigned_technician_to_accept_or_write(self):
        visit = Intervention.objects.create(service_request=self.record, technician=self.tech)
        with self.assertRaises(APIException) as raised:
            self.accept()
        self.assertIn(raised.exception.status_code, (400, 403))
        self.denied_write_routes(visit)
        self.assertEqual(self.followup().status_code, 403)

    def test_reassignment_revokes_old_acceptance_and_historical_visit_rights_immediately(self):
        self.assign()
        self.accept()
        visit = Intervention.objects.create(service_request=self.record, technician=self.tech)
        first_revision = self.record.assignment_revision
        self.assign(self.other_tech)
        self.assertGreater(self.record.assignment_revision, first_revision)
        self.assertIsNone(self.record.assignment_accepted_at)
        self.denied_write_routes(visit)
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.followup().status_code, 403)
        self.accept(self.other_tech)
        response = self.followup()
        self.assertEqual(response.status_code, 201, response.json())
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'maintenance')

    def test_client_courier_anonymous_and_other_technician_cannot_confirm_for_current_owner(self):
        self.assign()
        for actor in (self.customer, self.courier, self.other_tech, AnonymousUser()):
            with self.subTest(actor=getattr(actor, 'role', 'anonymous')), self.assertRaises(PermissionDenied):
                confirm_assignment(self.record.pk, actor=actor, expected_revision=self.record.assignment_revision, accept=True)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.assignment_accepted_at)

    def test_refusal_is_read_only_and_correct_revision_confirmation_replays_without_duplicate_event(self):
        self.assign()
        before = self.record.operation_events.count()
        confirm_assignment(self.record.pk, actor=self.tech, expected_revision=self.record.assignment_revision, accept=False)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.assignment_accepted_at)
        self.assertEqual(self.record.operation_events.count(), before)
        self.accept()
        accepted_at = self.record.assignment_accepted_at
        count = self.record.operation_events.count()
        self.accept()
        self.assertEqual(self.record.assignment_accepted_at, accepted_at)
        self.assertEqual(self.record.operation_events.count(), count)
        with self.assertRaises(APIException) as raised:
            confirm_assignment(self.record.pk, actor=self.tech, expected_revision=self.record.assignment_revision - 1, accept=True)
        self.assertEqual(raised.exception.status_code, 409)

    def test_accepted_technician_still_cannot_bypass_followup_with_generic_patch_or_missing_preconditions(self):
        self.assign()
        self.accept()
        for body in ({'status': 'maintenance'}, {'assigned_technician': self.other_tech.pk},
                     {'assignment_accepted_at': '2000-01-01T00:00:00Z'}):
            response = self.api.patch(f'/api/requests/{self.record.pk}/', body, format='json')
            self.assertEqual(response.status_code, 403, response.json())
        path = f'/api/requests/{self.record.pk}/timeline/'
        response = self.api.post(path, {'kind': 'status_changed', 'status_after': 'maintenance',
            'observation': 'Transition sans préconditions'}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(self.followup(observation='').status_code, 400)
        self.assertEqual(self.followup(assignment_revision=self.record.assignment_revision - 1).status_code, 409)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'pending')

    def test_private_followup_and_admin_proxy_confirmation_never_leak_reason_to_client(self):
        self.assign()
        with self.assertRaises(PermissionDenied):
            confirm_assignment(self.record.pk, actor=self.manager, expected_revision=self.record.assignment_revision,
                               accept=True, on_behalf=True, reason='FORGED_MANAGER_PROXY')
        self.record = confirm_assignment(self.record.pk, actor=self.admin,
            expected_revision=self.record.assignment_revision, accept=True, on_behalf=True,
            reason='PRIVATE_ADMIN_PROXY_REASON')
        response = self.followup(observation='PRIVATE_TECHNICIAN_FOLLOWUP', is_internal=True,
                                 summary='Synthèse explicite de suivi')
        self.assertEqual(response.status_code, 201, response.json())
        self.api.force_authenticate(self.customer)
        timeline = self.api.get(f'/api/requests/{self.record.pk}/timeline/')
        self.assertEqual(timeline.status_code, 200, timeline.json())
        for private in ('PRIVATE_ADMIN_PROXY_REASON', 'PRIVATE_TECHNICIAN_FOLLOWUP', self.admin.username):
            self.assertNotIn(private, str(timeline.json()))

    def test_clients_and_couriers_cannot_append_followup_even_with_current_revision(self):
        self.assign()
        self.accept()
        for actor in (self.customer, self.courier, None):
            self.api.force_authenticate(actor)
            response = self.followup()
            self.assertIn(response.status_code, (401, 403), response.json())
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'pending')

    def test_confirmation_http_route_rejects_other_roles_and_strictly_validates_acceptance(self):
        self.assign()
        url = f'/api/requests/{self.record.pk}/assignment/confirm/'
        body = {'expected_revision': self.record.assignment_revision, 'accept': True}
        for actor in (self.customer, self.courier, None):
            self.api.force_authenticate(actor)
            self.assertIn(self.api.post(url, body, format='json').status_code, (401, 403))
        self.api.force_authenticate(self.tech)
        for changes in ({'accept': 'true'}, {'expected_revision': True}, {'accepted_by': self.admin.pk}):
            response = self.api.post(url, {**body, **changes}, format='json')
            self.assertEqual(response.status_code, 400, response.json())
        malformed = self.api.post(url, [], format='json')
        self.assertEqual(malformed.status_code, 400, malformed.json())
        cancelled = self.api.post(url, {**body, 'accept': False}, format='json')
        self.assertEqual(cancelled.status_code, 200, cancelled.json())
        self.record.refresh_from_db()
        self.assertIsNone(self.record.assignment_accepted_at)
        accepted = self.api.post(url, body, format='json')
        self.assertEqual(accepted.status_code, 200, accepted.json())
        self.record.refresh_from_db()
        self.assertIsNotNone(self.record.assignment_accepted_at)
        stale = self.api.post(url, {**body, 'expected_revision': body['expected_revision'] - 1}, format='json')
        self.assertEqual(stale.status_code, 409, stale.json())

    def test_accepted_technician_status_timeline_alias_requires_and_checks_current_revision(self):
        self.assign()
        self.accept()
        url = f'/api/requests/{self.record.pk}/timeline/'
        body = {'kind': 'status_changed', 'status_after': 'maintenance', 'expected_status': self.record.status,
                'assignment_revision': self.record.assignment_revision, 'observation': 'PRIVATE_STATUS_ALIAS_NOTE'}
        response = self.api.post(url, body, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'maintenance')
        self.assign(self.other_tech)
        self.accept(self.other_tech)
        rejected = self.api.post(url, {**body, 'status_after': 'testing', 'expected_status': 'maintenance',
            'assignment_revision': self.record.assignment_revision}, format='json')
        self.assertEqual(rejected.status_code, 403, rejected.json())
        self.api.force_authenticate(self.customer)
        timeline = self.api.get(url)
        self.assertNotIn('PRIVATE_STATUS_ALIAS_NOTE', str(timeline.json()))

    def test_manager_cannot_forge_readonly_acceptance_metadata_on_generic_request(self):
        self.assign()
        self.api.force_authenticate(self.manager)
        response = self.api.patch(f'/api/requests/{self.record.pk}/', {
            'assignment_accepted_at': '2000-01-01T00:00:00Z',
            'assignment_accepted_by': self.tech.pk,
            'assignment_accepted_revision': self.record.assignment_revision,
        }, format='json')
        self.assertIn(response.status_code, (200, 400), response.json())
        self.record.refresh_from_db()
        self.assertIsNone(self.record.assignment_accepted_at)
        self.assertIsNone(self.record.assignment_accepted_by_id)
        self.assertIsNone(self.record.assignment_accepted_revision)
        if response.status_code == 200:
            self.assertFalse(response.json()['assignment']['accepted'])
