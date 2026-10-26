"""Independent client-import/privacy checks using fictional records only."""

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection, connections
from django.test import Client as BrowserClient, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from core.client_import import ClientImportError, import_clients_csv, normalized_name
from core.models import AuditLog, Client, Equipment, ServiceRequest


def client_csv(rows, columns=None):
    columns = columns or ['name', 'contact_name', 'tax_id', 'phone', 'notes']
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentClientImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user('client-review-admin', role='admin')
        cls.tech = get_user_model().objects.create_user('client-review-tech', role='technician')

    def test_preview_has_no_writes_and_apply_is_idempotent_without_mutating_existing(self):
        original = Client.objects.create(name='Atelier Existant', contact_name='Contact initial', notes='Note déjà enregistrée', legacy_id='0000000000000091')
        before = list(Client.objects.order_by('pk').values())
        data = client_csv([
            ['Atelier Existant', 'Contact initial', '', '', 'Note déjà enregistrée'],
            ['Laboratoire Nouveau', 'Contact neuf', '000042-00-A', '+216 00 000 001', 'À vérifier'],
        ])
        preview = import_clients_csv(data, 'fictional.csv', actor=self.admin)
        self.assertEqual(preview['summary']['create'], 1)
        self.assertEqual(preview['summary']['existing'], 1)
        self.assertEqual(list(Client.objects.order_by('pk').values()), before)
        self.assertFalse(AuditLog.objects.exists())

        applied = import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True, expected_sha256=preview['sha256'])
        self.assertEqual(applied['summary']['created'], 1)
        self.assertEqual(list(Client.objects.filter(pk=original.pk).values()), before)
        added = Client.objects.get(name='Laboratoire Nouveau')
        self.assertEqual(added.tax_id, '000042-00-A')
        self.assertEqual(added.phone, '+216 00 000 001')
        self.assertEqual(added.country, '')
        self.assertEqual(get_user_model().objects.count(), 2)
        after = list(Client.objects.order_by('pk').values())
        replay = import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(replay['summary']['created'], 0)
        self.assertEqual(replay['summary']['existing'], 2)
        self.assertEqual(list(Client.objects.order_by('pk').values()), after)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_same_company_two_contacts_are_conflicts_and_never_merged(self):
        data = client_csv([
            ['Société Fictive', 'Contact Alpha', '', '', 'Site A'],
            ['Société Fictive', 'Contact Bêta', '', '', 'Site B'],
        ])
        result = import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['conflict'], 2)
        self.assertEqual(result['summary']['created'], 0)
        self.assertFalse(Client.objects.exists())

    def test_existing_homonym_with_another_contact_is_neither_updated_nor_merged(self):
        original = Client.objects.create(name='Société Fictive', contact_name='Contact Alpha', notes='Privé initial')
        before = Client.objects.filter(pk=original.pk).values().get()
        result = import_clients_csv(client_csv([['Société Fictive', 'Contact Bêta', '', '', 'Autre site']]), 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['conflict'], 1)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Client.objects.filter(pk=original.pk).values().get(), before)

    def test_existing_name_with_missing_contact_requires_manual_completion(self):
        original = Client.objects.create(name='Atelier Sans Contact')
        result = import_clients_csv(client_csv([['Atelier Sans Contact', 'Contact proposé', '', '', '']]), 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['existing'], 1)
        self.assertTrue(result['rows'][0]['errors'])
        original.refresh_from_db()
        self.assertEqual(original.contact_name, '')
        self.assertEqual(Client.objects.count(), 1)

    def test_normalization_is_conservative_about_accents_and_punctuation(self):
        self.assertEqual(normalized_name('  ÉQUIPE\u00a0  Ａtelier  '), normalized_name('équipe Atelier'))
        self.assertNotEqual(normalized_name('Équipe Atelier'), normalized_name('Equipe Atelier'))
        self.assertNotEqual(normalized_name('Atelier-Est'), normalized_name('Atelier Est'))
        original = Client.objects.create(name='Équipe Atelier', contact_name='Contact')
        data = client_csv([
            ['  ÉQUIPE\u00a0  Ａtelier ', 'Contact', '', '', ''],
            ['Equipe Atelier', 'Autre Contact', '', '', ''],
        ])
        result = import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['existing'], 1)
        self.assertEqual(result['summary']['created'], 1)
        original.refresh_from_db()
        self.assertEqual(original.name, 'Équipe Atelier')
        self.assertEqual(Client.objects.count(), 2)

    def test_two_existing_homonyms_block_name_based_import(self):
        Client.objects.create(name='Entreprise Jumelle', contact_name='Alpha')
        Client.objects.create(name='Entreprise Jumelle', contact_name='Bêta')
        result = import_clients_csv(client_csv([['Entreprise Jumelle', 'Alpha', '', '', '']]), 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['conflict'], 1)
        self.assertEqual(Client.objects.count(), 2)

    def test_formula_like_text_is_stored_as_text_and_phone_plus_is_preserved(self):
        data = client_csv([['=Laboratoire Fictif', '@Contact', '000042', '+216 00 000 001', '=1+1\n<script>fictional()</script>']])
        result = import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['created'], 1)
        row = Client.objects.get()
        self.assertEqual(row.name, '=Laboratoire Fictif')
        self.assertEqual(row.phone, '+216 00 000 001')
        self.assertEqual(row.notes, '=1+1\n<script>fictional()</script>')

    def test_secret_identity_and_unknown_columns_are_rejected_before_writes(self):
        for forbidden in ('password', 'mot_de_passe', 'is_superuser', 'id', 'legacy_id', 'client_id', 'unknown'):
            with self.subTest(column=forbidden), self.assertRaises(ClientImportError):
                import_clients_csv(client_csv([['Laboratoire', 'never-import']], ['name', forbidden]), 'fictional.csv', actor=self.admin, apply=True)
        self.assertFalse(Client.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_dangerous_control_and_invalid_email_do_not_create_records(self):
        result = import_clients_csv(client_csv([['Atelier\x1b Interdit', '']], ['name', 'email']), 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['invalid'], 1)
        result = import_clients_csv(client_csv([['Atelier Fictif', 'not-an-email']], ['name', 'email']), 'fictional.csv', actor=self.admin, apply=True)
        self.assertEqual(result['summary']['invalid'], 1)
        self.assertFalse(Client.objects.exists())

    def test_changed_file_after_preview_and_unauthorized_actor_cannot_apply(self):
        data = client_csv([['Atelier Fictif']], ['name'])
        with self.assertRaises(ClientImportError):
            import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True, expected_sha256='0' * 64)
        with self.assertRaises(PermissionDenied):
            import_clients_csv(data, 'fictional.csv', actor=self.tech, apply=True)
        self.assertFalse(Client.objects.exists())

    def test_audit_failure_rolls_back_all_new_clients_and_audit_entries(self):
        data = client_csv([['Atelier Alpha'], ['Atelier Bêta']], ['name'])
        real_create = AuditLog.objects.create
        call_count = 0

        def fail_second_audit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise DatabaseError('Synthetic failure')
            return real_create(*args, **kwargs)

        with patch('core.client_import.AuditLog.objects.create', side_effect=fail_second_audit), self.assertRaises(DatabaseError):
            import_clients_csv(data, 'fictional.csv', actor=self.admin, apply=True)
        self.assertFalse(Client.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_csrf_session_upload_limits_real_stream_before_import(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.admin.set_password('OnlyFictionalCsrfReview42!')
        self.admin.save(update_fields=['password'])
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        token = browser.get('/api/session/').json()['csrfToken']
        # Below the 3 MiB request-header ceiling, above the 2 MiB file ceiling.
        # The upload handler must bound the actual stream before the view reads
        # it, including when CSRF accesses request.POST during authentication.
        with patch('core.client_import_views.import_clients_csv') as importer:
            response = browser.post('/api/clients/import/', {
                'file': SimpleUploadedFile('fictional.csv', b'name\n' + b'X' * (2 * 1024 * 1024)),
                'mode': 'apply',
            }, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 413)
        importer.assert_not_called()
        self.assertFalse(Client.objects.exists())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentClientDirectoryPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Atelier Revue Fictif', notes='PRIVATE_CLIENT_NOTE_SENTINEL', tax_id='00000042')
        cls.other = Client.objects.create(name='Atelier Étranger Fictif', notes='FOREIGN_NOTE_SENTINEL')
        cls.admin = User.objects.create_user('directory-review-admin', role='admin')
        cls.customer = User.objects.create_user('directory-review-client', role='client', client=cls.company)
        User.objects.create_user('directory-review-client-two', role='client', client=cls.company)
        User.objects.create_user('directory-review-client-disabled', role='client', client=cls.company, is_active=False)
        for index in range(2):
            equipment = Equipment.objects.create(client=cls.company, serial_number=f'CLIENT-REVIEW-{index}', model='Fictional')
            ServiceRequest.objects.create(equipment=equipment, subject=f'Ouvert {index}')
            ServiceRequest.objects.create(equipment=equipment, subject=f'Fermé {index}', status='closed')

    def setUp(self):
        self.api = APIClient()

    def test_counts_are_distinct_across_equipment_requests_and_portal_users(self):
        self.api.force_authenticate(self.admin)
        response = self.api.get(f'/api/clients/{self.company.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['equipment_count'], 2)
        self.assertEqual(response.data['open_requests_count'], 2)
        self.assertEqual(response.data['portal_users_count'], 2)
        self.assertEqual(response.data['notes'], 'PRIVATE_CLIENT_NOTE_SENTINEL')

    def test_portal_list_detail_search_never_expose_notes_or_foreign_client(self):
        self.api.force_authenticate(self.customer)
        for url in ('/api/clients/', f'/api/clients/{self.company.pk}/', '/api/search/?q=Atelier'):
            with self.subTest(url=url):
                response = self.api.get(url)
                self.assertEqual(response.status_code, 200, response.data)
                serialized = str(response.data)
                self.assertNotIn('PRIVATE_CLIENT_NOTE_SENTINEL', serialized)
                self.assertNotIn('FOREIGN_NOTE_SENTINEL', serialized)
                self.assertNotIn('portal_users_count', serialized)
                self.assertNotIn(self.other.name, serialized)
        self.assertEqual(self.api.get(f'/api/clients/{self.other.pk}/').status_code, 404)
        self.assertEqual(self.api.patch(f'/api/clients/{self.company.pk}/', {'notes': 'Changed'}, format='json').status_code, 403)

    def test_portal_cannot_preview_or_apply_import_even_with_valid_csv(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.api.force_authenticate(self.customer)
        for mode in ('preview', 'apply'):
            response = self.api.post('/api/clients/import/', {'file': SimpleUploadedFile('fictional.csv', client_csv([['New fictional']], ['name'])), 'mode': mode}, format='multipart')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Client.objects.count(), 2)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL advisory locks.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentClientImportConcurrencyTests(TransactionTestCase):
    def test_concurrent_imports_create_one_client_and_one_audit_without_updates(self):
        actor = get_user_model().objects.create_user('client-import-concurrency-review', role='admin')
        gate = Barrier(2, timeout=10)
        data = client_csv([['Laboratoire Concurrence Fictif', 'Contact fictif', '00000052', '', 'Donnée fictive']])

        def worker():
            close_old_connections()
            try:
                current_actor = get_user_model().objects.get(pk=actor.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                gate.wait()
                result = import_clients_csv(data, 'fictional.csv', actor=current_actor, apply=True)
                return result['summary']['created'], result['summary']['existing']
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=25) for future in futures]
        self.assertEqual(sorted(results), [(0, 1), (1, 0)])
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Client.objects.get().tax_id, '00000052')
        self.assertEqual(AuditLog.objects.filter(action='import_create', resource='client').count(), 1)
