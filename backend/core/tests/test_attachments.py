from io import BytesIO, StringIO
import hashlib
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client as BrowserClient, TestCase, TransactionTestCase, override_settings
from PIL import Image
from pypdf import PdfWriter
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.attachment_models import RequestAttachment
from core.attachment_service import create_document
from core.attachment_storage import private_path
from core.attachment_validation import MAX_FILE_SIZE, check_attachment, safe_original_name
from core.models import Client, Equipment, OperationEvent, ServiceRequest
from core.request_assignment import confirm_assignment


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (3, 3), color='#1262ff').save(output, format='PNG')
    return output.getvalue()


def pdf_bytes(*, pages=1, encrypted=False):
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if encrypted:
        writer.encrypt('fictional-test-password')
    writer.write(output)
    return output.getvalue()


def office_bytes(extension='docx', *, malicious=None):
    main, content_type, xml = (
        ('word/document.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        if extension == 'docx' else
        ('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>')
    )
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{main}" ContentType="{content_type}"/></Types>')
        archive.writestr(main, xml)
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        if malicious == 'macro':
            archive.writestr('word/vbaProject.bin', b'not-a-real-macro')
        if malicious == 'traversal':
            archive.writestr('../outside.txt', b'outside')
        if malicious == 'bomb':
            archive.writestr('xl/huge.xml', b'A' * (2 * 1024 * 1024))
    return output.getvalue()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Client documents fictif')
        cls.other_company = Client.objects.create(name='Autre client documents')
        cls.admin = User.objects.create_user('documents-admin', first_name='Auteur', last_name='Initial', role='admin', password='DocumentsTesting42!')
        cls.tech = User.objects.create_user('documents-tech', role='technician', password='DocumentsTesting42!')
        cls.other_tech = User.objects.create_user('documents-other-tech', role='technician', password='DocumentsTesting42!')
        cls.customer = User.objects.create_user('documents-client', role='client', client=cls.company, password='DocumentsTesting42!')
        cls.other_customer = User.objects.create_user('documents-other-client', role='client', client=cls.other_company, password='DocumentsTesting42!')
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='DOCS-FICTIONAL-001', model='Laboratoire')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='DOCS-FICTIONAL-002', model='Autre laboratoire')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Dossier documents', assigned_technician=cls.tech)
        # These existing document scenarios start after real technician acceptance.
        cls.request = confirm_assignment(cls.request.pk, actor=cls.tech, expected_revision=cls.request.assignment_revision, accept=True)
        cls.other_request = ServiceRequest.objects.create(equipment=cls.other_equipment, subject='Autre dossier')
        cls.unassigned = ServiceRequest.objects.create(equipment=cls.equipment, subject='Dossier non affecté')

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=Path(self.media.name)))
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.url = f'/api/requests/{self.request.pk}/documents/'

    def upload(self, *, name='photo.png', data=None, visible=None, request_id=None, **fields):
        payload = {'file': SimpleUploadedFile(name, image_bytes() if data is None else data, content_type='application/octet-stream'), **fields}
        if visible is not None:
            payload['client_visible'] = visible
        return self.api.post(f'/api/requests/{request_id or self.request.pk}/documents/', payload, format='multipart')

    def test_upload_is_private_by_default_and_metadata_is_frozen(self):
        data = image_bytes()
        response = self.upload(data=data, label='Photo de contrôle')
        self.assertEqual(response.status_code, 201, response.data)
        document = RequestAttachment.objects.get()
        self.assertFalse(document.client_visible)
        self.assertEqual(document.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(document.size_bytes, len(data))
        self.assertEqual(private_path(document.stored_name).read_bytes(), data)
        self.assertNotIn('photo.png', document.stored_name)
        self.assertEqual(private_path(document.stored_name).stat().st_mode & 0o777, 0o600)
        self.assertNotIn('stored_name', response.data)
        self.assertNotIn('media', response.data['download_url'])
        created_at = response.data['created_at']
        self.admin.first_name = 'Auteur modifié'
        self.admin.save(update_fields=['first_name'])
        listing = self.api.get(self.url).data
        self.assertEqual(listing['results'][0]['uploaded_by_name'], 'Auteur Initial')
        self.assertEqual(listing['results'][0]['created_at'], created_at)
        self.assertFalse(listing['virus_scanned'])
        event = OperationEvent.objects.get(kind='attachment_added')
        self.assertTrue(event.is_internal)
        self.assertIn('photo.png', event.summary)
        self.assertNotIn(document.sha256, event.summary)

    def test_real_pdf_and_office_formats_are_checked_read_only(self):
        files = [('report.pdf', pdf_bytes()), ('report.docx', office_bytes()), ('report.xlsx', office_bytes('xlsx')), ('notes.txt', 'Compte rendu UTF-8 échantillon'.encode())]
        for name, data in files:
            response = self.upload(name=name, data=data)
            self.assertEqual(response.status_code, 201, (name, response.data))
        self.assertEqual(RequestAttachment.objects.count(), 4)

    def test_declared_mime_is_not_trusted_and_download_is_attachment(self):
        created = self.upload()
        response = self.api.get(created.data['download_url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', response['Content-Security-Policy'])
        self.assertEqual(b''.join(response.streaming_content), image_bytes())

    def test_clients_only_see_shared_files_from_their_own_request(self):
        private = self.upload(name='private.png')
        shared = self.upload(name='shared.png', visible='true')
        foreign = self.upload(name='foreign.png', visible='true', request_id=self.other_request.pk)
        self.api.force_authenticate(self.customer)
        listing = self.api.get(self.url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item['id'] for item in listing.data['results']], [shared.data['id']])
        self.assertFalse(listing.data['can_upload'])
        self.assertFalse(listing.data['results'][0]['can_delete'])
        self.assertEqual(listing.data['results'][0]['uploaded_by_name'], 'Équipe SAV')
        for document in (private, foreign):
            self.assertEqual(self.api.get(document.data['download_url']).status_code, 404)
        self.assertEqual(self.api.get(f'/api/requests/{self.other_request.pk}/documents/').status_code, 404)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.api.delete(f'/api/documents/{shared.data["id"]}/').status_code, 403)
        timeline = self.api.get(f'/api/requests/{self.request.pk}/timeline/').data
        self.assertNotIn('private.png', str(timeline))
        self.assertIn('shared.png', str(timeline))

    def test_assigned_technician_can_write_but_other_technician_is_read_only(self):
        self.api.force_authenticate(self.tech)
        created = self.upload()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(self.upload(request_id=self.unassigned.pk).status_code, 403)
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.api.get(self.url).status_code, 200)
        self.assertFalse(self.api.get(self.url).data['can_upload'])
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.api.delete(f'/api/documents/{created.data["id"]}/').status_code, 403)

    def test_anonymous_cannot_list_upload_or_guess_download(self):
        created = self.upload()
        self.api.force_authenticate(None)
        for response in (self.api.get(self.url), self.upload(), self.api.get(created.data['download_url'])):
            self.assertIn(response.status_code, (401, 403))

    def test_visibility_is_strict_and_cannot_be_forged_by_unknown_fields(self):
        for visible in ('TRUE', '1', 'yes', ' true ', ''):
            response = self.upload(visible=visible)
            self.assertEqual(response.status_code, 400, (visible, response.data))
        for fields in ({'uploaded_by': str(self.tech.pk)}, {'created_at': '2000-01-01'}, {'stored_name': '../../outside'}):
            self.assertEqual(self.upload(**fields).status_code, 400)
        self.assertFalse(RequestAttachment.objects.exists())

    def test_format_mismatch_malformed_macro_and_unsafe_archives_are_rejected(self):
        cases = [
            ('fake.pdf', b'%PDF-1.7\nnot-a-real-pdf'), ('fake.png', b'not an image'),
            ('binary.txt', b'text\x00binary'), ('legacy.xls', b'legacy'),
            ('macro.docx', office_bytes(malicious='macro')),
            ('traversal.docx', office_bytes(malicious='traversal')),
            ('bomb.xlsx', office_bytes('xlsx', malicious='bomb')),
        ]
        for name, data in cases:
            response = self.upload(name=name, data=data)
            self.assertEqual(response.status_code, 400, (name, response.data))
        self.assertFalse(RequestAttachment.objects.exists())
        self.assertFalse(any(Path(self.media.name).rglob('*')))

    def test_encrypted_and_more_than_500_page_pdfs_are_rejected(self):
        for content in (pdf_bytes(encrypted=True), pdf_bytes(pages=501)):
            response = self.upload(name='restricted.pdf', data=content)
            self.assertEqual(response.status_code, 400, response.data)

    def test_pdf_worker_is_time_bounded_and_does_not_receive_environment_secrets(self):
        with patch('core.attachment_validation.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'{"valid": true, "page_count": 1}'
            response = self.upload(name='report.pdf', data=pdf_bytes())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertNotIn('DATABASE_URL', run.call_args.kwargs['env'])
        self.assertNotIn('DJANGO_SECRET_KEY', run.call_args.kwargs['env'])

    def test_actual_file_stream_over_10_mib_is_stopped_before_storage_service(self):
        content = b'A' * (MAX_FILE_SIZE + 1)
        with patch('core.attachment_views.create_document') as save:
            response = self.upload(name='oversize.txt', data=content)
        self.assertEqual(response.status_code, 413, response.content)
        save.assert_not_called()
        self.assertFalse(RequestAttachment.objects.exists())
        self.assertFalse(any(Path(self.media.name).rglob('*')))

    def test_oversize_body_is_rejected_before_authentication_or_parsing(self):
        self.api.force_authenticate(None)
        response = self.api.post(self.url, b'not parsed', content_type='multipart/form-data; boundary=x', CONTENT_LENGTH=str(11 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_csrf_required_for_real_session_and_valid_token_succeeds(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        token = browser.get('/api/session/').json()['csrfToken']
        response = browser.post(self.url, {'file': SimpleUploadedFile('photo.png', image_bytes())})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RequestAttachment.objects.exists())
        response = browser.post(self.url, {'file': SimpleUploadedFile('photo.png', image_bytes())}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201, response.content)
        document_id = response.json()['id']
        self.assertEqual(browser.delete(f'/api/documents/{document_id}/').status_code, 403)

    def test_oversize_stream_is_bounded_even_when_session_auth_reads_post_for_csrf(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        token = browser.get('/api/session/').json()['csrfToken']
        response = browser.post(
            self.url, {'file': SimpleUploadedFile('large.txt', b'A' * (MAX_FILE_SIZE + 1))},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 413, response.content)
        self.assertFalse(RequestAttachment.objects.exists())

    def test_upload_failure_rolls_back_metadata_event_and_private_file(self):
        before_events = OperationEvent.objects.count()
        with patch('core.attachment_service.append_event', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesMessage(RuntimeError, 'synthetic failure'):
                self.upload()
        self.assertFalse(RequestAttachment.objects.exists())
        self.assertEqual(OperationEvent.objects.count(), before_events)
        self.assertEqual([path for path in Path(self.media.name).rglob('*') if path.is_file()], [])

    def test_delete_retains_history_but_hides_and_removes_private_bytes(self):
        created = self.upload(visible='true')
        document = RequestAttachment.objects.get()
        stored = private_path(document.stored_name)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.delete(f'/api/documents/{document.pk}/')
        self.assertIn(response.status_code, (202, 204))
        document.refresh_from_db()
        self.assertIsNotNone(document.deleted_at)
        self.assertIsNotNone(document.storage_deleted_at)
        self.assertFalse(stored.exists())
        self.assertEqual(self.api.get(created.data['download_url']).status_code, 404)
        self.assertEqual(self.api.get(self.url).data['results'], [])
        self.assertEqual(OperationEvent.objects.filter(kind='attachment_added').count(), 1)
        self.assertEqual(OperationEvent.objects.filter(kind='attachment_deleted').count(), 1)

    def test_failed_delete_transaction_does_not_remove_file_or_visibility(self):
        self.upload()
        document = RequestAttachment.objects.get()
        with patch('core.attachment_service.append_event', side_effect=RuntimeError('synthetic deletion failure')):
            with self.assertRaises(RuntimeError):
                self.api.delete(f'/api/documents/{document.pk}/')
        document.refresh_from_db()
        self.assertIsNone(document.deleted_at)
        self.assertTrue(private_path(document.stored_name).exists())

    def test_storage_failure_is_pending_and_purge_command_can_resume(self):
        self.upload()
        document = RequestAttachment.objects.get()
        with patch('pathlib.Path.unlink', side_effect=PermissionError('synthetic disk error')):
            with self.assertLogs('core.attachment_service', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.api.delete(f'/api/documents/{document.pk}/')
        self.assertEqual(response.status_code, 202)
        document.refresh_from_db()
        self.assertIsNone(document.storage_deleted_at)
        self.assertEqual(self.api.get(self.url).data['results'], [])
        output = StringIO()
        call_command('purge_request_documents', stdout=output)
        document.refresh_from_db()
        self.assertIsNotNone(document.storage_deleted_at)
        self.assertFalse(private_path(document.stored_name).exists())

    def test_non_generated_paths_and_symlinks_never_disclose_outside_files(self):
        created = self.upload()
        document = RequestAttachment.objects.get()
        document.stored_name = '../../outside-secret.txt'
        document.save(update_fields=['stored_name'])
        self.assertEqual(self.api.get(created.data['download_url']).status_code, 404)

    def test_generated_filename_symlink_is_refused_without_reading_target(self):
        created = self.upload()
        document = RequestAttachment.objects.get()
        path = private_path(document.stored_name)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'outside.txt'
            target.write_text('OUTSIDE-FILE-MUST-STAY-PRIVATE', encoding='utf-8')
            path.unlink()
            path.symlink_to(target)
            response = self.api.get(created.data['download_url'])
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('OUTSIDE-FILE-MUST-STAY-PRIVATE', str(response.data))
            self.assertTrue(target.exists())

    def test_database_failure_after_unlink_remains_pending_and_recoverable(self):
        self.upload()
        document = RequestAttachment.objects.get()
        path = private_path(document.stored_name)
        with patch('django.db.models.query.QuerySet.update', side_effect=DatabaseError('synthetic post-commit failure')):
            with self.assertLogs('core.attachment_service', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.api.delete(f'/api/documents/{document.pk}/')
        self.assertEqual(response.status_code, 202)
        self.assertFalse(path.exists())
        document.refresh_from_db()
        self.assertIsNotNone(document.deleted_at)
        self.assertIsNone(document.storage_deleted_at)
        call_command('purge_request_documents', stdout=StringIO())
        document.refresh_from_db()
        self.assertIsNotNone(document.storage_deleted_at)

    def test_orphan_purge_keeps_active_and_recent_files(self):
        self.upload()
        document = RequestAttachment.objects.get()
        active = private_path(document.stored_name)
        parent = active.parent
        old = parent / ('a' * 32 + '.txt')
        recent = parent / ('b' * 32 + '.txt')
        unrelated = parent / 'unmanaged-user-file.txt'
        for path in (old, recent, unrelated):
            path.write_text('Fichier synthétique', encoding='utf-8')
        stale = time.time() - 25 * 3600
        os.utime(old, (stale, stale))
        os.utime(unrelated, (stale, stale))
        call_command('purge_request_documents', '--orphans', stdout=StringIO())
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(active.exists())
        self.assertTrue(unrelated.exists())

    def test_original_name_is_sanitized_without_publishing_storage_paths(self):
        name, extension = safe_original_name('../../folder\\unsafe\r\nname.pdf')
        self.assertEqual((name, extension), ('unsafename.pdf', 'pdf'))
        created = self.upload(name='../../document.png')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['original_name'], 'document.png')
        document = RequestAttachment.objects.get()
        public = self.api.get('/media/' + document.stored_name)
        self.assertNotEqual(public.get('Content-Type'), 'image/png')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AttachmentCommitTests(TransactionTestCase):
    def test_real_commit_returns_204_only_after_file_unlink(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory)):
            actor = get_user_model().objects.create_user('document-commit', role='admin')
            client = Client.objects.create(name='Client commit fictif')
            equipment = Equipment.objects.create(client=client, serial_number='DOC-COMMIT-FICTION', model='Laboratoire')
            request = ServiceRequest.objects.create(equipment=equipment, subject='Suppression réelle')
            document = create_document(service_request=request, uploaded=SimpleUploadedFile('photo.png', image_bytes()), label='', client_visible=False, actor=actor)
            path = private_path(document.stored_name)
            api = APIClient()
            api.force_authenticate(actor)
            response = api.delete(f'/api/documents/{document.pk}/')
            self.assertEqual(response.status_code, 204)
            self.assertFalse(path.exists())
            self.assertTrue(OperationEvent.objects.filter(kind='attachment_deleted').exists())
