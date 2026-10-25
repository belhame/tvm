"""Pure geometry tests with fictional product codes and year mappings only."""
from copy import deepcopy
from unittest import TestCase

from core.serial_geometry import decode_profiles


YEAR_TABLES = [
    {'structure': 'Eaton', 'code': 'A', 'year': 2024, 'raw_code': 'A'},
    {'structure': 'Eaton', 'code': 'I', 'year': 2024, 'raw_code': 'I/J'},
    {'structure': 'Eaton', 'code': 'J', 'year': 2024, 'raw_code': 'I/J'},
    {'structure': 'Pulsar', 'code': 'A', 'year': 2016, 'raw_code': 'A'},
    {'structure': 'Powerware', 'code': 'K', 'year': 2020, 'raw_code': 'K'},
]


class SerialGeometryTests(TestCase):
    def one(self, serial, profile, tables=None):
        candidates = decode_profiles(serial, YEAR_TABLES if tables is None else tables, profile)
        self.assertEqual(len(candidates), 1, candidates)
        return candidates[0]

    def test_eaton_segments_and_proven_reference_monday(self):
        result = self.one('TQX1A01001', 'Eaton')
        self.assertEqual(result['format'], 'eaton_10')
        self.assertEqual(result['segments'], {
            'manufacturing_location_code': 'T', 'product_code': 'QX1',
            'year_code': 'A', 'week_code': '01', 'unit_order_code': '001',
        })
        self.assertEqual((result['year'], result['week'], result['manufactured_on']), (2024, 1, '2024-01-01'))
        self.assertEqual(result['manufacture_date_basis']['type'], 'iso_week')
        self.assertEqual(result['manufacture_date_basis']['precision'], 'week')
        self.assertFalse(result['manufacture_date_basis']['reconstructed'])
        self.assertIsNone(result['manufacture_date_basis']['blocked_reason'])
        self.assertTrue(any('contractuel' in warning for warning in result['warnings']))

    def test_year_aliases_are_not_rejected_by_global_character_exclusions(self):
        for code in ('I', 'J'):
            with self.subTest(code=code):
                result = self.one(f'TQX1{code}01001', 'Eaton')
                self.assertEqual(result['year'], 2024)
                self.assertEqual(result['manufactured_on'], '2024-01-01')

    def test_unknown_or_conflicting_year_never_uses_a_guessed_cycle(self):
        unknown = self.one('TQX1Z01001', 'Eaton')
        self.assertIsNone(unknown['year'])
        self.assertIsNone(unknown['manufactured_on'])
        self.assertTrue(unknown['manufacture_date_basis']['blocked_reason'])
        conflict = YEAR_TABLES + [{'structure': 'Eaton', 'code': 'A', 'year': 2025}]
        result = self.one('TQX1A01001', 'Eaton', conflict)
        self.assertIsNone(result['year'])
        self.assertIsNone(result['manufactured_on'])
        self.assertTrue(any('Plusieurs années' in warning for warning in result['warnings']))

    def test_duplicate_identical_year_records_are_not_an_ambiguity(self):
        tables = YEAR_TABLES + [YEAR_TABLES[0].copy()]
        self.assertEqual(self.one('TQX1A01001', 'Eaton', tables)['year'], 2024)

    def test_iso_week_53_is_checked_against_the_year_without_normalization(self):
        tables = [{'structure': 'Eaton', 'code': 'A', 'year': 2020}]
        self.assertEqual(self.one('TQX1A53001', 'Eaton', tables)['manufactured_on'], '2020-12-28')
        invalid = self.one('TQX1A53001', 'Eaton', [{'structure': 'Eaton', 'code': 'A', 'year': 2021}])
        self.assertIsNone(invalid['manufactured_on'])
        self.assertEqual(invalid['week'], 53)
        for week in ('00', '54', 'AA'):
            with self.subTest(week=week):
                result = self.one(f'TQX1A{week}001', 'Eaton')
                self.assertIsNone(result['week'])
                self.assertIsNone(result['manufactured_on'])

    def test_pulsar_has_different_positions_and_profile_specific_year(self):
        result = self.one('QX1A01001', 'Pulsar')
        self.assertEqual(result['segments']['product_code'], 'QX1')
        self.assertEqual(result['year'], 2016)
        self.assertEqual(result['manufactured_on'], '2016-01-04')
        basis = result['manufacture_date_basis']
        self.assertEqual(basis['type'], 'reconstructed_iso_week')
        self.assertTrue(basis['reconstructed'])
        self.assertTrue(any('convention ISO' in warning for warning in result['warnings']))

    def test_pulsar_oem_suffix_is_preserved(self):
        result = self.one('QX1A01001BC', 'Pulsar')
        self.assertEqual(result['format'], 'pulsar_oem_11')
        self.assertEqual(result['segments']['oem_code'], 'BC')
        self.assertEqual(result['segments']['unit_order_code'], '001')
        self.assertEqual(result['manufactured_on'], '2016-01-04')

    def test_pulsar_repair_week_never_becomes_manufacturing_or_warranty_date(self):
        result = self.one('QX1ADC00A', 'Pulsar')
        self.assertIsNone(result['manufactured_on'])
        self.assertIsNone(result['year'])
        self.assertIsNone(result['week'])
        self.assertTrue(any('réparation' in warning for warning in result['warnings']))

    def test_powerware_preserves_day_but_uses_an_explicit_internal_week_convention(self):
        result = self.one('RK015A0001', 'Powerware')
        self.assertEqual(result['segments'], {
            'manufacturing_location_code': 'R', 'year_code': 'K', 'week_code': '01',
            'day_code': '5', 'special_code': 'A', 'unit_order_code': '0001',
        })
        self.assertNotIn('product_code', result['segments'])
        self.assertEqual(result['manufactured_on'], '2019-12-30')
        self.assertEqual(result['manufacture_date_basis']['type'], 'reconstructed_iso_week')
        self.assertTrue(result['manufacture_date_basis']['reconstructed'])
        self.assertTrue(any('jour Powerware' in warning for warning in result['warnings']))

    def test_powerware_special_use_invalid_day_or_zero_order_block_date(self):
        for serial in ('RK015B0001', 'RK010A0001', 'RK018A0001', 'RK015A0000'):
            with self.subTest(serial=serial):
                result = self.one(serial, 'Powerware')
                self.assertIsNone(result['manufactured_on'])
                self.assertTrue(result['manufacture_date_basis']['blocked_reason'])

    def test_all_compatible_geometries_are_returned_instead_of_selecting_a_profile(self):
        result = decode_profiles('RK015A0001', YEAR_TABLES)
        self.assertEqual({r['profile'] for r in result}, {'Eaton', 'Powerware'})
        self.assertEqual({r['profile'] for r in decode_profiles('RK015A0001', YEAR_TABLES, ' Powerware ')}, {'Powerware'})

    def test_nv_keeps_month_precision_without_an_invented_first_day(self):
        result = self.one('33D100001', 'NV DX')
        self.assertEqual(result['format'], 'nv_9')
        self.assertEqual(result['segments']['production_code'], '33')
        self.assertEqual(result['segments']['product_code'], '3')
        self.assertEqual(result['segments']['month_code'], '1')
        self.assertEqual(result['segments']['month_number'], 1)
        self.assertEqual(result['year'], 2010)
        self.assertIsNone(result['manufactured_on'])
        self.assertEqual(result['manufacture_date_basis']['type'], 'month_only')
        self.assertEqual(result['manufacture_date_basis']['precision'], 'month')
        for code, month in [('9', 9), ('A', 10), ('B', 11), ('C', 12)]:
            with self.subTest(code=code):
                self.assertEqual(self.one(f'33D{code}00001', 'NV DX')['segments']['month_number'], month)

    def test_nv_known_years_do_not_extrapolate_later_letters(self):
        for code, year in [('1', 2001), ('9', 2009), ('D', 2010), ('E', 2011), ('F', 2012)]:
            with self.subTest(code=code):
                self.assertEqual(self.one(f'33{code}100001', 'NV DX')['year'], year)
        self.assertIsNone(self.one('33G100001', 'NV DX')['year'])
        self.assertIsNone(self.one('33D100001', 'NV DX', [{'structure': 'NV DX', 'code': 'D', 'year': 2040}])['year'])

    def test_nv_invalid_month_or_zero_order_requires_manual_validation(self):
        for serial in ('33D000001', '33DD00001', '33D100000'):
            with self.subTest(serial=serial):
                result = self.one(serial, 'NV DX')
                self.assertIsNone(result['manufactured_on'])
                self.assertTrue(result['manufacture_date_basis']['blocked_reason'])

    def test_dx_never_guesses_century_even_for_a_valid_calendar_pattern(self):
        result = self.one('240229-00000001', 'NV DX')
        self.assertEqual(result['format'], 'dx_15')
        self.assertEqual(result['segments']['year_code'], '24')
        self.assertEqual(result['segments']['month_code'], '02')
        self.assertEqual(result['segments']['day_code'], '29')
        self.assertIsNone(result['year'])
        self.assertIsNone(result['manufactured_on'])
        self.assertTrue(any('siècle' in warning for warning in result['warnings']))
        invalid = self.one('240431-00000001', 'NV DX')
        self.assertIsNone(invalid['manufactured_on'])
        self.assertTrue(any('impossibles' in warning for warning in invalid['warnings']))

    def test_ascii_normalization_is_local_and_inputs_are_unchanged(self):
        tables = deepcopy(YEAR_TABLES)
        serial = '  tqx1a01001  '
        self.assertEqual(self.one(serial, 'eaton', tables)['segments']['product_code'], 'QX1')
        self.assertEqual(serial, '  tqx1a01001  ')
        self.assertEqual(tables, YEAR_TABLES)
        for unsupported in ('ＴQX1A01001', 'TQX1 A01001', 'OTHER-BRAND-001', '', 'ßQX1A0100'):
            with self.subTest(serial=unsupported):
                self.assertEqual(decode_profiles(unsupported, YEAR_TABLES), [])
        self.assertEqual(decode_profiles('TQX1A01001', YEAR_TABLES, 'unknown'), [])

    def test_contract_rejects_wrong_types_without_coercing_identifiers(self):
        for value in (1234567890, None, True, []):
            with self.subTest(value=value), self.assertRaises(TypeError):
                decode_profiles(value, YEAR_TABLES)
        with self.assertRaises(TypeError):
            decode_profiles('TQX1A01001', {})
        with self.assertRaises(TypeError):
            decode_profiles('TQX1A01001', YEAR_TABLES, 1)

    def test_every_candidate_has_complete_date_provenance(self):
        for serial in ('TQX1A01001', 'QX1A01001', 'RK015A0001', '33D100001', '240229-00000001'):
            for candidate in decode_profiles(serial, YEAR_TABLES):
                with self.subTest(serial=serial, format=candidate['format']):
                    self.assertEqual(set(candidate['manufacture_date_basis']), {'type', 'reconstructed', 'source', 'precision', 'blocked_reason'})
                    self.assertTrue(candidate['manufacture_date_basis']['source'])
                    self.assertTrue(candidate['warnings'])
