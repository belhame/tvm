"""Independent company-owned courier review, using fictional records only."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client as BrowserClient, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Equipment, OutboundJob, ServiceRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentCourierTypesReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Livreur Dédié Fictif', email='centre-fictif@example.invalid', notes='PRIVATE_COURIER_TYPE_CLIENT_NOTE')
        cls.other_company = Client.objects.create(name='Autre Centre Livreur Fictif', email='autre-centre@example.invalid', notes='PRIVATE_OTHER_COMPANY_NOTE')
        cls.admin = User.objects.create_user('courier-type-review-admin', role='admin')
        cls.internal = User.objects.create_user('courier-type-review-internal', role='courier')
        cls.external = User.objects.create_user('courier-type-review-external', role='courier', courier_kind='client', client=cls.company)
        cls.other_external = User.objects.create_user('courier-type-review-other-external', role='courier', courier_kind='client', client=cls.other_company)
        cls.customer = User.objects.create_user('courier-type-review-client', role='client', client=cls.company)
        cls.other_customer = User.objects.create_user('courier-type-review-other-client', role='client', client=cls.other_company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='COURIER-TYPE-FICTION-001', model='Onduleur dédié fictif')
        cls.other_unit = Equipment.objects.create(client=cls.other_company, serial_number='COURIER-TYPE-FICTION-002', model='Autre onduleur fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def set_referents(self, **fields):
        response = self.api.patch(f'/api/clients/{self.company.pk}/', fields, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.company.refresh_from_db()

    def mark_ready(self, unit=None):
        record = ServiceRequest.objects.create(equipment=unit or self.unit, subject='Tests fictifs de routage', status='testing')
        body = {'diagnosis': 'Tests fictifs réussis', 'tests_passed': True, 'tested_on': timezone.localdate().isoformat()}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(f'/api/requests/{record.pk}/disposition/repair/', body, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        record.refresh_from_db()
        return record, body

    def legacy_job(self, *, unit=None, courier=None):
        record = ServiceRequest.objects.create(equipment=unit or self.unit, subject='Ancien prêt fictif')
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        response = self.api.post('/api/logistics/outbound/', {'service_request': record.pk, 'courier': (courier or self.external).pk}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        return OutboundJob.objects.get(pk=response.json()['id'])

    def end_customer_pickup(self, **changes):
        body = {'request_key': str(uuid4()), 'equipment': self.unit.pk,
                'pickup_scope': 'end_customer', 'end_customer_name': 'Client final fictif du centre',
                'fault_description': 'Panne déclarée fictive', 'pickup_address': 'Adresse finale fictive',
                'contact_name': 'Contact final fictif', 'contact_phone': '+000 123 456'}
        body.update(changes)
        return body

    def test_external_courier_real_session_cannot_reach_workshop_or_legacy_apis(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.external)
        token = browser.get('/api/session/').json()['csrfToken']
        for method, path, body in [
            ('get', '/api/clients/', None), ('get', '/api/equipment/', None),
            ('get', '/api/requests/', None), ('get', '/api/search/?q=FICTION', None),
            ('get', '/api/users/', None), ('get', '/admin/', None),
            ('get', '/api/logistics/clients/', None),
            ('post', '/api/logistics/lookup/', {'serial_number': self.unit.serial_number}),
            ('post', '/api/logistics/lookup/', {'serial_number': self.other_unit.serial_number}),
            ('post', '/api/logistics/receive/', {'request_key': str(uuid4()), 'serial_number': self.unit.serial_number, 'client': self.company.pk}),
            ('post', '/api/logistics/recognize-serial/', {}),
        ]:
            with self.subTest(method=method, path=path):
                if method == 'get':
                    response = browser.get(path)
                elif path.endswith('/recognize-serial/'):
                    response = browser.post(path, body, HTTP_X_CSRFTOKEN=token)
                else:
                    response = browser.post(path, body, content_type='application/json', HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertEqual(browser.get('/api/logistics/pickups/').json(), [])
        self.assertFalse(ServiceRequest.objects.exists())

    def test_external_bootstrap_never_contains_another_company_or_staff_directory(self):
        self.api.force_authenticate(self.external)
        response = self.api.get('/api/logistics/bootstrap/')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['couriers'], [])
        self.assertTrue(all(row.get('id') == self.company.pk for row in response.json()['clients']))
        for private in (self.other_company.name, self.other_company.email, self.company.email, self.company.notes, self.other_company.notes, self.internal.username):
            self.assertNotIn(private, str(response.json()))

    def test_driver_company_and_assignment_both_limit_delivery_access_and_handoff(self):
        own = self.legacy_job()
        foreign = self.legacy_job(unit=self.other_unit, courier=self.other_external)
        self.api.force_authenticate(self.external)
        listing = self.api.get('/api/logistics/outbound/')
        self.assertEqual(listing.status_code, 200, listing.json())
        self.assertEqual([row['id'] for row in listing.json()], [own.pk])
        self.assertEqual(self.api.get(f'/api/logistics/outbound/{foreign.pk}/').status_code, 404)
        response = self.api.post(f'/api/logistics/outbound/{foreign.pk}/handoff/', {'recipient_name': 'Contact fictif'}, format='json')
        self.assertIn(response.status_code, (403, 404), response.json())
        # Fail closed even for an inconsistent historical assignment to an
        # external driver who belongs to a different company.
        OutboundJob.objects.filter(pk=foreign.pk).update(assigned_courier=self.external)
        self.assertEqual(self.api.get(f'/api/logistics/outbound/{foreign.pk}/').status_code, 404)
        listing = self.api.get('/api/logistics/outbound/')
        self.assertEqual([row['id'] for row in listing.json()], [own.pk])

    def test_external_daily_notification_does_not_reveal_a_foreign_historical_assignment(self):
        from core.notification_models import InAppNotification
        from core.notification_service import logistics_workload

        own = self.legacy_job()
        foreign = self.legacy_job(unit=self.other_unit, courier=self.other_external)
        OutboundJob.objects.filter(pk=foreign.pk).update(assigned_courier=self.external)
        InAppNotification.objects.create(recipient=self.external, kind='daily_logistics',
            dedup_key='review-external-owner-day', local_date=timezone.localdate(),
            payload={'pickup_ids': [], 'delivery_ids': [own.pk, foreign.pk]})
        workload = logistics_workload(self.external)
        self.assertEqual([row['id'] for row in workload['deliveries']], [own.pk])
        self.assertEqual(workload['pickups'], [])
        self.api.force_authenticate(self.external)
        response = self.api.get('/api/logistics/notifications/')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertNotIn(self.other_company.name, str(response.json()))
        self.assertNotIn(self.other_unit.serial_number, str(response.json()))

    def test_external_courier_cannot_be_assigned_to_another_company(self):
        job = self.legacy_job(unit=self.other_unit, courier=self.other_external)
        response = self.api.post(f'/api/logistics/outbound/{job.pk}/assign/', {'courier': self.external.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.other_external.pk)

    def test_client_referents_reject_foreign_external_internal_mismatch_and_inactive_driver(self):
        self.other_external.is_active = False
        self.other_external.save(update_fields=['is_active'])
        for changes in ({'default_courier': self.other_external.pk}, {'default_courier': self.internal.pk}, {'internal_courier': self.external.pk}):
            with self.subTest(changes=changes):
                response = self.api.patch(f'/api/clients/{self.company.pk}/', changes, format='json')
                self.assertEqual(response.status_code, 400, response.json())
        self.external.is_active = False
        self.external.save(update_fields=['is_active'])
        response = self.api.patch(f'/api/clients/{self.company.pk}/', {'default_courier': self.external.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.json())

    def test_portal_cannot_change_its_routing_or_courier_owner(self):
        self.api.force_authenticate(self.customer)
        for path, changes in ((f'/api/clients/{self.company.pk}/', {'default_courier': self.other_external.pk}),
                              (f'/api/users/{self.external.pk}/', {'client': self.other_company.pk, 'courier_kind': 'internal'})):
            response = self.api.patch(path, changes, format='json')
            self.assertEqual(response.status_code, 403, response.json())
        self.external.refresh_from_db()
        self.assertEqual(self.external.client_id, self.company.pk)

    def test_ready_prefers_own_external_default_and_falls_back_to_internal_when_disabled(self):
        self.set_referents(default_courier=self.external.pk, internal_courier=self.internal.pk)
        first, _ = self.mark_ready()
        self.assertEqual(OutboundJob.objects.get(service_request=first).assigned_courier_id, self.external.pk)
        self.external.is_active = False
        self.external.save(update_fields=['is_active'])
        unit = Equipment.objects.create(client=self.company, serial_number='COURIER-TYPE-FALLBACK-003', model='Onduleur de repli fictif')
        second, _ = self.mark_ready(unit)
        self.assertEqual(OutboundJob.objects.get(service_request=second).assigned_courier_id, self.internal.pk)
        self.assertEqual(ServiceRequest.objects.get(pk=second.pk).status, 'ready_for_delivery')

    def test_ready_replay_does_not_replace_manual_courier_or_handoff_proof(self):
        record, body = self.mark_ready()
        self.assertFalse(OutboundJob.objects.filter(service_request=record).exists())
        response = self.api.post('/api/logistics/outbound/', {'service_request': record.pk, 'courier': self.internal.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job = OutboundJob.objects.get(service_request=record)
        self.set_referents(default_courier=self.external.pk, internal_courier=self.internal.pk)
        response = self.api.post(f'/api/requests/{record.pk}/disposition/repair/', body, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        response = self.api.post('/api/logistics/reconcile/', {'client': self.company.pk, 'reassign_automatic': True}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.internal.pk)
        self.api.force_authenticate(self.internal)
        response = self.api.post(f'/api/logistics/outbound/{job.pk}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job.refresh_from_db()
        proof = job.handed_over_at
        self.api.force_authenticate(self.admin)
        response = self.api.post(f'/api/requests/{record.pk}/disposition/repair/', body, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        response = self.api.post('/api/logistics/reconcile/', {'client': self.company.pk, 'reassign_automatic': True}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job.refresh_from_db()
        self.assertEqual(job.assigned_courier_id, self.internal.pk)
        self.assertEqual(job.handed_over_at, proof)
        self.assertEqual(job.recipient_name, 'Destinataire fictif')
        record.refresh_from_db()
        self.assertEqual(record.status, 'ready_for_delivery')
        self.assertIsNone(record.closed_at)

    def test_completed_mission_prevents_external_driver_reparenting_or_type_conversion(self):
        job = self.legacy_job()
        self.api.force_authenticate(self.external)
        response = self.api.post(f'/api/logistics/outbound/{job.pk}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job.refresh_from_db()
        proof = job.handed_over_at
        self.api.force_authenticate(self.admin)
        for changes in ({'client': self.other_company.pk}, {'courier_kind': 'internal', 'client': None}, {'role': 'technician', 'courier_kind': 'internal', 'client': None}):
            with self.subTest(changes=changes):
                response = self.api.patch(f'/api/users/{self.external.pk}/', changes, format='json')
                self.assertEqual(response.status_code, 400, response.json())
        self.external.refresh_from_db()
        self.assertEqual(self.external.client_id, self.company.pk)
        self.assertEqual(self.external.courier_kind, 'client')
        job.refresh_from_db()
        self.assertEqual(job.client_id, self.company.pk)
        self.assertEqual(job.handed_over_at, proof)

    def test_referent_cannot_change_identity_but_can_be_disabled_without_blocking_client_notes(self):
        self.set_referents(default_courier=self.external.pk, internal_courier=self.internal.pk)
        response = self.api.patch(f'/api/users/{self.external.pk}/', {'client': self.other_company.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        response = self.api.patch(f'/api/users/{self.external.pk}/', {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.set_referents(notes='Note fictive après désactivation du référent')
        self.assertEqual(self.company.default_courier_id, self.external.pk)
        self.assertEqual(self.company.notes, 'Note fictive après désactivation du référent')

    def test_portal_end_customer_pickup_keeps_parent_company_without_new_client_or_workshop_arrival(self):
        self.api.force_authenticate(self.customer)
        before = Client.objects.count(), Equipment.objects.count(), ServiceRequest.objects.count()
        response = self.api.post('/api/logistics/pickups/', self.end_customer_pickup(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['client']['id'], self.company.pk)
        self.assertEqual(response.json()['pickup_scope'], 'end_customer')
        self.assertEqual(response.json()['end_customer_name'], 'Client final fictif du centre')
        self.assertEqual((Client.objects.count(), Equipment.objects.count(), ServiceRequest.objects.count()), before)
        self.assertIsNone(response.json()['service_request'])
        self.assertIsNone(response.json()['received_at'])
        foreign = self.api.post('/api/logistics/pickups/', self.end_customer_pickup(client=self.other_company.pk), format='json')
        self.assertIn(foreign.status_code, (400, 403), foreign.json())
        self.assertEqual((Client.objects.count(), Equipment.objects.count(), ServiceRequest.objects.count()), before)

    def test_manager_can_create_end_customer_pickup_but_only_internal_driver_can_be_assigned(self):
        response = self.api.post('/api/logistics/pickups/', self.end_customer_pickup(client=self.company.pk), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        identifier = response.json()['id']
        rejected = self.api.post(f'/api/logistics/pickups/{identifier}/assign/', {'courier': self.external.pk}, format='json')
        self.assertEqual(rejected.status_code, 400, rejected.json())
        assigned = self.api.post(f'/api/logistics/pickups/{identifier}/assign/', {'courier': self.internal.pk}, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.json())
        self.assertEqual(assigned.json()['assigned_courier'], self.internal.pk)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_end_customer_pickup_requires_identity_address_contact_and_rejects_server_fields(self):
        self.api.force_authenticate(self.customer)
        for changes in ({'end_customer_name': ''}, {'pickup_address': ''}, {'contact_name': ''},
                        {'status': 'received'}, {'assigned_courier': self.external.pk},
                        {'received_at': '2000-01-01T00:00:00Z'}, {'service_request': 1}):
            with self.subTest(changes=changes):
                response = self.api.post('/api/logistics/pickups/', self.end_customer_pickup(**changes), format='json')
                self.assertEqual(response.status_code, 400, response.json())
        from core.models import PickupRequest
        self.assertFalse(PickupRequest.objects.exists())
        self.assertFalse(ServiceRequest.objects.exists())

    def test_reconcile_is_post_only_strict_and_reserved_to_managers(self):
        self.assertEqual(self.api.get('/api/logistics/reconcile/').status_code, 405)
        for body in ({'client': True}, {'client': str(self.company.pk)}, {'reassign_automatic': 'true'}, {'status': 'closed'}):
            response = self.api.post('/api/logistics/reconcile/', body, format='json')
            self.assertEqual(response.status_code, 400, response.json())
        for actor in (self.customer, self.external, self.internal):
            self.api.force_authenticate(actor)
            response = self.api.post('/api/logistics/reconcile/', {'client': self.company.pk}, format='json')
            self.assertEqual(response.status_code, 403, response.json())

    def test_database_requires_company_only_for_client_courier_and_disallows_privileged_flags(self):
        User = get_user_model()
        for changes in ({'client_id': None}, {'courier_kind': 'internal'}, {'is_staff': True}, {'is_superuser': True}, {'can_validate_billing': True}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.filter(pk=self.external.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.internal.pk).update(client=self.company)
