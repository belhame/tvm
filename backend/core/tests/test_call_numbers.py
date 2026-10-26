from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as datetime_timezone
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.intake_service import create_intake
from core.models import Client, Equipment, Intervention, RequestNumberSequence, ServiceRequest
from core.request_numbering import reference_query_value

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TIME_ZONE='Africa/Lagos')
class CallNumberTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Centre fictif Alpha')
        cls.other_company = Client.objects.create(name='Centre fictif Bêta')
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='CALL-LAB-ALPHA', model='Laboratoire fictif')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='CALL-LAB-BETA', model='Autre laboratoire fictif')
        cls.manager = User.objects.create_user('call-manager', role='manager')
        cls.customer = User.objects.create_user('call-alpha', role='client', client=cls.company)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def create_request(self, **values):
        return ServiceRequest.objects.create(equipment=self.equipment, subject='Appel fictif', **values)

    def test_new_numbers_are_padded_in_local_year_without_rewriting_old_numbers(self):
        historic = self.create_request(reference='SAV-HISTORIQUE-LAB')
        frozen = datetime(2046, 12, 31, 23, 30, tzinfo=datetime_timezone.utc)  # 2047 locally.
        with patch('django.utils.timezone.now', return_value=frozen):
            first = self.create_request()
            second = self.create_request()
        self.assertEqual((first.reference, second.reference), ('47-00001', '47-00002'))
        self.assertEqual(RequestNumberSequence.objects.get(year=2047).last_value, 2)
        historic.refresh_from_db()
        self.assertEqual(historic.reference, 'SAV-HISTORIQUE-LAB')
        self.assertFalse(RequestNumberSequence.objects.filter(year=2046).exists())

    def test_existing_real_number_reserves_its_sequence_and_other_formats_do_not(self):
        self.create_request(reference='47-00009')
        self.create_request(reference='47-99999-LEGACY')
        self.create_request(reference='SAV-2047-00099')
        with patch('django.utils.timezone.now', return_value=datetime(2047, 5, 1, tzinfo=datetime_timezone.utc)):
            created = self.create_request()
        self.assertEqual(created.reference, '47-00010')

    def test_year_change_starts_a_separate_counter(self):
        with patch('django.utils.timezone.now', return_value=datetime(2047, 12, 31, 10, tzinfo=datetime_timezone.utc)):
            previous = self.create_request()
        with patch('django.utils.timezone.now', return_value=datetime(2048, 1, 1, 10, tzinfo=datetime_timezone.utc)):
            current = self.create_request()
        self.assertEqual((previous.reference, current.reference), ('47-00001', '48-00001'))

    def test_failed_transaction_does_not_consume_a_number(self):
        frozen = datetime(2047, 5, 1, tzinfo=datetime_timezone.utc)
        with patch('django.utils.timezone.now', return_value=frozen):
            with self.assertRaises(RuntimeError), transaction.atomic():
                self.create_request()
                raise RuntimeError('Rollback test only')
            saved = self.create_request()
        self.assertEqual(saved.reference, '47-00001')

    def test_number_exhaustion_never_wraps_or_changes_historical_number(self):
        self.create_request(reference='47-99999')
        with patch('django.utils.timezone.now', return_value=datetime(2047, 5, 1, tzinfo=datetime_timezone.utc)):
            with self.assertRaises(ValidationError):
                self.create_request()
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertFalse(RequestNumberSequence.objects.filter(year=2047).exists())

    def test_shared_call_alias_and_external_reference_are_independent_from_visit_reference(self):
        request = self.create_request(reference='TVM-ANCIEN-LAB', client_reference='0007-LAB-A')
        visits = [Intervention.objects.create(service_request=request, reference=f'INT-LAB-{index}') for index in range(2)]
        for visit in visits:
            response = self.api.get(f'/api/interventions/{visit.pk}/')
            self.assertEqual(response.data['call_number'], 'TVM-ANCIEN-LAB')
            self.assertEqual(response.data['request_reference'], 'TVM-ANCIEN-LAB')
            self.assertEqual(response.data['client_reference'], '0007-LAB-A')
            self.assertEqual(response.data['reference'], visit.reference)
        response = self.api.patch(f'/api/requests/{request.pk}/', {'reference': 'FORGED', 'call_number': 'FORGED'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['call_number'], 'TVM-ANCIEN-LAB')
        response = self.api.patch(f'/api/interventions/{visits[0].pk}/', {'call_number': 'FORGED', 'client_reference': 'FORGED'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['client_reference'], '0007-LAB-A')

    def test_reference_zeroes_letters_and_duplicate_centres_are_preserved(self):
        first = self.create_request(client_reference='000Ab-07')
        second = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Autre centre', client_reference='000Ab-07')
        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.client_reference, '000Ab-07')

    def test_external_reference_correction_is_historized_without_changing_tvm_number(self):
        request = self.create_request(reference='47-00012', client_reference='000ABC-01')
        response = self.api.patch(f'/api/requests/{request.pk}/', {'client_reference': '000ABC-02'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['call_number'], '47-00012')
        event = request.operation_events.latest('id')
        self.assertIn('Numéro d’appel client : 000ABC-01 → 000ABC-02', event.summary)

    def test_client_fragment_search_and_explicit_filters_are_scoped_before_match(self):
        own = self.create_request(reference='47-00012', client_reference='000Ab-07')
        other = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Autre centre', client_reference='000Ab-07')
        hidden = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Secret autre centre', client_reference='SECRET-CENTRE-B')
        own_visit = Intervention.objects.create(service_request=own)
        Intervention.objects.create(service_request=other)
        Intervention.objects.create(service_request=hidden)
        self.api.force_authenticate(self.customer)
        for suffix in ['?q=ab-0', '?client_reference=AB-07', '?call_number=00012&client_reference=000ab']:
            self.assertEqual([row['id'] for row in self.api.get('/api/requests/' + suffix).data], [own.pk])
            self.assertEqual([row['id'] for row in self.api.get('/api/interventions/' + suffix).data], [own_visit.pk])
        results = self.api.get('/api/search/?q=ab-0').data
        self.assertEqual([row['id'] for row in results['requests']], [own.pk])
        self.assertEqual([row['id'] for row in results['interventions']], [own_visit.pk])
        self.assertEqual(results['interventions'][0]['call_number'], own.reference)
        self.assertEqual(results['interventions'][0]['client_reference'], '000Ab-07')
        self.assertEqual(self.api.get('/api/search/?q=SECRET-CENTRE-B').data['requests'], [])
        self.assertEqual(self.api.get('/api/search/?q=SECRET-CENTRE-B').data['interventions'], [])
        self.assertEqual(self.api.get(f'/api/requests/{other.pk}/').status_code, 404)

    def test_global_search_by_tvm_number_returns_all_its_visits(self):
        request = self.create_request(reference='47-00033', client_reference='CENTRE-LAB-33')
        first = Intervention.objects.create(service_request=request)
        second = Intervention.objects.create(service_request=request)
        result = self.api.get('/api/search/?q=47-00033').data
        self.assertEqual([row['id'] for row in result['requests']], [request.pk])
        self.assertEqual({row['id'] for row in result['interventions']}, {first.pk, second.pk})

    def test_one_character_external_reference_is_searchable_exactly(self):
        own = self.create_request(client_reference='0')
        longer = self.create_request(client_reference='0007')
        other = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Centre B zéro', client_reference='0')
        own_visit = Intervention.objects.create(service_request=own)
        Intervention.objects.create(service_request=other)
        self.api.force_authenticate(self.customer)
        result = self.api.get('/api/search/?q=0').data
        self.assertEqual([row['id'] for row in result['requests']], [own.pk])
        self.assertEqual([row['id'] for row in result['interventions']], [own_visit.pk])
        self.assertNotIn(longer.pk, [row['id'] for row in result['requests']])

    def test_search_rejects_oversize_nul_and_surrogates_without_server_error(self):
        values = ['x' * 201, '\x00']
        for path in ['/api/requests/', '/api/interventions/']:
            for field in ['q', 'call_number', 'client_reference']:
                for value in values:
                    self.assertEqual(self.api.get(path, {field: value}).status_code, 400)
                self.assertEqual(self.api.get(path + f'?{field}=%ED%A0%80').status_code, 400)
        for value in values:
            self.assertEqual(self.api.get('/api/search/', {'q': value}).status_code, 400)
        self.assertEqual(self.api.get('/api/search/?q=%ED%A0%80').status_code, 400)
        with self.assertRaises(ValidationError):
            reference_query_value({'q': '\ud800'}, 'q')

    def test_client_search_does_not_grant_writes(self):
        request = self.create_request(client_reference='ZERO-LAB')
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.api.get('/api/requests/?client_reference=ZERO').status_code, 200)
        self.assertEqual(self.api.patch(f'/api/requests/{request.pk}/', {'client_reference': 'CHANGED'}, format='json').status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Allocation concurrente PostgreSQL réelle')
class ConcurrentCallNumberTests(TransactionTestCase):
    def test_two_creations_obtain_distinct_consecutive_numbers(self):
        company = Client.objects.create(name='Centre numéros simultanés')
        equipment = Equipment.objects.create(client=company, serial_number='CALL-CONCURRENT-LAB', model='Fictif')
        ready = Barrier(2)

        def create(index):
            try:
                ready.wait(timeout=10)
                saved = ServiceRequest.objects.create(equipment_id=equipment.pk, subject=f'Appel simultané {index}')
                return saved.reference
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            numbers = list(pool.map(create, range(2), timeout=30))
        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(sorted(int(value[-5:]) for value in numbers), [1, 2])

    def test_intake_equipment_lock_does_not_deadlock_numbered_request_fk(self):
        from core.intake_service import _lookup_serial
        from core.request_numbering import next_request_number
        company = Client.objects.create(name='Centre concurrence réception')
        equipment = Equipment.objects.create(client=company, serial_number='CALL-MIXED-LAB', model='Fictif')
        manager = User.objects.create_user('call-concurrent-manager', role='manager')
        equipment_locked = Event()
        counter_locked = Event()

        def synchronized_lookup(data):
            equipment_locked.set()
            if not counter_locked.wait(10):
                raise RuntimeError('Counter coordination timed out')
            return _lookup_serial(data)

        def synchronized_number():
            number = next_request_number()
            counter_locked.set()
            return number

        def intake():
            try:
                actor = User.objects.get(pk=manager.pk)
                return create_intake({'request_key': str(uuid4()), 'serial_number': equipment.serial_number, 'equipment': equipment.pk, 'subject': 'Réception simultanée'}, actor=actor).request.reference
            finally:
                connections.close_all()

        def ordinary():
            try:
                if not equipment_locked.wait(10):
                    raise RuntimeError('Equipment coordination timed out')
                return ServiceRequest.objects.create(equipment_id=equipment.pk, subject='Création normale simultanée').reference
            finally:
                connections.close_all()

        with patch('core.intake_service._lookup_serial', side_effect=synchronized_lookup), patch('core.request_numbering.next_request_number', side_effect=synchronized_number):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(intake), pool.submit(ordinary)]
                numbers = [future.result(timeout=30) for future in futures]
        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(ServiceRequest.objects.count(), 2)
