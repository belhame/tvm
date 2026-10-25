from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import Client as BrowserClient, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from rest_framework.test import APIClient

from core.catalogue_models import CatalogueImport, CatalogueProduct, CatalogueState, CatalogueWarranty
from core.catalogue_parser import parse_catalogue
from core.catalogue_service import CatalogueValidationError, analyse_catalogue, import_catalogue
from core.models import AuditLog, Client, Equipment, Warranty


FIXTURE = Path(__file__).parent / 'fixtures' / 'catalogue_synthetic.xls'
DATA = FIXTURE.read_bytes()


def parsed_for(data, *, name=None):
    parsed = deepcopy(parse_catalogue(DATA, filename='catalogue_synthetic.xls'))
    parsed['metadata']['sha256'] = hashlib.sha256(data).hexdigest()
    if name:
        parsed['products'][0]['product_name'] = name
    return parsed


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Société catalogue fictive')
        cls.admin = User.objects.create_user('catalogue-admin', password='CatalogueTestingPhrase42!', role='admin')
        cls.manager = User.objects.create_user('catalogue-manager', password='CatalogueTestingPhrase42!', role='manager')
        cls.tech = User.objects.create_user('catalogue-tech', password='CatalogueTestingPhrase42!', role='technician')
        cls.customer = User.objects.create_user('catalogue-client', password='CatalogueTestingPhrase42!', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='UNCHANGED-001', model='Modèle existant', warranty_until='2028-01-01')
        cls.snapshot = import_catalogue(DATA, FIXTURE.name, actor=cls.admin).snapshot

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def upload(self, data=DATA):
        return self.api.post('/api/catalogue/import/', {'file': SimpleUploadedFile('catalogue.xls', data, content_type='application/vnd.ms-excel')}, format='multipart')

    def other_version(self):
        data = DATA + b'synthetic-next-version'
        with patch('core.catalogue_parser.parse_catalogue', return_value=parsed_for(data, name='Nouveau produit fictif')):
            return import_catalogue(data, 'next.xls', actor=self.manager).snapshot

    def test_initial_snapshot_preserves_source_rows_collisions_and_raw_values(self):
        self.assertEqual(self.snapshot.product_count, 4)
        self.assertEqual(self.snapshot.warranty_count, 6)
        self.assertEqual(CatalogueProduct.objects.count(), 4)
        self.assertEqual(CatalogueWarranty.objects.count(), 6)
        self.assertEqual(CatalogueProduct.objects.filter(product_code='QX1').count(), 3)
        self.assertEqual(CatalogueProduct.objects.filter(product_code='NA').count(), 1)
        for source in parse_catalogue(DATA, filename=FIXTURE.name)['products']:
            product = self.snapshot.products.get(source_row=source['source_row'])
            self.assertEqual(product.raw_data, source['raw_data'])
            self.assertEqual(product.launch_year, source['launch_year_raw'])
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.model, 'Modèle existant')
        self.assertEqual(str(self.equipment.warranty_until), '2028-01-01')
        self.assertEqual((Client.objects.count(), Equipment.objects.count(), Warranty.objects.count()), (1, 1, 0))

    def test_same_digest_is_strictly_idempotent_when_already_active(self):
        before_audit = AuditLog.objects.count()
        result = import_catalogue(DATA, 'renamed.xls', actor=self.manager)
        self.assertFalse(result.created)
        self.assertFalse(result.activated)
        self.assertEqual(result.snapshot.pk, self.snapshot.pk)
        self.assertEqual(CatalogueImport.objects.count(), 1)
        self.assertEqual(CatalogueProduct.objects.count(), 4)
        self.assertEqual(AuditLog.objects.count(), before_audit)
        self.assertEqual(result.snapshot.imported_by_id, self.admin.pk)

    def test_new_snapshot_and_reactivation_keep_versions_without_duplication(self):
        newer = self.other_version()
        self.snapshot.refresh_from_db()
        self.assertFalse(self.snapshot.is_active)
        self.assertTrue(newer.is_active)
        self.assertEqual(CatalogueImport.objects.filter(is_active=True).count(), 1)
        result = import_catalogue(DATA, FIXTURE.name, actor=self.manager)
        self.assertFalse(result.created)
        self.assertTrue(result.activated)
        self.assertEqual(result.snapshot.pk, self.snapshot.pk)
        self.assertEqual((CatalogueImport.objects.count(), CatalogueProduct.objects.count()), (2, 8))
        self.assertEqual(CatalogueImport.objects.get(is_active=True).pk, self.snapshot.pk)

    def test_invalid_workbook_does_not_change_the_active_import(self):
        with self.assertRaises(CatalogueValidationError):
            import_catalogue(b'not an XLS workbook', 'wrong.xls', actor=self.admin)
        self.assertEqual(CatalogueImport.objects.get(is_active=True).pk, self.snapshot.pk)
        self.assertEqual(CatalogueImport.objects.count(), 1)

    def test_insert_failure_rolls_back_everything_and_retains_active_import(self):
        data = DATA + b'duplicate-row'
        parsed = parsed_for(data)
        parsed['products'][1]['source_row'] = parsed['products'][0]['source_row']
        with patch('core.catalogue_parser.parse_catalogue', return_value=parsed):
            with self.assertRaises(IntegrityError):
                import_catalogue(data, 'duplicate.xls', actor=self.admin)
        self.assertEqual(CatalogueImport.objects.get(is_active=True).pk, self.snapshot.pk)
        self.assertEqual((CatalogueImport.objects.count(), CatalogueProduct.objects.count()), (1, 4))

    def test_failure_after_activation_also_rolls_back_old_active_state(self):
        data = DATA + b'audit-failure'
        with patch('core.catalogue_parser.parse_catalogue', return_value=parsed_for(data)):
            with patch('core.catalogue_service.AuditLog.objects.create', side_effect=RuntimeError('synthetic failure')):
                with self.assertRaises(RuntimeError):
                    import_catalogue(data, 'failure.xls', actor=self.admin)
        self.assertEqual(CatalogueImport.objects.get(is_active=True).pk, self.snapshot.pk)
        self.assertEqual((CatalogueImport.objects.count(), CatalogueProduct.objects.count()), (1, 4))

    def test_database_constraints_prohibit_two_active_versions_and_bad_state_ids(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogueImport.objects.create(filename='other.xls', sha256='f' * 64, product_count=0, warranty_count=0, is_active=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogueState.objects.create(pk=2)

    def test_status_exposes_provenance_counts_and_profile_specific_year_tables(self):
        response = self.api.get('/api/catalogue/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['available'])
        self.assertEqual(response.data['active_import']['id'], self.snapshot.pk)
        self.assertEqual(response.data['counts']['products'], 4)
        self.assertEqual(response.data['counts']['na_codes'], 1)
        self.assertEqual(response.data['counts']['duplicate_code_groups'], 1)
        self.assertEqual(len(response.data['year_tables']), 9)
        self.assertEqual(response.data['active_import']['metadata']['revision'], 'ZZ')

    def test_search_profile_filter_flags_and_ambiguity_are_not_lost_by_search(self):
        rows = self.api.get('/api/catalogue/products/?q=QX1&structure=Eaton').data
        self.assertEqual(rows['count'], 2)
        self.assertTrue(all(row['code_is_ambiguous'] for row in rows['results']))
        first = rows['results'][0]
        self.assertEqual(first['equipment_model_suggestion'], first['product_name'])
        product = CatalogueProduct.objects.get(pk=first['id'])
        response = self.api.get('/api/catalogue/products/', {'q': product.manufacturing_part_number, 'structure': 'Eaton'})
        self.assertTrue(response.data['results'][0]['code_is_ambiguous'])
        pulsar = self.api.get('/api/catalogue/products/?q=QX1&structure=Pulsar').data['results']
        self.assertEqual(len(pulsar), 1)
        self.assertFalse(pulsar[0]['code_is_ambiguous'])
        placeholder = self.api.get('/api/catalogue/products/?q=NA').data['results']
        placeholder = next(row for row in placeholder if row['product_code'] == 'NA')
        self.assertFalse(placeholder['code_is_usable'])
        self.assertFalse(placeholder['code_is_ambiguous'])

    def test_pagination_has_default_50_and_caps_requested_size_at_100(self):
        CatalogueProduct.objects.bulk_create([CatalogueProduct(snapshot=self.snapshot, source_row=1000 + i, product_name=f'Produit pagination {i}', structure='Eaton') for i in range(105)])
        first = self.api.get('/api/catalogue/products/').data
        self.assertEqual(first['count'], 109)
        self.assertEqual(len(first['results']), 50)
        self.assertEqual(first['page_size'], 50)
        self.assertIsNotNone(first['next'])
        self.assertEqual(len(self.api.get('/api/catalogue/products/?page_size=999').data['results']), 100)
        self.assertEqual(len(self.api.get('/api/catalogue/products/?page=3').data['results']), 9)

    def test_no_silent_truncation_of_long_model_names_and_search_input(self):
        product = self.snapshot.products.first()
        product.product_name = 'X' * 121
        product.save()
        response = self.api.get('/api/catalogue/products/')
        row = next(row for row in response.data['results'] if row['id'] == product.pk)
        self.assertEqual(row['product_name'], 'X' * 121)
        self.assertIsNone(row['equipment_model_suggestion'])
        self.assertEqual(self.api.get('/api/catalogue/products/', {'q': 'a' * 200}).status_code, 200)
        self.assertEqual(self.api.get('/api/catalogue/products/', {'q': 'a' * 201}).status_code, 400)

    def test_guarantees_are_separate_records_with_uncertainty_and_provenance(self):
        response = self.api.get('/api/catalogue/warranties/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 6)
        self.assertTrue(any(row['scope'] == 'electronics' for row in response.data))
        self.assertTrue(any(row['scope'] == 'batteries' for row in response.data))
        self.assertTrue(any(row['duration_months'] is None for row in response.data))
        self.assertTrue(all(row['source_column'] and row['raw_data'] for row in response.data))
        self.assertEqual(Warranty.objects.count(), 0)

    def test_pages_and_guarantees_can_be_pinned_to_an_immutable_old_version(self):
        newer = self.other_version()
        response = self.api.get('/api/catalogue/products/', {'import_id': self.snapshot.pk})
        self.assertEqual(response.data['import_id'], self.snapshot.pk)
        self.assertTrue(all(row['import_id'] == self.snapshot.pk for row in response.data['results']))
        self.assertNotIn('Nouveau produit fictif', str(response.data))
        current = self.api.get('/api/catalogue/products/').data
        self.assertEqual(current['import_id'], newer.pk)
        warranties = self.api.get('/api/catalogue/warranties/', {'import_id': self.snapshot.pk}).data
        self.assertTrue(all(row['import_id'] == self.snapshot.pk for row in warranties))
        for invalid in ('0', '-1', 'x', '9' * 10000, '9223372036854775808'):
            with self.subTest(import_id=invalid):
                self.assertEqual(self.api.get('/api/catalogue/products/', {'import_id': invalid}).status_code, 400)

    def test_internal_read_permissions_and_client_exclusion_cover_all_routes(self):
        for user in (self.admin, self.manager, self.tech):
            self.api.force_authenticate(user)
            for route in ('', 'products/', 'warranties/'):
                self.assertEqual(self.api.get('/api/catalogue/' + route).status_code, 200)
        self.api.force_authenticate(self.customer)
        for route in ('', 'products/', 'warranties/'):
            self.assertEqual(self.api.get('/api/catalogue/' + route, {'import_id': self.snapshot.pk}).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        self.api.force_authenticate(self.tech)
        self.assertEqual(self.upload().status_code, 403)
        self.api.force_authenticate(user=None)
        for route in ('', 'products/', 'warranties/'):
            self.assertIn(self.api.get('/api/catalogue/' + route).status_code, (401, 403))

    def test_upload_reports_known_digest_and_invalid_files_leave_active_intact(self):
        self.api.force_authenticate(self.manager)
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['created'])
        self.assertTrue(response.data['already_imported'])
        self.assertFalse(response.data['activated'])
        self.assertEqual(self.upload(b'bad workbook').status_code, 400)
        self.assertEqual(self.api.post('/api/catalogue/import/', {}, format='multipart').status_code, 400)
        self.assertEqual(self.upload(b'x' * (8 * 1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(CatalogueImport.objects.get(is_active=True).pk, self.snapshot.pk)

    def test_upload_requires_session_csrf_and_accepts_a_file_above_memory_threshold(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.manager)
        response = browser.post('/api/catalogue/import/', {'file': SimpleUploadedFile('catalogue.xls', DATA)})
        self.assertEqual(response.status_code, 403)
        token = browser.get('/api/session/').json()['csrfToken']
        large = b'x' * (3 * 1024 * 1024)
        with patch('core.catalogue_parser.parse_catalogue', return_value=parsed_for(large)):
            response = browser.post('/api/catalogue/import/', {'file': SimpleUploadedFile('large.xls', large)}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()['created'])

    def test_empty_active_state_is_explicit(self):
        CatalogueImport.objects.update(is_active=False)
        response = self.api.get('/api/catalogue/')
        self.assertFalse(response.data['available'])
        self.assertIsNone(response.data['active_import'])
        self.assertEqual(response.data['counts']['products'], 0)
        self.assertEqual(self.api.get('/api/catalogue/products/').data['results'], [])
        self.assertEqual(self.api.get('/api/catalogue/warranties/').data, [])

    def test_validate_only_command_writes_nothing_and_import_requires_an_authorized_actor(self):
        before = (CatalogueImport.objects.count(), CatalogueProduct.objects.count(), AuditLog.objects.count())
        call_command('import_eaton_catalogue', str(FIXTURE), validate_only=True, stdout=StringIO())
        self.assertEqual(before, (CatalogueImport.objects.count(), CatalogueProduct.objects.count(), AuditLog.objects.count()))
        for username in (None, self.tech.username, self.customer.username, 'missing-user'):
            with self.subTest(actor=username), self.assertRaises(CommandError):
                call_command('import_eaton_catalogue', str(FIXTURE), actor=username, stdout=StringIO())
        call_command('import_eaton_catalogue', str(FIXTURE), actor=self.manager.username, stdout=StringIO())
        self.assertEqual(CatalogueImport.objects.count(), 1)

    def test_client_serial_analysis_does_not_expose_catalogue_or_query_it(self):
        self.api.force_authenticate(self.customer)
        with self.assertNumQueries(0):
            response = self.api.post('/api/serial-analysis/', {'serial_number': 'S123A01000'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('catalogue', response.data)
        self.assertNotIn('product_name', response.data)
        self.assertNotIn('year_tables', response.data)


@skipUnlessDBFeature('has_select_for_update')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CatalogueConcurrencyTests(TransactionTestCase):
    def test_two_concurrent_imports_of_the_same_digest_create_one_snapshot(self):
        actor = get_user_model().objects.create_user('catalogue-concurrent', password='ConcurrentTestingPhrase42!', role='admin')
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                result = import_catalogue(DATA, FIXTURE.name, actor=user)
                return result.snapshot.pk, result.created
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: worker(), range(2)))
        self.assertEqual(len({pk for pk, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(CatalogueImport.objects.count(), 1)
        self.assertEqual(CatalogueImport.objects.filter(is_active=True).count(), 1)
        self.assertEqual(CatalogueProduct.objects.count(), 4)
