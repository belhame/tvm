from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.urls import include, path
from rest_framework.test import APIClient

from core.knowledge_models import KnowledgeChunk, RepairCase, TechnicalDocument
from core.knowledge_service import approved_cases, approved_chunks
from core.knowledge_storage import knowledge_path
from core.models import Client, Equipment, Intervention, ServiceRequest

urlpatterns = [path('api/knowledge/', include('core.knowledge_urls'))]
User = get_user_model()


@override_settings(ROOT_URLCONF=__name__, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class KnowledgeLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('knowledge-manager', role='manager')
        cls.tech = User.objects.create_user('knowledge-tech', role='technician')
        cls.other_tech = User.objects.create_user('knowledge-other', role='technician')
        cls.courier = User.objects.create_user('knowledge-courier', role='courier')
        cls.company = Client.objects.create(name='Centre source privé laboratoire', contact_name='Contact confidentiel', email='source@example.invalid')
        cls.customer = User.objects.create_user('knowledge-customer', role='client', client=cls.company)
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='SOURCE-PRIVATE-SERIAL', brand='Eaton', model='LAB-850')
        cls.request = ServiceRequest.objects.create(equipment=cls.equipment, subject='Symptôme privé non automatiquement ingéré', client_reference='SOURCE-PRIVATE-CALL')
        cls.intervention = Intervention.objects.create(service_request=cls.request, technician=cls.tech, status='completed', work_done='Données source non copiées', internal_notes='NEVER_AUTO_INGEST_PRIVATE')

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=Path(self.media.name)))
        self.api = APIClient()
        self.api.force_authenticate(self.tech)

    def upload(self, **overrides):
        payload = {'title': 'Procédure fictive de laboratoire', 'brand': 'Éaton', 'model': 'LAB-850',
                   'kind': 'procedure', 'file': SimpleUploadedFile('procedure.txt', b'F01 : verifier la tension et la carte de commande.\nCouper avant toute intervention.')}
        payload.update(overrides)
        return self.api.post('/api/knowledge/documents/', payload, format='multipart')

    def contribute(self, **overrides):
        payload = {'intervention': self.intervention.pk, 'symptoms': 'Alarme F01 et tension instable',
                   'fault_code': 'F01', 'measurements': 'Tension de sortie : 230 V',
                   'confirmed_cause': 'Connecteur de commande desserré confirmé par contrôle',
                   'repair': 'Reprise du connecteur et contrôle du serrage', 'outcome': 'Essai en charge stable sans alarme'}
        payload.update(overrides)
        return self.api.post('/api/knowledge/cases/', payload, format='json')

    def approve(self, path):
        self.api.force_authenticate(self.manager)
        return self.api.post(path + 'approve/', {}, format='json')

    def test_document_is_private_draft_until_human_approval(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['state'], 'draft')
        self.assertEqual(approved_chunks(brand='Eaton', model='LAB-850').count(), 0)
        document = TechnicalDocument.objects.get(pk=response.data['id'])
        self.assertRegex(document.stored_name, r'^knowledge/[a-f0-9]{32}\.txt$')
        self.assertTrue(knowledge_path(document.stored_name).exists())
        self.assertNotIn('stored_name', response.data)
        approved = self.approve(f'/api/knowledge/documents/{document.pk}/')
        self.assertEqual(approved.status_code, 200, approved.data)
        chunks = approved_chunks(brand=' EATON ', model='lab-850')
        self.assertGreater(chunks.count(), 0)
        self.assertEqual(approved_chunks(brand='Eaton', model='LAB-8500').count(), 0)

    def test_detail_excerpts_keep_page_ordinal_and_source_id(self):
        response = self.upload(file=SimpleUploadedFile('long.txt', ('Texte technique fictif. ' * 250).encode()))
        self.assertEqual(response.status_code, 201, response.data)
        detail = self.api.get(f'/api/knowledge/documents/{response.data["id"]}/').data
        self.assertGreater(len(detail['chunks']), 1)
        self.assertTrue(all(chunk['page'] == 1 for chunk in detail['chunks']))
        self.assertEqual(detail['chunks'][0]['source_id'], f'D{response.data["id"]}-P1-C1')
        self.assertEqual([chunk['ordinal'] for chunk in detail['chunks']], list(range(1, len(detail['chunks']) + 1)))

    def test_technician_cannot_approve_or_archive_and_no_update_delete_api(self):
        document = self.upload().data
        base = f'/api/knowledge/documents/{document["id"]}/'
        for action in ['approve/', 'archive/']:
            self.assertEqual(self.api.post(base + action, {}, format='json').status_code, 403)
        self.assertEqual(self.api.patch(base, {'title': 'Écrasé'}, format='json').status_code, 405)
        self.assertEqual(self.api.delete(base).status_code, 405)

    def test_archived_document_is_withdrawn_but_original_can_be_consulted(self):
        document = self.upload().data
        base = f'/api/knowledge/documents/{document["id"]}/'
        self.approve(base)
        self.assertGreater(approved_chunks(brand='Eaton', model='LAB-850').count(), 0)
        archived = self.api.post(base + 'archive/', {}, format='json')
        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertEqual(approved_chunks(brand='Eaton', model='LAB-850').count(), 0)
        self.assertEqual(self.api.get(base + 'download/').status_code, 200)
        self.assertEqual(self.api.post(base + 'approve/', {}, format='json').status_code, 400)

    def test_board_and_revision_retrieval_include_generic_and_exact_only(self):
        ids = []
        for board, revision in [('', ''), ('PCB-LAB', 'A'), ('PCB-LAB', 'B'), ('PCB-OTHER', 'A')]:
            self.api.force_authenticate(self.tech)
            document = self.upload(board_reference=board, revision=revision).data
            ids.append(document['id'])
            self.approve(f'/api/knowledge/documents/{document["id"]}/')
        chunks = approved_chunks(brand='Eaton', model='LAB-850', board_reference='pcb-lab', revision='a')
        self.assertEqual(set(chunks.values_list('document_id', flat=True)), {ids[0], ids[1]})

    def test_document_model_and_excerpts_cannot_be_rewritten_after_approval(self):
        document = self.upload().data
        self.approve(f'/api/knowledge/documents/{document["id"]}/')
        saved = TechnicalDocument.objects.get(pk=document['id'])
        saved.model = 'OTHER-MODEL'
        with self.assertRaises(ModelValidationError):
            saved.save()
        chunk = KnowledgeChunk.objects.filter(document=saved).first()
        chunk.text = 'Écrasement interdit'
        with self.assertRaises(ModelValidationError):
            chunk.save()

    @skipUnless(connection.vendor == 'postgresql', 'Protection réelle PostgreSQL')
    def test_database_protects_approved_document_and_excerpt_even_from_sql(self):
        document = self.upload().data
        self.approve(f'/api/knowledge/documents/{document["id"]}/')
        with self.assertRaises(DatabaseError), transaction.atomic():
            TechnicalDocument.objects.filter(pk=document['id']).update(title='Écrasement SQL interdit')
        with self.assertRaises(DatabaseError), transaction.atomic():
            KnowledgeChunk.objects.filter(document_id=document['id']).update(text='Écrasement SQL interdit')
        with self.assertRaises(DatabaseError), transaction.atomic():
            KnowledgeChunk.objects.bulk_create([KnowledgeChunk(document_id=document['id'], page=2, ordinal=1, text='Ajout tardif interdit')])

    def test_client_courier_and_anonymous_cannot_see_or_download_library(self):
        document = self.upload().data
        paths = ['/api/knowledge/documents/', f'/api/knowledge/documents/{document["id"]}/',
                 f'/api/knowledge/documents/{document["id"]}/download/', '/api/knowledge/cases/']
        for actor in [self.customer, self.courier, None]:
            self.api.force_authenticate(actor)
            for path in paths:
                self.assertEqual(self.api.get(path).status_code, 403)

    def test_unsupported_files_invalid_utf8_and_malformed_pdf_are_rejected(self):
        for name, data in [('photo.png', b'fake'), ('bad.txt', b'\xff\xfe\0'), ('fake.pdf', b'not a pdf')]:
            response = self.upload(file=SimpleUploadedFile(name, data))
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(TechnicalDocument.objects.count(), 0)
        self.assertFalse(list(Path(self.media.name).rglob('*.*')))

    def test_upload_fields_and_filters_are_bounded_and_strict(self):
        for fields in [{'model': ''}, {'brand': 'x' * 101}, {'model': '\x00'}, {'owner': 'other'}, {'brand': '\ufdfa' * 100}]:
            response = self.upload(**fields)
            self.assertEqual(response.status_code, 400, response.data)
        for query in ['?q=' + 'x' * 201, '?state=not-a-state', '?owner=other', '?q=%00', '?model=a&model=b']:
            self.assertEqual(self.api.get('/api/knowledge/documents/' + query).status_code, 400)

    def test_approval_requires_empty_payload_and_csrf(self):
        document = self.upload().data
        base = f'/api/knowledge/documents/{document["id"]}/approve/'
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.post(base, {'state': 'approved'}, format='json').status_code, 400)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.manager)
        self.assertEqual(client.post(base, {}, format='json').status_code, 403)

    def test_contribution_is_explicit_draft_and_does_not_copy_notes(self):
        self.assertEqual(RepairCase.objects.count(), 0)
        response = self.contribute()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data['brand'], response.data['model']), ('Eaton', 'LAB-850'))
        self.assertEqual(response.data['state'], 'draft')
        self.assertFalse(response.data['eligible_for_retrieval'])
        self.assertNotIn('NEVER_AUTO_INGEST_PRIVATE', str(response.data))
        self.assertNotIn(self.company.name, str(response.data))
        self.assertEqual(approved_cases(brand='Eaton', model='LAB-850').count(), 0)
        approved = self.approve(f'/api/knowledge/cases/{response.data["id"]}/')
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertTrue(approved.data['eligible_for_retrieval'])
        self.assertEqual(approved_cases(brand='Eaton', model='LAB-850').count(), 1)

    def test_only_own_completed_intervention_can_be_contributed_by_technician(self):
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.contribute().status_code, 403)
        self.api.force_authenticate(self.tech)
        Intervention.objects.filter(pk=self.intervention.pk).update(status='in_progress')
        self.assertEqual(self.contribute().status_code, 400)
        self.assertEqual(RepairCase.objects.count(), 0)

    def test_reopened_intervention_withdraws_approved_case_at_runtime(self):
        case = self.contribute().data
        self.approve(f'/api/knowledge/cases/{case["id"]}/')
        Intervention.objects.filter(pk=self.intervention.pk).update(status='in_progress')
        self.assertEqual(approved_cases(brand='Eaton', model='LAB-850').count(), 0)
        self.assertFalse(self.api.get(f'/api/knowledge/cases/{case["id"]}/').data['eligible_for_retrieval'])

    def test_changed_source_model_withdraws_case_without_rewriting_snapshot(self):
        case = self.contribute().data
        self.approve(f'/api/knowledge/cases/{case["id"]}/')
        Equipment.objects.filter(pk=self.equipment.pk).update(model='LAB-OTHER')
        self.assertEqual(approved_cases(brand='Eaton', model='LAB-850').count(), 0)
        saved = RepairCase.objects.get(pk=case['id'])
        self.assertEqual(saved.model, 'LAB-850')

    def test_case_pii_and_source_identifiers_are_rejected_including_revision(self):
        for fields in [{'symptoms': 'Envoyer contact@example.invalid'}, {'measurements': 'Appelez +33 6 12 34 56 78'},
                       {'repair': 'Dossier SOURCE-PRIVATE-CALL'}, {'outcome': 'SOURCE-PRIVATE-SERIAL'},
                       {'revision': 'source@example.invalid'}, {'confirmed_cause': self.company.name}]:
            with self.subTest(fields=fields):
                response = self.contribute(**fields)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(RepairCase.objects.count(), 0)

    def test_case_input_rejects_nontechnical_extra_fields_and_invalid_types(self):
        for fields in [{'brand': 'Other'}, {'client': self.company.pk}, {'intervention': True}, {'intervention': 1.1}, {'symptoms': 123}, {'outcome': ''}]:
            self.assertEqual(self.contribute(**fields).status_code, 400)


@skipUnless(connection.vendor == 'postgresql', 'Verrouillage PostgreSQL réel')
class KnowledgeApprovalConcurrencyTests(TransactionTestCase):
    def test_excerpt_insert_waits_for_non_key_approval_update_then_is_rejected(self):
        actor = User.objects.create_user('knowledge-concurrent-manager', role='manager')
        document = TechnicalDocument.objects.create(
            title='Source fictive simultanée', brand='Eaton', model='LAB-CONCURRENT', kind='procedure',
            stored_name='knowledge/' + 'a' * 32 + '.txt', original_name='synthetic.txt', mime_type='text/plain',
            size_bytes=4, sha256='b' * 64, pages=1, text_status='extracted', created_by=actor,
            created_by_label=actor.username,
        )
        updated = Event()
        attempted = Event()
        reader_finished = Event()

        def approve_without_explicit_row_lock():
            try:
                with transaction.atomic():
                    # This ordinary UPDATE obtains NO KEY UPDATE, not the
                    # stronger FOR UPDATE lock used by our approval service.
                    TechnicalDocument.objects.filter(pk=document.pk).update(
                        state='approved', approved_at=timezone.now(), approved_by=actor,
                        approved_by_label=actor.username,
                    )
                    updated.set()
                    if not attempted.wait(5):
                        raise RuntimeError('Concurrent insert did not start')
                    prematurely_finished = reader_finished.wait(.4)
                return prematurely_finished
            finally:
                connections.close_all()

        def insert_excerpt():
            try:
                if not updated.wait(5):
                    raise RuntimeError('Concurrent approval did not start')
                attempted.set()
                try:
                    with transaction.atomic():
                        KnowledgeChunk.objects.bulk_create([KnowledgeChunk(document_id=document.pk, page=1, ordinal=1, text='Ajout tardif fictif')])
                    return 'created'
                except DatabaseError:
                    return 'rejected'
                finally:
                    reader_finished.set()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(approve_without_explicit_row_lock)
            insertion = pool.submit(insert_excerpt)
            self.assertFalse(approval.result(timeout=15))
            self.assertEqual(insertion.result(timeout=15), 'rejected')
        self.assertEqual(KnowledgeChunk.objects.filter(document=document).count(), 0)
