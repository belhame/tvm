from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.catalogue_service import import_catalogue
from core.models import AuditLog, Client, Contract, Equipment, Intervention, OperationEvent, ServiceRequest, Warranty
from core.simple_intake import SimpleIntakeConflict, create_intake, lookup_intake
from core.request_assignment import assign_request, confirm_assignment
from core.request_tracking import write_followup

User = get_user_model()
BASE = '/api/logistics/sav-intake/'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SimpleIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('simple-manager', role='manager')
        cls.tech = User.objects.create_user('simple-tech', role='technician')
        cls.courier = User.objects.create_user('simple-courier', role='courier', first_name='Livreur TVM')
        cls.second_courier = User.objects.create_user('simple-courier-other', role='courier')
        cls.company = Client.objects.create(name='Centre SAV simple fictif', notes='CLIENT_PRIVATE_NOTES')
        cls.other_company = Client.objects.create(name='Centre privé autre société')
        cls.customer = User.objects.create_user('simple-client', role='client', client=cls.company)
        cls.external = User.objects.create_user('simple-external', role='courier', courier_kind='client', client=cls.company)
        cls.foreign_courier = User.objects.create_user('simple-external-other', role='courier', courier_kind='client', client=cls.other_company)
        cls.inactive = User.objects.create_user('simple-inactive', role='courier', is_active=False)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='SIMPLE-KNOWN-001', brand='Marque réelle', model='Modèle réel', power_kva=10)
        cls.foreign = Equipment.objects.create(client=cls.other_company, serial_number='FOREIGN-PRIVATE-001', brand='SECRET_BRAND', model='SECRET_MODEL')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.tech)

    def payload(self, **values):
        return {'request_key': str(uuid4()), 'client': self.company.pk, 'serial_number': 'SIMPLE-UNKNOWN-001',
                'arrival_courier': self.courier.pk, **values}

    def create(self, **values):
        return self.api.post(BASE + 'create/', self.payload(**values), format='json')

    def lookup(self, serial=None, **values):
        return self.api.post(BASE + 'lookup/', {'client': self.company.pk, 'serial_number': serial or self.unit.serial_number, **values}, format='json')

    def test_options_are_minimal_and_include_eligible_courier_metadata(self):
        response = self.api.get(BASE + 'options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['courier_required'])
        self.assertEqual(set(response.data['clients'][0]), {'id', 'name'})
        for courier in response.data['couriers']:
            self.assertEqual(set(courier), {'id', 'name', 'courier_kind', 'client'})
        self.assertNotIn(self.inactive.pk, [row['id'] for row in response.data['couriers']])
        self.assertNotIn('CLIENT_PRIVATE_NOTES', str(response.data))

    def test_technician_creates_unknown_equipment_without_a_model_or_assignment(self):
        before = timezone.now()
        response = self.create(client_reference='000CLIENT-LAB', description='Panne signalée')
        self.assertEqual(response.status_code, 201, response.data)
        record = ServiceRequest.objects.get(pk=response.data['request']['id'])
        unit = record.equipment
        self.assertEqual((unit.model, unit.brand), ('À identifier', ''))
        self.assertEqual((record.status, record.assigned_technician_id), ('new', None))
        self.assertGreaterEqual(record.arrived_at, before)
        self.assertEqual(record.requested_by_id, self.tech.pk)
        self.assertEqual(record.arrival_courier_id, self.courier.pk)
        self.assertEqual(record.courier_name, 'Livreur TVM')
        self.assertEqual(record.client_reference, '000CLIENT-LAB')
        self.assertEqual(record.warranty_status, 'quotation')
        self.assertTrue(response.data['coverage']['provisional'])
        self.assertEqual(response.data['coverage']['label'], 'Garantie à vérifier')
        self.assertEqual(record.intake_data['summary']['coverage'], response.data['coverage'])
        self.assertEqual(record.intake_data['summary']['return_history'], response.data['return_history'])
        self.assertEqual(Warranty.objects.count(), 0)
        self.assertEqual(record.interventions.count(), 0)

    def test_courier_creator_is_automatic_and_never_spoofed(self):
        self.api.force_authenticate(self.courier)
        options = self.api.get(BASE + 'options/').data
        self.assertFalse(options['courier_required'])
        self.assertEqual(options['actor_courier']['id'], self.courier.pk)
        self.assertEqual(options['couriers'], [])
        payload = self.payload()
        payload.pop('arrival_courier')
        response = self.api.post(BASE + 'create/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        record = ServiceRequest.objects.get(pk=response.data['request']['id'])
        self.assertEqual((record.requested_by_id, record.arrival_courier_id), (self.courier.pk, self.courier.pk))
        self.assertNotIn('assignment', response.data['request'])
        self.assertNotIn('description', response.data['request'])
        spoof = self.create(serial_number='SIMPLE-SPOOFED', arrival_courier=self.second_courier.pk)
        self.assertEqual(spoof.status_code, 400)

    def test_staff_requires_active_internal_or_same_client_external_courier(self):
        payload = self.payload()
        payload.pop('arrival_courier')
        self.assertEqual(self.api.post(BASE + 'create/', payload, format='json').status_code, 400)
        for courier in [self.foreign_courier, self.inactive, self.tech]:
            self.assertEqual(self.create(arrival_courier=courier.pk).status_code, 400)
        allowed = self.create(arrival_courier=self.external.pk)
        self.assertEqual(allowed.status_code, 201, allowed.data)
        self.assertEqual(allowed.data['request']['arrival_courier']['id'], self.external.pk)

    def test_client_external_courier_and_anonymous_cannot_create_or_lookup(self):
        for actor in [self.customer, self.external, None]:
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.get(BASE + 'options/').status_code, 403)
            self.assertEqual(self.lookup().status_code, 403)
            self.assertEqual(self.create().status_code, 403)

    def test_lookup_is_readonly_and_never_serializes_full_sav_for_courier(self):
        old = ServiceRequest.objects.create(equipment=self.unit, subject='PRIVATE_SOURCE_SUBJECT', description='PRIVATE_SOURCE_DESCRIPTION')
        Intervention.objects.create(service_request=old, internal_notes='PRIVATE_SOURCE_INTERVENTION', diagnosis='PRIVATE_DIAGNOSIS')
        counts = (Equipment.objects.count(), ServiceRequest.objects.count(), OperationEvent.objects.count(), AuditLog.objects.count())
        self.api.force_authenticate(self.courier)
        with patch('core.serial_lookup._recorded', side_effect=AssertionError('Full SAV history must not be loaded')):
            response = self.lookup()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(counts, (Equipment.objects.count(), ServiceRequest.objects.count(), OperationEvent.objects.count(), AuditLog.objects.count()))
        for secret in ['PRIVATE_SOURCE_SUBJECT', 'PRIVATE_SOURCE_DESCRIPTION', 'PRIVATE_SOURCE_INTERVENTION', 'PRIVATE_DIAGNOSIS', 'CLIENT_PRIVATE_NOTES']:
            self.assertNotIn(secret, str(response.data))

    def test_foreign_serial_never_discloses_equipment_or_client_metadata(self):
        for endpoint, payload in [('lookup/', {'client': self.company.pk, 'serial_number': self.foreign.serial_number}),
                                  ('create/', self.payload(serial_number=self.foreign.serial_number))]:
            response = self.api.post(BASE + endpoint, payload, format='json')
            self.assertEqual(response.status_code, 409, response.data)
            for secret in ['SECRET_BRAND', 'SECRET_MODEL', self.other_company.name, self.foreign.serial_number]:
                self.assertNotIn(secret, str(response.data))

    def test_open_request_conflict_does_not_reset_arrival_or_duplicate(self):
        original_arrival = timezone.now() - timedelta(days=5)
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Dossier ouvert privé', arrived_at=original_arrival, status='testing')
        before = OperationEvent.objects.count()
        response = self.create(serial_number=self.unit.serial_number)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['open_request']['id'], record.pk)
        self.assertIs(type(response.data['open_request']['id']), int)
        self.assertNotIn('Dossier ouvert privé', str(response.data))
        record.refresh_from_db()
        self.assertEqual((record.arrived_at, record.status), (original_arrival, 'testing'))
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.count(), before)

    def test_exact_replay_preserves_first_arrival_payload_and_all_counts(self):
        payload = self.payload()
        first = self.api.post(BASE + 'create/', payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        counts = (Equipment.objects.count(), ServiceRequest.objects.count(), OperationEvent.objects.count())
        second = self.api.post(BASE + 'create/', payload, format='json')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data, {**first.data, 'created': False})
        self.assertEqual(counts, (Equipment.objects.count(), ServiceRequest.objects.count(), OperationEvent.objects.count()))
        altered = self.api.post(BASE + 'create/', {**payload, 'description': 'Autre réception'}, format='json')
        self.assertEqual(altered.status_code, 409)

    def test_same_serial_with_different_key_is_open_conflict_and_other_actor_cannot_replay(self):
        payload = self.payload()
        first = self.api.post(BASE + 'create/', payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.create().status_code, 409)
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.post(BASE + 'create/', payload, format='json').status_code, 409)

    def test_global_active_expired_and_future_guarantees_have_distinct_orientations(self):
        today = timezone.localdate()
        for scope, offset_start, offset_end, status, warranty_status, provisional in [
            ('electronics_and_batteries', -30, 30, 'active', 'warranty', False),
            ('unspecified', -30, 30, 'active', 'warranty', True),
            ('electronics_and_batteries', -60, -1, 'expired', 'quotation', False),
            ('electronics_and_batteries', 1, 60, 'not_started', 'quotation', True),
        ]:
            with self.subTest(scope=scope, status=status):
                Warranty.objects.all().delete()
                row = Warranty.objects.create(equipment=self.unit, scope=scope, starts_on=today + timedelta(days=offset_start), ends_on=today + timedelta(days=offset_end))
                response = self.lookup()
                self.assertEqual(response.status_code, 200, response.data)
                coverage = response.data['coverage']
                self.assertEqual((coverage['status'], coverage['warranty_status'], coverage['provisional']), (status, warranty_status, provisional))
                self.assertEqual(coverage['starts_on'], row.starts_on.isoformat())
                self.assertEqual(coverage['ends_on'], row.ends_on.isoformat())

    def test_battery_only_and_inherited_global_end_do_not_fake_ups_coverage(self):
        today = timezone.localdate()
        self.unit.warranty_until = today + timedelta(days=50)
        self.unit.save(update_fields=['warranty_until'])
        Warranty.objects.create(equipment=self.unit, scope='batteries', starts_on=today - timedelta(days=10), ends_on=today + timedelta(days=50))
        response = self.lookup()
        self.assertEqual(response.data['coverage']['status'], 'unknown')
        self.assertEqual(response.data['coverage']['warranty_status'], 'quotation')
        self.assertTrue(response.data['coverage']['provisional'])

    def test_equipment_global_end_without_component_records_is_honored(self):
        self.unit.warranty_until = timezone.localdate() + timedelta(days=50)
        self.unit.save(update_fields=['warranty_until'])
        response = self.lookup()
        self.assertEqual(response.data['coverage']['warranty_status'], 'warranty')
        self.assertTrue(response.data['coverage']['provisional'])

    def test_contract_does_not_become_a_warranty_or_a_generated_financial_document(self):
        today = timezone.localdate()
        Contract.objects.create(number='SIMPLE-CONTRACT-LAB', client=self.company, equipment=self.unit,
            starts_on=today - timedelta(days=1), ends_on=today + timedelta(days=30), status='active', coverage='PRIVATE_CONTRACT_TERMS')
        response = self.create(serial_number=self.unit.serial_number)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['coverage']['warranty_status'], 'quotation')
        self.assertTrue(response.data['coverage']['provisional'])
        self.assertNotIn('PRIVATE_CONTRACT_TERMS', str(response.data))
        record = ServiceRequest.objects.get(pk=response.data['request']['id'])
        self.assertFalse(hasattr(record, 'diagnostic_quote'))
        self.assertEqual(Warranty.objects.count(), 0)

    def test_prior_exact_serial_and_completed_exchange_links_are_return_history(self):
        old = ServiceRequest.objects.create(equipment=self.unit, reference='OLD-SIMPLE-LAB', client_reference='000OLD-REF', subject='PRIVATE_OLD_SUBJECT', status='closed')
        lookup = self.lookup().data
        self.assertTrue(lookup['return_history']['is_return'])
        self.assertEqual(lookup['return_history']['matches'][0]['relation'], 'same_equipment')
        response = self.create(serial_number=self.unit.serial_number)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['request']['return_flag'])
        self.assertNotIn(response.data['request']['id'], [row['id'] for row in response.data['return_history']['matches']])
        replacement = Equipment.objects.create(client=self.company, serial_number='SIMPLE-REPLACEMENT-LAB', model='Remplacement réel')
        historical_visit = Intervention.objects.create(service_request=old, status='completed', work_done='Échange antérieur réel')
        # Represent a pre-workflow completed exchange without bypassing the
        # production guard that forbids creating new exchanges on closed SAVs.
        Intervention.objects.filter(pk=historical_visit.pk).update(kind='exchange', replacement_equipment=replacement)
        linked = self.lookup(replacement.serial_number).data
        match = linked['return_history']['matches'][0]
        self.assertEqual((match['relation'], match['serial_number'], match['call_number']), ('replacement', self.unit.serial_number, old.reference))
        self.assertNotIn('PRIVATE_OLD_SUBJECT', str(linked))

    def test_unique_catalogue_auto_identifies_without_overwriting_existing_equipment(self):
        fixture = Path(__file__).parent / 'fixtures/request_intake_synthetic.xls'
        import_catalogue(fixture.read_bytes(), fixture.name, actor=self.manager)
        response = self.create(serial_number='GAB2A49002')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['equipment']['model'], 'LAB850F')
        self.assertEqual(response.data['equipment']['identification'], 'catalogue')
        self.assertIn(response.data['coverage']['status'], ('active', 'expired', 'not_started', 'unknown'))
        if response.data['coverage']['status'] == 'active':
            self.assertTrue(response.data['coverage']['provisional'])
        self.assertEqual(Warranty.objects.count(), 0)
        original = (self.unit.model, self.unit.brand, self.unit.warranty_until, self.unit.status)
        self.create(serial_number=self.unit.serial_number)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.model, self.unit.brand, self.unit.warranty_until, self.unit.status), original)

    def test_readonly_arrival_courier_is_hidden_from_portal_and_cannot_be_forged(self):
        response = self.create()
        record = ServiceRequest.objects.get(pk=response.data['request']['id'])
        self.api.force_authenticate(self.manager)
        updated = self.api.patch(f'/api/requests/{record.pk}/', {'arrival_courier': self.second_courier.pk}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        record.refresh_from_db()
        self.assertEqual(record.arrival_courier_id, self.courier.pk)
        self.api.force_authenticate(self.customer)
        self.assertNotIn('arrival_courier', self.api.get(f'/api/requests/{record.pk}/').data)

    def test_historical_arrival_courier_identity_cannot_be_converted(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        self.api.force_authenticate(self.manager)
        # Only admins manage users; conversion must fail on the history guard,
        # not merely because a manager lacks account permissions.
        self.manager.role = 'admin'
        self.manager.save(update_fields=['role'])
        response = self.api.patch(f'/api/users/{self.courier.pk}/', {'courier_kind': 'client', 'client': self.company.pk}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.courier.refresh_from_db()
        self.assertEqual(self.courier.courier_kind, 'internal')

    def test_strict_fields_and_server_owned_arrival_status_assignment_are_enforced(self):
        for extra in [{'status': 'maintenance'}, {'assigned_technician': self.tech.pk}, {'arrived_at': '2026-01-01T00:00:00Z'},
                      {'return_flag': True}, {'requested_by': self.courier.pk}, {'model': 'FORGED'}, {'warranty_status': 'warranty'}]:
            self.assertEqual(self.create(**extra).status_code, 400)
        for changes in [{'client': True}, {'arrival_courier': '1'}, {'serial_number': '\x00'}, {'description': 12}]:
            self.assertEqual(self.create(**changes).status_code, 400)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.tech)
        self.assertEqual(client.post(BASE + 'create/', self.payload(), format='json').status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Concurrence PostgreSQL réelle')
class ConcurrentSimpleIntakeTests(TransactionTestCase):
    def setUp(self):
        self.company = Client.objects.create(name='Centre réception concurrente fictif')
        self.manager = User.objects.create_user('simple-concurrent-manager', role='manager')
        self.tech = User.objects.create_user('simple-concurrent-tech', role='technician')
        self.courier = User.objects.create_user('simple-concurrent-courier', role='courier')

    def data(self, **values):
        return {'request_key': uuid4(), 'client': self.company.pk, 'serial_number': 'SIMPLE-CONCURRENT-LAB',
                'arrival_courier': self.courier.pk, 'client_reference': '', 'description': '', **values}

    def parallel(self, functions):
        ready = Barrier(len(functions))
        def run(function):
            try:
                ready.wait(timeout=10)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions, timeout=30))

    def test_same_key_concurrent_replay_creates_exactly_one_request_and_arrival(self):
        data = self.data()
        outcomes = self.parallel([lambda: create_intake(self.tech, data), lambda: create_intake(self.tech, data)])
        self.assertCountEqual([row['created'] for row in outcomes], [True, False])
        self.assertEqual(outcomes[0]['request'], outcomes[1]['request'])
        self.assertEqual(Equipment.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_two_keys_same_serial_have_one_creation_and_one_open_conflict(self):
        def receive(data):
            try:
                return create_intake(self.tech, data)['created']
            except SimpleIntakeConflict:
                return 'conflict'
        first, second = self.data(), self.data()
        outcomes = self.parallel([lambda: receive(first), lambda: receive(second)])
        self.assertCountEqual(outcomes, [True, 'conflict'])
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_open_conflict_racing_followup_does_not_invert_user_and_request_locks(self):
        equipment = Equipment.objects.create(client=self.company, serial_number='SIMPLE-CONCURRENT-LAB', model='Fictif')
        record = ServiceRequest.objects.create(equipment=equipment, subject='Dossier ouvert')
        record = assign_request(record.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=0)
        record = confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True)
        # The conflicting intake must be able to report its result while the
        # other transaction holds the existing request and awaits its actor.
        def reception():
            try:
                return create_intake(self.tech, self.data())
            except SimpleIntakeConflict:
                return 'conflict'
        payload = {'status': 'maintenance', 'expected_status': record.status, 'assignment_revision': record.assignment_revision, 'observation': 'Contrôle simultané'}
        outcomes = self.parallel([reception, lambda: write_followup(record.pk, payload, actor=self.tech).service_request.status])
        self.assertEqual(outcomes[0], 'conflict')
        self.assertEqual(outcomes[1], 'maintenance')
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_open_conflict_racing_real_repair_qualification_has_no_equipment_user_cycle(self):
        from core import simple_intake, disposition_workflow
        equipment = Equipment.objects.create(client=self.company, serial_number='SIMPLE-CONCURRENT-LAB', model='Fictif')
        record = ServiceRequest.objects.create(equipment=equipment, subject='Tests atelier', status='testing')
        record = assign_request(record.pk, actor=self.manager, technician_id=self.tech.pk, expected_revision=0)
        confirm_assignment(record.pk, actor=self.tech, expected_revision=record.assignment_revision, accept=True)
        equipment_locked = Event()
        user_locked = Event()
        original_equipment = simple_intake._equipment
        original_allowed = disposition_workflow._edit_allowed
        def equipment_gate(*args, **kwargs):
            result = original_equipment(*args, **kwargs)
            if kwargs.get('lock'):
                equipment_locked.set()
                if not user_locked.wait(10):
                    raise RuntimeError('Repair qualification did not reach its actor lock')
            return result
        def user_gate(*args, **kwargs):
            result = original_allowed(*args, **kwargs)
            user_locked.set()
            if not equipment_locked.wait(10):
                raise RuntimeError('Reception did not reach its equipment lock')
            return result
        def reception():
            try:
                create_intake(self.tech, self.data())
                return 'unexpected-create'
            except SimpleIntakeConflict:
                return 'conflict'
        def repaired():
            return disposition_workflow.mark_repaired(record.pk, {'tests_passed': True, 'diagnosis': 'Tests synthétiques réussis', 'tested_on': timezone.localdate()}, actor=self.tech).status
        with patch('core.simple_intake._equipment', side_effect=equipment_gate), patch('core.disposition_workflow._edit_allowed', side_effect=user_gate):
            results = self.parallel([reception, repaired])
        self.assertEqual(results, ['conflict', 'ready_for_delivery'])
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_simple_intake_and_existing_logistics_receive_share_the_serial_lock(self):
        from core.logistics_service import receive
        from core.logistics_models import CourierReceipt
        simple_data = self.data()
        legacy_data = {'request_key': uuid4(), 'client': self.company.pk, 'serial_number': simple_data['serial_number'],
                       'manual_model': 'Modèle réception historique', 'manual_brand': 'Marque réelle',
                       'manual_reason': 'Identification observée pour test synthétique', 'source': 'manual'}
        def simple():
            try:
                return create_intake(self.tech, simple_data)['created']
            except SimpleIntakeConflict:
                return 'conflict'
        results = self.parallel([simple, lambda: receive(self.courier, legacy_data).pk])
        self.assertIn(results[0], (True, 'conflict'))
        self.assertIsInstance(results[1], int)
        self.assertEqual(Equipment.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(CourierReceipt.objects.count(), 1)
