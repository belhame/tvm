"""Warranty tracker regressions use the fictional laboratory workbook only."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.catalogue_models import CatalogueWarranty
from core.catalogue_service import import_catalogue
from core.models import AuditLog, Client, Equipment, ServiceRequest, Warranty
from core.serial_lookup import find_serial_product, find_serial_products, generation_family, lookup_serial
from core.simple_intake import lookup_intake


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WarrantyRefreshTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user('warranty-laboratory', role='technician')
        cls.admin = get_user_model().objects.create_user('warranty-laboratory-admin', role='admin')
        cls.company = Client.objects.create(name='Centre garantie de laboratoire')
        path = Path(__file__).with_name('fixtures') / 'request_intake_synthetic.xls'
        cls.snapshot = import_catalogue(path.read_bytes(), path.name, actor=cls.admin).snapshot
        cls.product = cls.snapshot.products.get(product_code='AB2')
        cls.reference = cls.snapshot.warranties.get(product_name='Laboratoire Garantie')

    def setUp(self):
        self.product.range_name = 'Laboratoire Garantie G2'
        self.product.save(update_fields=['range_name'])

    def test_generic_generation_family_restores_reference_and_six_calendar_months(self):
        with patch('core.serial_lookup.timezone.localdate', return_value=date(2025, 1, 2)):
            result = lookup_serial('GAB2A49002')
        check = result['warranty_check']
        self.assertEqual(result['selected_warranty']['match_type'], 'generation_family')
        self.assertEqual(check['generation'], 'Gen 2')
        self.assertEqual(check['status'], 'active')
        self.assertEqual(check['manufactured_on'], '2023-12-04')
        self.assertEqual(check['starts_on'], '2024-06-04')
        self.assertEqual(check['ends_on'], '2026-06-04')
        self.assertEqual(check['duration_months'], 24)
        self.assertEqual(check['checked_on'], '2025-01-02')
        self.assertTrue(check['provisional'])
        self.assertEqual(check['rule']['start_offset_months'], 6)
        self.assertEqual(check['source']['warranty_row'], self.reference.source_row)
        self.assertTrue(any('génération' in text for text in check['warnings']))

    def test_generation_specific_reference_overrides_generic_family(self):
        exact = CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=900, source_column='B',
            product_name=self.product.range_name, scope='electronics_and_batteries', duration_months=12)
        result = lookup_serial('GAB2A49002')
        self.assertEqual(result['default_warranty_id'], exact.pk)
        self.assertEqual(result['warranty_check']['duration_months'], 12)
        self.assertEqual(result['selected_warranty']['match_type'], 'exact_range')

    def test_generation_qualified_components_block_generic_shortcut(self):
        CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=900, source_column='B',
            product_name=self.product.range_name + ' (Only Electronic)', scope='electronics', duration_months=12)
        result = lookup_serial('GAB2A49002')
        self.assertIsNone(result['default_warranty_id'])
        self.assertIsNone(result['selected_warranty'])
        self.assertEqual(result['warranty_check']['status'], 'unknown')
        self.assertEqual(len(result['warranty_options']), 1)
        self.assertEqual(result['warranty_options'][0]['match_type'], 'related_manual')

    def test_generic_components_never_automatically_cover_generation(self):
        self.reference.scope = 'batteries'
        self.reference.save(update_fields=['scope'])
        result = lookup_serial('GAB2A49002')
        self.assertIsNone(result['selected_warranty'])
        self.assertEqual(result['warranty_check']['status'], 'unknown')
        simple = lookup_intake(self.staff, client=self.company.pk, serial_number='GAB2A49002')
        self.assertEqual(simple['warranty_check']['status'], 'unknown')

    def test_variants_and_other_generation_names_are_not_discarded(self):
        for value in ('Laboratoire Garantie Rack G2', 'Laboratoire Garantie G2 Rack', 'Laboratoire Garantie2', 'Laboratoire Garantie G2X'):
            with self.subTest(value=value):
                self.product.range_name = value
                self.product.save(update_fields=['range_name'])
                result = lookup_serial('GAB2A49002')
                self.assertIsNone(result['selected_warranty'])
                self.assertEqual(result['warranty_check']['status'], 'unknown')
        self.assertEqual(generation_family('Famille (Launched2020) Gen 2'), ('Famille', 'Gen 2'))

    def test_two_generic_references_remain_ambiguous(self):
        CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=900, source_column='B',
            product_name=self.reference.product_name, scope='unspecified', duration_months=36)
        result = lookup_serial('GAB2A49002')
        self.assertIsNone(result['selected_warranty'])
        self.assertEqual(result['warranty_check']['status'], 'unknown')
        self.assertEqual(result['computed_warranty']['status'], 'needs_choice')

    def test_recorded_full_scope_warranty_takes_priority_without_hiding_catalogue_estimate(self):
        unit = Equipment.objects.create(client=self.company, serial_number='GAB2A49002', model='LAB850F',
            catalogue_product=self.product, manufactured_on=date(2020, 1, 6))
        actual = Warranty.objects.create(equipment=unit, scope='electronics_and_batteries',
            starts_on=date(2026, 1, 1), ends_on=date(2028, 1, 1))
        with patch('core.serial_lookup.timezone.localdate', return_value=date(2026, 10, 28)):
            result = lookup_serial(unit.serial_number)
        self.assertEqual(result['warranty_check']['basis'], 'recorded')
        self.assertEqual(result['warranty_check']['scope'], 'electronics_and_batteries')
        self.assertEqual(result['warranty_check']['status'], 'active')
        self.assertEqual(result['warranty_check']['starts_on'], actual.starts_on.isoformat())
        self.assertEqual(result['catalogue_manufactured_on'], '2023-12-04')
        self.assertEqual(result['catalogue_computed_warranty']['coverage_status'], 'expired')
        self.assertEqual(result['catalogue_computed_warranty']['starts_on'], '2024-06-04')
        unit.refresh_from_db()
        self.assertEqual(unit.manufactured_on, date(2020, 1, 6))

    def test_unknown_year_no_reference_and_zero_duration_have_no_active_badge(self):
        result = lookup_serial('GAB2Z49002')
        self.assertEqual(result['warranty_check']['status'], 'unknown')
        self.assertIsNone(result['warranty_check']['starts_on'])
        self.reference.duration_months = 0
        self.reference.save(update_fields=['duration_months'])
        result = lookup_serial('GAB2A49002')
        self.assertEqual(result['warranty_check']['status'], 'no_coverage')
        self.assertIsNone(result['warranty_check']['ends_on'])

    def test_simple_intake_gets_same_tracker_without_creating_business_records(self):
        counts = tuple(model.objects.count() for model in (Equipment, ServiceRequest, Warranty, AuditLog))
        with patch('core.serial_lookup.timezone.localdate', return_value=date(2025, 1, 2)):
            simple = lookup_intake(self.staff, client=self.company.pk, serial_number='GAB2A49002')
        check = simple['warranty_check']
        self.assertEqual(simple['coverage']['status'], 'active')
        self.assertEqual(check['status'], 'active')
        self.assertEqual(check['generation'], 'Gen 2')
        self.assertEqual(check['starts_on'], '2024-06-04')
        self.assertEqual(check['ends_on'], '2026-06-04')
        self.assertEqual(check['source']['warranty_match_type'], 'generation_family')
        self.assertEqual(tuple(model.objects.count() for model in (Equipment, ServiceRequest, Warranty, AuditLog)), counts)

    def test_mismatching_recorded_model_cannot_inherit_catalogue_identity_or_coverage(self):
        unit = Equipment.objects.create(client=self.company, serial_number='GAB2A49002',
            model='Autre matériel réellement enregistré', brand='Marque conservée')
        with patch('core.serial_lookup.timezone.localdate', return_value=date(2025, 1, 2)):
            result = lookup_serial(unit.serial_number)
            simple = lookup_intake(self.staff, client=self.company.pk, serial_number=unit.serial_number)
        for check in (result['warranty_check'], simple['warranty_check']):
            self.assertFalse(check['catalogue_identity_consistent'])
            self.assertEqual(check['status'], 'unknown')
            self.assertEqual(check['model_name'], unit.model)
            self.assertEqual(check['manufacturer'], unit.brand)
            self.assertEqual(check['industrial_part_number'], '')
            self.assertEqual(check['generation'], '')
            self.assertIsNone(check['duration_months'])
            self.assertIsNone(check['manufactured_on'])
            self.assertTrue(any('référence' in text for text in check['warnings']))

    def test_week_date_keeps_its_precision_and_historical_profile_is_not_rebranded(self):
        result = lookup_serial('GAB2A49002')
        self.assertEqual(result['warranty_check']['manufacture_date_basis']['precision'], 'week')
        self.assertEqual(result['warranty_check']['manufacture_date_basis']['type'], 'iso_week')
        pulsar_product = self.snapshot.products.filter(structure='Pulsar', product_code='QX1').first()
        self.assertIsNotNone(pulsar_product)
        result = lookup_serial('QX1A49002', profile='Pulsar', product_id=pulsar_product.pk)
        self.assertEqual(result['warranty_check']['manufacturer'], 'Pulsar')
        self.assertEqual(result['warranty_check']['profile'], 'Pulsar')
        self.assertTrue(result['warranty_check']['manufacture_date_basis']['reconstructed'])

    def test_expiry_boundary_uses_local_check_day_and_never_chooses_longest(self):
        for day, expected in ((date(2026, 6, 4), 'active'), (date(2026, 6, 5), 'expired')):
            with self.subTest(day=day), patch('core.serial_lookup.timezone.localdate', return_value=day):
                self.assertEqual(lookup_serial('GAB2A49002')['warranty_check']['status'], expected)

    def test_lightweight_serial_identification_requires_unique_profile_and_product(self):
        self.assertEqual(find_serial_product('GAB2A49002').pk, self.product.pk)
        self.assertIsNone(find_serial_product('GQX1A49002'))  # Two fixture products share this code.
        self.assertIsNone(find_serial_product('RS315A0001'))  # Two plausible numbering profiles.
        self.assertIsNone(find_serial_product('UNKNOWN-LAB-001'))
        self.assertIsNone(find_serial_product(None))
        self.assertFalse(Equipment.objects.exists())

    def test_batch_serial_identification_has_bounded_queries_and_retains_ambiguity(self):
        serials = ['GAB2A49002', 'GAB2A49003', 'GQX1A49002', 'RS315A0001', 'UNKNOWN-LAB-001']
        with self.assertNumQueries(2):
            candidates = find_serial_products(serials)
        self.assertEqual(candidates[serials[0]].pk, self.product.pk)
        self.assertEqual(candidates[serials[1]].pk, self.product.pk)
        self.assertTrue(all(candidates[serial] is None for serial in serials[2:]))
