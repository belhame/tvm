from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.battery_catalogue import SPECS, resolve_battery_configuration


def equipment(model, *, brand='Eaton', catalogue_number='', product_name='', range_name='', version=''):
    product = SimpleNamespace(catalogue_number=catalogue_number, product_name=product_name, range_name=range_name, version=version) if any((catalogue_number, product_name, range_name, version)) else None
    return SimpleNamespace(model=model, brand=brand, catalogue_product=product)


class BatteryCatalogueTests(SimpleTestCase):
    def test_named_reference_aliases_have_no_normalized_collisions(self):
        aliases = {}
        for row in SPECS:
            for alias in row['aliases']:
                self.assertIn(aliases.get(alias), (None, row['reference']))
                aliases[alias] = row['reference']
        self.assertEqual(len(SPECS), 108)

    def test_exact_g2_model_and_linked_literal_generation(self):
        for unit in [equipment('5E700FG2'), equipment('Eaton 5E 700 G2'),
                     equipment('5E700F', catalogue_number='5E700F', product_name='Eaton 5E 700 FR G2')]:
            result = resolve_battery_configuration(unit)
            self.assertEqual((result['status'], result['nominal_count'], result['capacity_ah']), ('matched', 1, '7'))
            self.assertEqual(result['suppliers'], ['Leoch'])

    def test_generation_never_inferred_from_f_version_two_or_launch_year(self):
        for unit in [equipment('5E700F'), equipment('5E700F', catalogue_number='5E700F', version='2'),
                     equipment('5E700F', catalogue_number='5E700F', version='2023'), equipment('5E 700')]:
            result = resolve_battery_configuration(unit)
            self.assertEqual(result['status'], 'unknown')
            self.assertIsNone(result['nominal_count'])

    def test_explicit_generation_conflict_is_ambiguous(self):
        result = resolve_battery_configuration(equipment('5E700FG1', catalogue_number='5E700FG2', product_name='5E700FG2', range_name='5E G2'))
        self.assertEqual(result['status'], 'ambiguous')
        self.assertIsNone(result['nominal_count'])

    def test_launch_annotation_2019_cannot_promote_other_families_to_g2(self):
        for model, family in [('5P650i', '5P'), ('5E700F', '5E'), ('5PX1000IRT2U', '5PX')]:
            with self.subTest(model=model):
                result = resolve_battery_configuration(equipment(model, catalogue_number=model,
                    product_name=f'Eaton {model}', range_name=f'Eaton {family} (Launched 2019)'))
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['nominal_count'])
        legacy = resolve_battery_configuration(equipment('9SX2000I', catalogue_number='9SX2000I',
            product_name='Eaton 9SX2000I', range_name='Eaton 9SX (Launched2019)'))
        self.assertEqual((legacy['status'], legacy['nominal_count']), ('matched', 8))

    def test_explicit_2019_generation_remains_usable_for_3s_only(self):
        for model in ('3S850F', '3S550F'):
            with self.subTest(model=model):
                result = resolve_battery_configuration(equipment(model, catalogue_number=model,
                    product_name=f'Eaton {model}', range_name='Eaton 3S (Launched 2019)'))
                self.assertEqual((result['status'], result['nominal_count']), ('matched', 1))
        self.assertEqual(resolve_battery_configuration(equipment('3S 850 2019'))['status'], 'matched')

    def test_stale_linked_catalogue_does_not_identify_unknown_model(self):
        result = resolve_battery_configuration(equipment('Unknown laboratory model', catalogue_number='5E700F', product_name='5E700FG2', range_name='5E G2'))
        self.assertEqual(result['status'], 'unknown')

    def test_incompatible_linked_model_returns_ambiguity(self):
        result = resolve_battery_configuration(equipment('5E700FG2', catalogue_number='5E900G2', product_name='5E900G2'))
        self.assertEqual(result['status'], 'ambiguous')

    def test_tower_rack_and_other_manufacturer_are_distinct(self):
        tower = resolve_battery_configuration(equipment('9SX2000I'))
        rack = resolve_battery_configuration(equipment('9SX2000IR'))
        self.assertEqual((tower['nominal_count'], rack['nominal_count']), (8, 6))
        self.assertEqual(resolve_battery_configuration(equipment('9SX2000IR', brand='Other'))['status'], 'unknown')
        self.assertEqual(resolve_battery_configuration(equipment('9SX2000IRG2'))['status'], 'unknown')

    def test_elp850iec_uses_its_own_supplied_configuration(self):
        self.assertEqual(resolve_battery_configuration(equipment('ELP850IEC'))['nominal_count'], 2)
        self.assertEqual(resolve_battery_configuration(equipment('ELP850FR'))['nominal_count'], 1)

    def test_six_volt_1u_does_not_become_tower_twelve_volt(self):
        rack = resolve_battery_configuration(equipment('5P650IRG2'))
        tower = resolve_battery_configuration(equipment('5P650IG2'))
        self.assertEqual((rack['nominal_count'], rack['voltage_v']), (2, '6'))
        self.assertEqual((tower['nominal_count'], tower['voltage_v']), (1, '12'))

    def test_external_banks_are_counted_separately(self):
        bank = resolve_battery_configuration(equipment('9SX EBM 240T'))
        self.assertEqual((bank['nominal_count'], bank['equipment_kind']), (40, 'external_battery_cabinet'))
        self.assertIn('2 × 20', bank['configuration'])
        self.assertTrue(any('ne s’ajoute pas' in warning for warning in bank['warnings']))
        self.assertEqual(resolve_battery_configuration(equipment('EBM'))['status'], 'unknown')

    def test_high_power_requires_explicit_generation_and_phase(self):
        good = resolve_battery_configuration(equipment('9SX 6kVA 1:1 G2'))
        self.assertEqual((good['nominal_count'], good['capacity_ah']), (15, '5'))
        for label in ['9SX 6kVA G2', '9SX 6kVA', '9PX 6kVA']:
            self.assertEqual(resolve_battery_configuration(equipment(label))['status'], 'unknown')
        no_internal = resolve_battery_configuration(equipment('9PX 6kVA 3:1'))
        self.assertEqual(no_internal['nominal_count'], 0)
        self.assertTrue(no_internal['external_battery_required'])

    def test_new_rack_9e_not_confused_with_old_tower(self):
        tower = resolve_battery_configuration(equipment('9E6000I'))
        rack = resolve_battery_configuration(equipment('9E6000IR'))
        self.assertEqual((tower['capacity_ah'], rack['capacity_ah']), ('9', '5'))

    def test_bare_power_anonymous_table_never_identifies_model(self):
        for label in ['550', '550 VA', '700 VA', '900', '1300', '1700', '5E9999G2']:
            self.assertEqual(resolve_battery_configuration(equipment(label))['status'], 'unknown')

    def test_returns_independent_reference_payloads(self):
        before = deepcopy(SPECS)
        first = resolve_battery_configuration(equipment('5E700FG2'))
        first['suppliers'].append('Untrusted mutation')
        self.assertEqual(SPECS, before)
        self.assertEqual(resolve_battery_configuration(equipment('5E700FG2'))['suppliers'], ['Leoch'])
