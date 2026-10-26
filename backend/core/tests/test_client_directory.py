import csv
import io
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client as BrowserClient, TestCase, override_settings
from rest_framework.test import APIClient

from core.client_import import CLIENT_COLUMNS, MAX_CLIENT_BYTES, ClientImportError, import_clients_csv, parse_clients_csv
from core.models import AuditLog, Client, Equipment, ServiceRequest


def csv_file(rows, header=CLIENT_COLUMNS, delimiter=';', bom=True):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=header, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return (('\ufeff' if bom else '') + stream.getvalue()).encode('utf-8')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ClientDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('directory-admin', password='FictionalDirectoryPhrase42!', role='admin')
        cls.manager = User.objects.create_user('directory-manager', password='FictionalDirectoryPhrase42!', role='manager')
        cls.tech = User.objects.create_user('directory-tech', password='FictionalDirectoryPhrase42!', role='technician')
        cls.company = Client.objects.create(name='Atelier client fictif', contact_name='Contact fictif', tax_id='000001/EXEMPLE', email='contact@example.invalid', phone='+000 123 456', notes='Note interne fictive')
        cls.other = Client.objects.create(name='Autre société fictive', notes='Note autre société')
        cls.customer = User.objects.create_user('directory-customer', password='FictionalDirectoryPhrase42!', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='DIRECTORY-FICTION-001', model='Modèle fictif')
        ServiceRequest.objects.create(equipment=cls.equipment, subject='Appel fictif actif')
        ServiceRequest.objects.create(equipment=cls.equipment, subject='Appel fictif clôturé', status='closed')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def upload(self, data, mode='preview', **kwargs):
        return self.api.post('/api/clients/import/', {'file': SimpleUploadedFile('clients.csv', data, content_type='text/csv'), 'mode': mode, **kwargs}, format='multipart')

    def test_directory_search_and_real_counts(self):
        row = self.api.get('/api/clients/', {'q': '000001/EXEMPLE'}).data[0]
        self.assertEqual(row['id'], self.company.pk)
        self.assertEqual((row['equipment_count'], row['open_requests_count'], row['portal_users_count']), (1, 1, 1))
        self.assertEqual(row['notes'], 'Note interne fictive')
        for query in ('contact@example.invalid', '+000 123', 'Contact fictif', 'atelier'):
            response = self.api.get('/api/clients/', {'q': query})
            self.assertEqual([row['id'] for row in response.data], [self.company.pk])
        self.assertEqual(self.api.get('/api/clients/', {'q': '\x00'}).status_code, 400)
        self.assertEqual(self.api.get('/api/clients/', {'q': 'a' * 201}).status_code, 400)

    def test_client_portal_scopes_before_search_and_omits_internal_notes(self):
        self.api.force_authenticate(self.customer)
        rows = self.api.get('/api/clients/').data
        self.assertEqual([row['id'] for row in rows], [self.company.pk])
        self.assertNotIn('notes', rows[0])
        self.assertNotIn('portal_users_count', rows[0])
        self.assertEqual(rows[0]['tax_id'], '000001/EXEMPLE')
        self.assertEqual(self.api.get('/api/clients/', {'q': 'Autre'}).data, [])
        self.assertEqual(self.api.get(f'/api/clients/{self.other.pk}/').status_code, 404)

    def test_client_tax_id_text_and_notes_edit_are_saved(self):
        response = self.api.patch(f'/api/clients/{self.company.pk}/', {'tax_id': '000001/A/M/000', 'notes': 'Donnée à vérifier'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.tax_id, '000001/A/M/000')
        self.assertEqual(self.company.notes, 'Donnée à vérifier')
        self.assertEqual(self.api.patch(f'/api/clients/{self.company.pk}/', {'notes': 'x' * 4001}, format='json').status_code, 400)

    def test_preview_never_writes_and_apply_preserves_zeroes_no_accounts(self):
        data = csv_file([{'name': 'Centre import fictif', 'tax_id': '000072/EXEMPLE', 'phone': '+000 123 456', 'notes': 'Transcription fictive à vérifier'}])
        counts = Client.objects.count(), get_user_model().objects.count(), AuditLog.objects.count()
        result = self.upload(data)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.data['applied'])
        self.assertEqual(result.data['summary']['create'], 1)
        self.assertEqual((Client.objects.count(), get_user_model().objects.count(), AuditLog.objects.count()), counts)
        response = self.upload(data, mode='apply', sha256=result.data['sha256'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['created'], 1)
        client = Client.objects.get(name='Centre import fictif')
        self.assertEqual((client.tax_id, client.country), ('000072/EXEMPLE', ''))
        self.assertEqual(get_user_model().objects.count(), counts[1])
        audit = AuditLog.objects.get(resource='client', resource_id=str(client.pk), action='import_create')
        self.assertEqual(audit.actor_id, self.admin.pk)
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_repeated_import_is_idempotent_and_never_overwrites(self):
        data = csv_file([{'name': 'Centre répétition fictif', 'email': 'source@example.invalid'}])
        self.upload(data, mode='apply')
        original = Client.objects.get(name='Centre répétition fictif')
        result = self.upload(data, mode='apply')
        self.assertEqual(result.data['summary']['existing'], 1)
        self.assertEqual(result.data['summary']['created'], 0)
        changed = csv_file([{'name': ' CENTRE   RÉPÉTITION FICTIF ', 'email': 'different@example.invalid'}])
        conflict = self.upload(changed, mode='apply')
        self.assertEqual(conflict.data['summary']['conflict'], 1)
        original.refresh_from_db()
        self.assertEqual(original.email, 'source@example.invalid')
        self.assertEqual(Client.objects.filter(name__icontains='répétition').count(), 1)

    def test_duplicate_identical_rows_skipped_distinct_contacts_not_merged(self):
        repeated = {'name': 'Société identique fictive', 'contact_name': 'Contact exemple'}
        result = self.upload(csv_file([repeated, repeated]), mode='apply')
        self.assertEqual((result.data['summary']['created'], result.data['summary']['duplicate']), (1, 1))
        conflict = self.upload(csv_file([{'name': 'Société ambiguë fictive', 'contact_name': 'Premier'}, {'name': 'Société ambiguë fictive', 'contact_name': 'Second'}]), mode='apply')
        self.assertEqual(conflict.data['summary']['conflict'], 2)
        self.assertFalse(Client.objects.filter(name='Société ambiguë fictive').exists())

    def test_existing_homonyms_or_tax_id_under_another_name_are_conflicts(self):
        Client.objects.create(name='Nom commun fictif')
        Client.objects.create(name='NOM COMMUN FICTIF')
        result = self.upload(csv_file([{'name': 'nom commun fictif'}, {'name': 'Autre identité fiscale fictive', 'tax_id': '000001/EXEMPLE'}]), mode='apply')
        self.assertEqual((result.data['summary']['conflict'], result.data['summary']['created']), (2, 0))

    def test_blank_existing_details_are_never_auto_completed(self):
        existing = Client.objects.create(name='Complément fictif', country='')
        result = self.upload(csv_file([{'name': 'Complément fictif', 'email': 'complete@example.invalid'}]), mode='apply')
        self.assertEqual(result.data['rows'][0]['status'], 'existing')
        self.assertIn('manuellement', result.data['rows'][0]['errors'][0])
        existing.refresh_from_db()
        self.assertEqual(existing.email, '')

    def test_tax_id_conflicts_inside_source_but_shared_email_is_not_identity(self):
        result = self.upload(csv_file([{'name': 'Fiscal Alpha fictif', 'tax_id': '0000X'}, {'name': 'Fiscal Beta fictif', 'tax_id': '0000X'}, {'name': 'Courriel Alpha fictif', 'email': 'shared@example.invalid'}, {'name': 'Courriel Beta fictif', 'email': 'shared@example.invalid'}]), mode='apply')
        self.assertEqual((result.data['summary']['conflict'], result.data['summary']['created']), (2, 2))

    def test_invalid_row_does_not_prevent_other_valid_rows(self):
        result = self.upload(csv_file([{'name': 'Valide fictif'}, {'name': 'Courriel incorrect fictif', 'email': 'not-an-email'}, {'name': '', 'contact_name': 'Contact sans société'}]), mode='apply')
        self.assertEqual((result.data['summary']['created'], result.data['summary']['invalid']), (1, 2))
        self.assertEqual(result.data['summary']['skipped'], 2)
        self.assertEqual(result.data['rows'][1]['data'], {})

    def test_sha256_mismatch_mode_and_multiple_files_rejected(self):
        data = csv_file([{'name': 'Ne pas importer fictif'}])
        self.assertEqual(self.upload(data, mode='apply', sha256='0' * 64).status_code, 400)
        self.assertEqual(self.upload(data, mode='bad').status_code, 400)
        response = self.api.post('/api/clients/import/', {'file': [SimpleUploadedFile('a.csv', data), SimpleUploadedFile('b.csv', data)]}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Client.objects.filter(name='Ne pas importer fictif').exists())

    def test_credential_columns_unknown_headers_and_malformed_csv_rejected(self):
        for data in (b'name;password\nFiction;secret-do-not-log\n', b'name;unknown\nFiction;value\n', b'name;name\nFiction;Fiction\n', b'email\ncontact@example.invalid\n', b'name\n"unterminated', b'name\n\x00bad', b'name\n\xff\xfe'):
            with self.subTest(data=data[:20]):
                response = self.upload(data, mode='apply')
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('secret-do-not-log', str(response.data))

    def test_parser_bom_comma_multiline_and_optional_columns(self):
        rows = parse_clients_csv(csv_file([{'name': 'Exemple avec accents é', 'address': 'Ligne 1\nLigne 2'}], delimiter=','), 'clients.CSV')
        self.assertEqual(rows[0]['data']['address'], 'Ligne 1\nLigne 2')
        self.assertEqual(rows[0]['data']['name'], 'Exemple avec accents é')
        self.assertEqual(parse_clients_csv(b'name\nFiction\n', 'clients.csv')[0]['data']['country'], '')

    def test_rows_limit_size_extension_and_control_characters(self):
        with self.assertRaises(ClientImportError):
            parse_clients_csv(b'name\n' + b'A' * MAX_CLIENT_BYTES, 'clients.csv')
        with self.assertRaises(ClientImportError):
            parse_clients_csv(b'name\nFiction\n', 'clients.xls')
        with self.assertRaises(ClientImportError):
            parse_clients_csv(b'name\n' + b'Fiction\n' * 5001, 'clients.csv')
        self.assertEqual(parse_clients_csv(b'name\nFic\x01tion\n', 'clients.csv')[0]['status'], 'invalid')
        response = self.upload(b'name\n' + b'A' * MAX_CLIENT_BYTES)
        self.assertEqual(response.status_code, 413)
        browser = BrowserClient()
        response = browser.generic('POST', '/api/clients/import/', b'x', content_type='multipart/form-data', CONTENT_LENGTH=str(3 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_import_roles_and_inactive_cli_actor(self):
        data = csv_file([{'name': 'Permissions fictives'}])
        for actor in (self.tech, self.customer, None):
            self.api.force_authenticate(actor)
            self.assertEqual(self.upload(data).status_code, 403)
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.upload(data).status_code, 200)
        self.manager.is_active = False
        with self.assertRaises(PermissionDenied):
            import_clients_csv(data, 'clients.csv', actor=self.manager)

    def test_import_transaction_rolls_back_on_audit_failure(self):
        data = csv_file([{'name': 'Rollback un fictif'}, {'name': 'Rollback deux fictif'}])
        with patch('core.client_import.AuditLog.objects.create', side_effect=RuntimeError('Fictional audit failure')):
            with self.assertRaises(RuntimeError):
                import_clients_csv(data, 'clients.csv', actor=self.admin, apply=True)
        self.assertFalse(Client.objects.filter(name__startswith='Rollback').exists())

    def test_command_defaults_to_private_simulation_then_apply(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'clients.csv'
            path.write_bytes(csv_file([{'name': 'Client commande fictif', 'email': 'private@example.invalid'}]))
            stdout = StringIO()
            call_command('import_clients', str(path), actor=self.admin.username, stdout=stdout)
            self.assertIn('Simulation sans écriture', stdout.getvalue())
            self.assertNotIn('private@example.invalid', stdout.getvalue())
            self.assertFalse(Client.objects.filter(name='Client commande fictif').exists())
            call_command('import_clients', str(path), actor=self.admin.username, apply=True, stdout=StringIO())
            self.assertTrue(Client.objects.filter(name='Client commande fictif').exists())
            with self.assertRaises(CommandError):
                call_command('import_clients', str(path), actor=self.tech.username, apply=True, stdout=StringIO())
