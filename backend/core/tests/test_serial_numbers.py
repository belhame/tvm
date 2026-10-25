from django.contrib.auth import get_user_model
from django.test import Client as BrowserClient, SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.models import AuditLog, Client, Equipment
from core.serial_numbers import analyze_serial_number


class SerialNumberAnalysisTests(SimpleTestCase):
    def test_segments_are_read_without_invented_names_or_calendar_year(self):
        result = analyze_serial_number('S123A01000')
        self.assertEqual(result['status'], 'matches')
        self.assertEqual(result['segments'], {
            'manufacturing_location_code': 'S',
            'product_identification_code': '123',
            'year_code': 'A',
            'week_code': '01',
            'week_number': 1,
            'unit_order_code': '000',
        })
        self.assertIsNone(result['calendar_year'])
        self.assertNotIn('manufacturing_location_name', result)
        self.assertNotIn('equipment_model', result)
        self.assertNotIn('unit_counter', result)
        self.assertTrue(any('1011' in warning for warning in result['warnings']))

    def test_outer_whitespace_and_ascii_case_are_normalized_only_for_analysis(self):
        result = analyze_serial_number('  s123a01aa0  ')
        self.assertEqual(result['status'], 'matches')
        self.assertEqual(result['normalized_serial_number'], 'S123A01AA0')
        self.assertEqual(result['segments']['unit_order_code'], 'AA0')

    def test_plant_exclusions_differ_from_other_code_positions(self):
        self.assertEqual(analyze_serial_number('S123A01000')['status'], 'matches')
        self.assertEqual(analyze_serial_number('U123A01000')['status'], 'matches')
        self.assertEqual(analyze_serial_number('Z123A01000')['status'], 'matches')
        self.assertEqual(analyze_serial_number('A1S3A01000')['status'], 'not_applicable')
        for excluded in 'IOQX':
            with self.subTest(location=excluded):
                self.assertEqual(analyze_serial_number(f'{excluded}123A01000')['status'], 'not_applicable')

    def test_general_exclusions_apply_to_product_year_and_unit_order(self):
        for excluded in 'IOQSUXZ':
            for serial in (f'A1{excluded}3A01000', f'A123{excluded}01000', f'A123A01{excluded}00'):
                with self.subTest(serial=serial):
                    self.assertEqual(analyze_serial_number(serial)['status'], 'not_applicable')

    def test_year_code_is_not_restricted_to_unconfirmed_letter_examples_or_mapped(self):
        for code in 'ABCY01':
            with self.subTest(year_code=code):
                result = analyze_serial_number(f'A123{code}01000')
                self.assertEqual(result['status'], 'matches')
                self.assertEqual(result['segments']['year_code'], code)
                self.assertIsNone(result['calendar_year'])

    def test_week_must_be_two_digits_from_01_to_53(self):
        for week in ('00', '54', '99', 'A1', '1A'):
            with self.subTest(week=week):
                result = analyze_serial_number(f'A123A{week}000')
                self.assertEqual(result['status'], 'not_applicable')
                self.assertIsNone(result['segments'])
        self.assertEqual(analyze_serial_number('A123A53000')['segments']['week_number'], 53)

    def test_other_serial_formats_and_unicode_are_not_reinterpreted(self):
        for serial in ('OTHER-BRAND-0001', '', 'A123 A01000', 'A123A0100', 'A123A010000', 'Ａ123A01000', 'ß12A01000'):
            with self.subTest(serial=serial):
                self.assertEqual(analyze_serial_number(serial)['status'], 'not_applicable')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SerialNumberAnalysisAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Client.objects.create(name='Client analyse')
        User = get_user_model()
        cls.users = {
            role: User.objects.create_user(
                f'analysis-{role}', password='StrongAnalysisPhrase42!', role=role,
                client=cls.company if role == 'client' else None,
            )
            for role in ('admin', 'manager', 'technician', 'client')
        }

    def setUp(self):
        self.api = APIClient()

    def test_anonymous_access_is_denied(self):
        response = self.api.post('/api/serial-analysis/', {'serial_number': 'S123A01000'}, format='json')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_roles_get_same_pure_result_without_business_queries(self):
        expected = analyze_serial_number('S123A01000')
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.api.force_authenticate(user)
                with self.assertNumQueries(0):
                    response = self.api.post('/api/serial-analysis/', {'serial_number': 'S123A01000'}, format='json')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, expected)
        self.assertEqual(Equipment.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_input_type_is_strict_and_missing_blank_or_oversize_values_fail(self):
        self.api.force_authenticate(self.users['admin'])
        for value in (None, 1234567890, 1.5, True, [], {}, '', '   ', 'A' * 121):
            with self.subTest(value=value):
                response = self.api.post('/api/serial-analysis/', {'serial_number': value}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('serial_number', response.data)
        self.assertEqual(self.api.post('/api/serial-analysis/', {}, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/serial-analysis/', [], format='json').status_code, 400)

    def test_nonmatching_format_does_not_block_equipment_registration(self):
        self.api.force_authenticate(self.users['admin'])
        serial = 'OTHER-BRAND-0001'
        response = self.api.post('/api/serial-analysis/', {'serial_number': serial}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'not_applicable')
        response = self.api.post('/api/equipment/', {'client': self.company.pk, 'serial_number': serial, 'brand': 'Autre', 'model': 'Modèle libre'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Equipment.objects.get().serial_number, serial)

    def test_post_requires_csrf_with_real_cookie_session(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.users['admin'])
        body = {'serial_number': 'S123A01000'}
        self.assertEqual(browser.post('/api/serial-analysis/', body, content_type='application/json').status_code, 403)
        session = browser.get('/api/session/').json()
        response = browser.post('/api/serial-analysis/', body, content_type='application/json', HTTP_X_CSRFTOKEN=session['csrfToken'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'matches')

    def test_get_is_not_a_supported_analysis_method(self):
        self.api.force_authenticate(self.users['admin'])
        self.assertEqual(self.api.get('/api/serial-analysis/').status_code, 405)
