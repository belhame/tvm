from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client as BrowserClient, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.catalogue_models import CatalogueImport, CatalogueProduct, CatalogueWarranty
from core.catalogue_service import import_catalogue
from core.models import AuditLog, Client, Contract, Equipment, Intervention, ServiceRequest, Warranty
from core.serial_lookup import add_calendar_months, canonical_range, lookup_serial


FIXTURE = Path(__file__).parent / 'fixtures' / 'request_intake_synthetic.xls'
SERIAL = 'GAB2A49002'  # Fictional catalogue code AB2, public fixture only.


class SerialCalendarTests(SimpleTestCase):
    def test_calendar_offset_is_six_months_not_180_days(self):
        self.assertEqual(add_calendar_months(date(2023, 12, 4), 6), date(2024, 6, 4))
        self.assertNotEqual(add_calendar_months(date(2023, 12, 4), 6), date(2023, 12, 4) + timedelta(days=180))
        self.assertEqual(add_calendar_months(date(2023, 8, 31), 6), date(2024, 2, 29))
        self.assertEqual(add_calendar_months(date(2024, 8, 31), 6), date(2025, 2, 28))

    def test_only_launch_annotation_is_removed_from_automatic_family_match(self):
        self.assertEqual(canonical_range('Famille fictive (Launched2020)'), canonical_range('Famille fictive'))
        self.assertEqual(canonical_range('Famille fictive (Launched 2020)'), canonical_range('Famille fictive'))
        self.assertNotEqual(canonical_range('Famille fictive (Only Electronic)'), canonical_range('Famille fictive'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SerialLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Entreprise lookup fictive')
        cls.admin = User.objects.create_user('lookup-admin', password='LookupTestingPhrase42!', role='admin')
        cls.manager = User.objects.create_user('lookup-manager', password='LookupTestingPhrase42!', role='manager')
        cls.tech = User.objects.create_user('lookup-tech', password='LookupTestingPhrase42!', role='technician')
        cls.customer = User.objects.create_user('lookup-client', password='LookupTestingPhrase42!', role='client', client=cls.company)
        cls.snapshot = import_catalogue(FIXTURE.read_bytes(), FIXTURE.name, actor=cls.admin).snapshot
        cls.product = CatalogueProduct.objects.get(snapshot=cls.snapshot, product_code='AB2')
        cls.reference = CatalogueWarranty.objects.get(snapshot=cls.snapshot, product_name='Laboratoire Garantie')

    def test_unique_catalogue_match_proposes_short_model_and_warranty_calendar_dates(self):
        result = lookup_serial(SERIAL)
        self.assertEqual(result['detection']['profile'], 'Eaton')
        self.assertEqual(result['detection']['year'], 2023)
        self.assertEqual(result['detection']['week'], 49)
        self.assertEqual(result['selected_product_id'], self.product.pk)
        self.assertEqual(result['selected_product']['short_model'], 'LAB850F')
        self.assertEqual(result['selected_product']['product_name'], 'Onduleur laboratoire Unique')
        self.assertEqual(result['manufactured_on'], '2023-12-04')
        self.assertEqual(result['default_warranty_id'], self.reference.pk)
        self.assertEqual(result['computed_warranty']['starts_on'], '2024-06-04')
        self.assertEqual(result['computed_warranty']['ends_on'], '2026-06-04')
        self.assertEqual(result['computed_warranty']['duration_months'], 24)
        self.assertEqual(result['computed_warranty']['rule']['start_offset_months'], 6)
        self.assertEqual(result['catalogue_import_id'], self.snapshot.pk)
        self.assertEqual((Equipment.objects.count(), Warranty.objects.count(), ServiceRequest.objects.count()), (0, 0, 0))

    def test_duplicate_code_requires_choice_and_does_not_pick_first(self):
        result = lookup_serial('GQX1A49002')
        self.assertEqual(len(result['product_candidates']), 2)
        self.assertIsNone(result['selected_product'])
        self.assertTrue(result['detection']['requires_product_choice'])
        chosen = result['product_candidates'][1]
        selected = lookup_serial('GQX1A49002', product_id=chosen['id'], catalogue_import_id=self.snapshot.pk)
        self.assertEqual(selected['selected_product_id'], chosen['id'])
        with self.assertRaises(ValidationError):
            lookup_serial('GQX1A49002', product_id=self.product.pk)

    def test_product_code_collision_cannot_displace_a_plausible_powerware_profile(self):
        CatalogueProduct.objects.create(snapshot=self.snapshot, source_row=700, product_name='Produit collision de laboratoire', product_code='S31', structure='Eaton')
        result = lookup_serial('RS315A0001')
        self.assertEqual(set(result['detection']['profile_options']), {'Eaton', 'Powerware'})
        self.assertTrue(result['detection']['requires_profile_choice'])
        self.assertIsNone(result['selected_product'])
        self.assertIsNone(result['manufactured_on'])
        chosen = lookup_serial('RS315A0001', profile='Powerware')
        self.assertEqual(chosen['detection']['profile'], 'Powerware')
        self.assertIsNotNone(chosen['manufactured_on'])

    def test_year_aliases_are_profile_specific_without_old_global_exclusions(self):
        for code in ('I', 'J'):
            result = lookup_serial(f'GAB2{code}49002')
            self.assertEqual(result['detection']['year'], 2024)
            self.assertEqual(result['manufactured_on'], '2024-12-02')
        pulsar = lookup_serial('QX1A49002')
        self.assertEqual(pulsar['detection']['profile'], 'Pulsar')
        self.assertEqual(pulsar['detection']['year'], 2001)
        self.assertTrue(pulsar['manufacture_date_basis']['reconstructed'])

    def test_unproved_year_or_repair_week_does_not_produce_dates(self):
        for serial in ('GAB2Z49002', 'QX1AAF002'):
            result = lookup_serial(serial)
            self.assertIsNone(result['manufactured_on'])
            self.assertIsNotNone(result['manufacture_date_basis']['blocked_reason'])
            self.assertNotEqual(result['computed_warranty']['coverage_status'], 'active')

    def test_refined_guarantee_options_stay_separate_and_need_explicit_choice(self):
        self.reference.product_name = 'Laboratoire Garantie (Launched2020)'
        self.reference.save()
        self.assertEqual(lookup_serial(SERIAL)['default_warranty_id'], self.reference.pk)
        other = CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=500, source_column='B', product_name='Laboratoire Garantie (Only Electronic)', scope='electronics', duration_text='3 years', duration_months=36)
        result = lookup_serial(SERIAL)
        self.assertEqual(len(result['warranty_options']), 1)
        self.assertEqual(result['default_warranty_id'], self.reference.pk)
        self.reference.product_name = 'Autre famille sans correspondance'
        self.reference.save()
        result = lookup_serial(SERIAL)
        self.assertEqual(len(result['warranty_options']), 1)
        self.assertIsNone(result['default_warranty_id'])
        selected = lookup_serial(SERIAL, warranty_reference_id=other.pk)
        self.assertEqual(selected['selected_warranty']['match_type'], 'related_manual')
        self.assertEqual(selected['computed_warranty']['duration_months'], 36)

    def test_manual_family_alternatives_include_internal_battery_without_combining_components(self):
        self.reference.product_name = 'Laboratoire Garantie (Only Electronic)'
        self.reference.scope = 'electronics'
        self.reference.save()
        CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=600, source_column='B', product_name='Laboratoire Garantie Internal battery', scope='batteries', duration_text='1 year', duration_months=12)
        result = lookup_serial(SERIAL)
        self.assertEqual({option['scope'] for option in result['warranty_options']}, {'electronics', 'batteries'})
        self.assertTrue(all(option['match_type'] == 'related_manual' for option in result['warranty_options']))
        self.assertIsNone(result['default_warranty_id'])
        self.assertEqual(result['computed_warranty']['status'], 'needs_choice')

    def test_manual_family_power_classes_respect_boundary_and_never_choose_longest(self):
        self.reference.product_name = 'Autre famille sans correspondance'
        self.reference.save()
        self.product.range_name = 'LAB9PX'
        self.product.save()
        for row, label, months in [(610, 'LAB9PX1–3kVA', 24), (611, 'LAB9PX5–11kVA', 36), (612, 'LAB9PXX 1–3kVA', 60)]:
            CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=row, source_column='B', product_name=label, scope='electronics', duration_text=f'{months} months', duration_months=months)
        result = lookup_serial(SERIAL)
        self.assertEqual(len(result['warranty_options']), 2)
        self.assertEqual({row['duration_months'] for row in result['warranty_options']}, {24, 36})
        self.assertIsNone(result['default_warranty_id'])
        self.assertIsNone(result['computed_warranty']['duration_months'])

    def test_components_do_not_default_to_the_longest_duration(self):
        self.reference.scope = 'electronics'
        self.reference.duration_months = 12
        self.reference.save()
        CatalogueWarranty.objects.create(snapshot=self.snapshot, source_row=501, source_column='B', product_name='Laboratoire Garantie', scope='batteries', duration_text='2 years', duration_months=24)
        result = lookup_serial(SERIAL)
        self.assertEqual({row['scope'] for row in result['warranty_options']}, {'electronics', 'batteries'})
        self.assertIsNone(result['default_warranty_id'])
        self.assertIsNone(result['computed_warranty']['duration_months'])

    def test_zero_months_has_no_coverage_and_future_fabrication_is_not_active(self):
        self.reference.duration_months = 0
        self.reference.save()
        result = lookup_serial(SERIAL)
        self.assertEqual(result['computed_warranty']['status'], 'no_coverage')
        self.assertEqual(result['computed_warranty']['coverage_status'], 'not_covered')
        self.assertIsNone(result['computed_warranty']['ends_on'])
        self.reference.duration_months = 24
        self.reference.save()
        metadata = self.snapshot.metadata
        for mapping in metadata['year_tables']:
            if mapping['structure'] == 'Eaton' and mapping['code'] == 'A':
                mapping['year'] = timezone.localdate().year + 2
        self.snapshot.metadata = metadata
        self.snapshot.save()
        result = lookup_serial(SERIAL)
        self.assertEqual(result['computed_warranty']['coverage_status'], 'not_started')
        self.assertTrue(any('future' in warning for warning in result['warnings']))

    def test_existing_equipment_recorded_scope_dates_history_and_contracts_take_priority(self):
        equipment = Equipment.objects.create(client=self.company, serial_number=SERIAL.lower(), model='Modèle réellement enregistré', manufactured_on='2020-01-06', warranty_until='2024-01-01')
        today = timezone.localdate()
        Warranty.objects.create(equipment=equipment, starts_on=today-timedelta(days=100), ends_on=today-timedelta(days=1), scope='electronics')
        Warranty.objects.create(equipment=equipment, starts_on=today-timedelta(days=10), ends_on=today+timedelta(days=100), scope='batteries')
        contract = Contract.objects.create(number='FICTIVE-CONTRACT', client=self.company, starts_on=today-timedelta(days=1), ends_on=today+timedelta(days=1), status='active')
        request = ServiceRequest.objects.create(equipment=equipment, subject='Dossier antérieur fictif')
        Intervention.objects.create(service_request=request, technician=self.tech)
        result = lookup_serial(SERIAL)
        self.assertEqual(result['existing_equipment']['model'], equipment.model)
        self.assertEqual(result['manufactured_on'], '2020-01-06')
        self.assertEqual(result['manufacture_date_basis']['type'], 'recorded')
        self.assertEqual(result['computed_warranty']['status'], 'recorded_priority')
        self.assertEqual({row['scope'] for row in result['recorded_warranties']}, {'electronics', 'batteries'})
        self.assertEqual({row['coverage_status'] for row in result['recorded_warranties']}, {'active', 'expired'})
        self.assertEqual(result['active_contracts'][0]['id'], contract.pk)
        self.assertEqual(len(result['history']['requests']), 1)
        self.assertEqual(len(result['history']['interventions']), 1)
        equipment.refresh_from_db()
        self.assertEqual(equipment.model, 'Modèle réellement enregistré')
        self.assertEqual(str(equipment.warranty_until), '2024-01-01')

    def test_legacy_global_end_date_is_preserved_without_claiming_component_coverage(self):
        equipment = Equipment.objects.create(client=self.company, serial_number=SERIAL, model='Modèle existant', warranty_until=date(2030, 4, 5))
        result = lookup_serial(SERIAL)
        self.assertEqual(result['computed_warranty']['status'], 'recorded_priority')
        self.assertEqual(result['computed_warranty']['ends_on'], '2030-04-05')
        self.assertEqual(result['computed_warranty']['scope'], 'unspecified')
        self.reference.scope = 'electronics'
        self.reference.save()
        component = lookup_serial(SERIAL)
        self.assertIsNone(component['computed_warranty']['ends_on'])
        self.assertEqual(component['computed_warranty']['coverage_status'], 'unknown')
        equipment.refresh_from_db()
        self.assertEqual(equipment.warranty_until, date(2030, 4, 5))

    def test_unique_active_recorded_extension_takes_priority_over_expired_base_period(self):
        equipment = Equipment.objects.create(client=self.company, serial_number=SERIAL, model='Modèle conservé')
        today = timezone.localdate()
        Warranty.objects.create(equipment=equipment, scope='unspecified', starts_on=today-timedelta(days=100), ends_on=today-timedelta(days=10))
        extension = Warranty.objects.create(equipment=equipment, scope='unspecified', starts_on=today-timedelta(days=9), ends_on=today+timedelta(days=100), provider='Extension enregistrée')
        result = lookup_serial(SERIAL)
        self.assertEqual(result['computed_warranty']['starts_on'], extension.starts_on.isoformat())
        self.assertEqual(result['computed_warranty']['ends_on'], extension.ends_on.isoformat())
        self.assertEqual(result['computed_warranty']['coverage_status'], 'active')
        self.assertEqual(len(result['recorded_warranties']), 2)
        self.assertEqual(Warranty.objects.filter(equipment=equipment).count(), 2)

    def test_no_catalogue_or_unknown_format_never_invents_a_model_or_date(self):
        unknown = lookup_serial('UNKNOWN-SERIES')
        self.assertIsNone(unknown['selected_product'])
        self.assertIsNone(unknown['manufactured_on'])
        CatalogueImport.objects.update(is_active=False)
        missing = lookup_serial(SERIAL)
        self.assertEqual(missing['detection']['status'], 'catalogue_unavailable')
        self.assertIsNone(missing['selected_product'])
        self.assertIsNone(missing['manufactured_on'])

    def test_powerware_has_no_automatic_product_and_nv_dx_do_not_invent_a_day_or_century(self):
        powerware = lookup_serial('GS313A0001', profile='Powerware')
        self.assertEqual(powerware['detection']['segments']['day_code'], '3')
        self.assertTrue(powerware['manufacture_date_basis']['reconstructed'])
        self.assertIsNone(powerware['selected_product'])
        for serial in ('32DA00001', '080704-00000001'):
            result = lookup_serial(serial, profile='NV DX')
            self.assertIsNone(result['manufactured_on'])
            self.assertNotEqual(result['computed_warranty']['coverage_status'], 'active')

    def test_lookup_is_read_only_even_when_selection_is_repeated(self):
        models = (Client, Equipment, Warranty, Contract, ServiceRequest, Intervention, CatalogueImport, CatalogueProduct, CatalogueWarranty, AuditLog)
        before = [model.objects.count() for model in models]
        for _ in range(3):
            lookup_serial(SERIAL, product_id=self.product.pk, warranty_reference_id=self.reference.pk, catalogue_import_id=self.snapshot.pk)
        self.assertEqual(before, [model.objects.count() for model in models])

    def test_existing_catalogue_link_conflict_is_reported_without_replacing_or_blocking_recorded_data(self):
        recorded_product = CatalogueProduct.objects.filter(snapshot=self.snapshot, structure='Eaton', product_code='QX1').first()
        equipment = Equipment.objects.create(client=self.company, serial_number=SERIAL, model='Référence conservée', catalogue_product=recorded_product)
        result = lookup_serial(SERIAL)
        self.assertEqual(result['existing_equipment']['model'], 'Référence conservée')
        self.assertEqual(result['selected_product_id'], recorded_product.pk)
        self.assertTrue(any('diffère' in warning for warning in result['warnings']))
        equipment.refresh_from_db()
        self.assertEqual(equipment.catalogue_product_id, recorded_product.pk)

    def test_recorded_battery_dates_do_not_become_electronics_coverage(self):
        self.reference.scope = 'electronics'
        self.reference.save()
        equipment = Equipment.objects.create(client=self.company, serial_number=SERIAL, model='Modèle réellement enregistré')
        today = timezone.localdate()
        warranty = Warranty.objects.create(equipment=equipment, scope='batteries', starts_on=today-timedelta(days=10), ends_on=today+timedelta(days=100))
        result = lookup_serial(SERIAL)
        self.assertEqual(result['computed_warranty']['status'], 'recorded_priority')
        self.assertIsNone(result['computed_warranty']['starts_on'])
        self.assertIsNone(result['computed_warranty']['ends_on'])
        self.assertEqual(result['computed_warranty']['coverage_status'], 'unknown')
        self.assertEqual(result['recorded_warranties'][0]['scope'], 'batteries')
        warranty.scope = 'electronics'
        warranty.save()
        compatible = lookup_serial(SERIAL)
        self.assertEqual(compatible['computed_warranty']['starts_on'], warranty.starts_on.isoformat())
        self.assertEqual(compatible['computed_warranty']['coverage_status'], 'active')

    def test_invalid_types_and_foreign_reference_ids_are_rejected(self):
        for value in (None, '', 1234567890, True, 'x' * 121, 'A\x00B', 'A\ud800B'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                lookup_serial(value)
        for value in (True, '1', 1.5, 0, -1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                lookup_serial(SERIAL, product_id=value)
        with self.assertRaises(ValidationError):
            lookup_serial(SERIAL, warranty_reference_id=999999)
        with self.assertRaises(ValidationError):
            lookup_serial(SERIAL, profile='Unproved manufacturer')

    def test_api_internal_roles_csrf_and_client_isolation(self):
        api = APIClient()
        self.assertIn(api.post('/api/serial-lookup/', {'serial_number': SERIAL}, format='json').status_code, (401, 403))
        for user in (self.admin, self.manager, self.tech):
            api.force_authenticate(user)
            self.assertEqual(api.post('/api/serial-lookup/', {'serial_number': SERIAL}, format='json').status_code, 200)
        api.force_authenticate(self.customer)
        self.assertEqual(api.post('/api/serial-lookup/', {'serial_number': SERIAL}, format='json').status_code, 403)
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.manager)
        self.assertEqual(browser.post('/api/serial-lookup/', {'serial_number': SERIAL}, content_type='application/json').status_code, 403)
        token = browser.get('/api/session/').json()['csrfToken']
        self.assertEqual(browser.post('/api/serial-lookup/', {'serial_number': SERIAL}, content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 200)
