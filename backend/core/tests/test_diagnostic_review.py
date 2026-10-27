"""Independent assistant/knowledge checks, with public fictional inputs only."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, ServiceRequest


AI_CONFIGURED = {'TVM_AI_ENABLED': True, 'TVM_AI_API_KEY': 'FIXTURE_ONLY_NOT_A_REAL_KEY',
                 'TVM_AI_MODEL': 'fixture-diagnostic-model', 'TVM_AI_TIMEOUT': 2}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentDiagnosticKnowledgeReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Diagnostic Fictif', email='private-diagnostic@example.invalid', phone='+22900000042', notes='PRIVATE_DIAGNOSTIC_CUSTOMER_NOTE')
        cls.admin = User.objects.create_user('diagnostic-review-admin', role='admin')
        cls.manager = User.objects.create_user('diagnostic-review-manager', role='manager')
        cls.tech = User.objects.create_user('diagnostic-review-tech', role='technician')
        cls.other_tech = User.objects.create_user('diagnostic-review-other-tech', role='technician')
        cls.courier = User.objects.create_user('diagnostic-review-courier', role='courier')
        cls.customer = User.objects.create_user('diagnostic-review-client', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='PRIVATE-DIAGNOSTIC-SERIAL-001', model='DIAG-LAB850F', brand='Eaton')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='PRIVATE_DIAGNOSTIC_REQUEST_SUBJECT', description='PRIVATE_DIAGNOSTIC_REQUEST_DESCRIPTION', assigned_technician=cls.tech, status='maintenance')
        cls.visit = Intervention.objects.create(service_request=cls.record, technician=cls.tech, status='completed', performed_on=timezone.localdate(), diagnosis='PRIVATE_DIAGNOSTIC_VISIT_TEXT', internal_notes='PRIVATE_DIAGNOSTIC_INTERNAL_NOTE')

    def setUp(self):
        self.storage = TemporaryDirectory(prefix='tvm-diagnostic-review-')
        self.addCleanup(self.storage.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=Path(self.storage.name))
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.api = APIClient()
        self.api.force_authenticate(self.tech)

    def document(self, *, model='DIAG-LAB850F', text='Contrôler la tension du bus. Examiner les diodes avant de remplacer la carte.', name='notice-fictive.txt', **changes):
        body = {'title': 'Notice de diagnostic fictive', 'brand': 'Eaton', 'model': model, 'kind': 'manual',
                'file': SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/plain')}
        body.update(changes)
        response = self.api.post('/api/knowledge/documents/', body, format='multipart')
        self.assertIn(response.status_code, (200, 201), response.json())
        return response.json()

    def case_body(self, **changes):
        body = {'intervention': self.visit.pk, 'symptoms': 'Arrêt lors du démarrage en charge.',
                'confirmed_cause': 'Diode de redressement défaillante après contrôle.',
                'repair': 'Remplacement de la diode et essais sur banc.',
                'outcome': 'Fonctionnement normal confirmé par les essais.'}
        body.update(changes)
        return body

    def approve_document(self, identifier):
        self.api.force_authenticate(self.manager)
        response = self.api.post(f'/api/knowledge/documents/{identifier}/approve/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()

    def analyze_body(self, **changes):
        from uuid import uuid4
        body = {'request_key': str(uuid4()), 'brand': 'Eaton', 'model': self.unit.model,
                'symptoms': 'Arrêt en charge avec tension du bus instable.',
                'fault_code': '', 'measurements': 'Diode à contrôler sur banc.'}
        body.update(changes)
        return body

    def provider_output(self, source_id):
        return {'output': {'summary': 'Contrôle technique à confirmer sur banc.',
            'hypotheses': [{'title': 'Défaillance possible d’une diode', 'explanation': 'Les symptômes justifient ce contrôle, sans cause certaine.', 'source_ids': [source_id]}],
            'checks': [{'instructions': 'Vérifier les diodes hors tension selon la procédure approuvée.', 'source_ids': [source_id]}],
            'missing_information': ['Valeur de tension du bus à relever.'],
            'uncertainties': ['Le schéma visuel reste à consulter manuellement.']},
            'usage': {'input_tokens': 10, 'output_tokens': 12}}

    def published_document(self, **changes):
        self.api.force_authenticate(self.tech)
        doc = self.document(**changes)
        self.approve_document(doc['id'])
        detail = self.api.get(f'/api/knowledge/documents/{doc["id"]}/').json()
        return doc, detail['chunks'][0]['source_id']

    def test_document_upload_is_private_draft_and_only_manager_can_publish(self):
        doc = self.document(name='../../notice-fictive.txt')
        self.assertEqual(doc['state'], 'draft')
        self.assertEqual(doc['text_status'], 'extracted')
        rejected = self.api.post(f'/api/knowledge/documents/{doc["id"]}/approve/', {}, format='json')
        self.assertEqual(rejected.status_code, 403, rejected.json())
        approved = self.approve_document(doc['id'])
        self.assertEqual(approved['state'], 'approved')
        detail = self.api.get(f'/api/knowledge/documents/{doc["id"]}/')
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertTrue(detail.json()['chunks'])
        self.assertTrue(all(row['source_id'].startswith(f'D{doc["id"]}-P') for row in detail.json()['chunks']))
        for private in ('stored_name', 'storage_path', str(self.storage.name), '/media/'):
            self.assertNotIn(private, str(detail.json()))
        files = [path for path in Path(self.storage.name).rglob('*') if path.is_file()]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, Path(self.storage.name) / 'knowledge')
        self.assertRegex(files[0].name, r'^[0-9a-f]{32}\.txt$')
        downloaded = self.api.get(f'/api/knowledge/documents/{doc["id"]}/download/')
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(downloaded.get('Content-Disposition', '').startswith('attachment;'))
        self.assertIn('no-store', downloaded.get('Cache-Control', ''))

    def test_clients_couriers_and_anonymous_cannot_read_documents_or_download_bytes(self):
        doc = self.document()
        for actor in (self.customer, self.courier, None):
            self.api.force_authenticate(actor)
            for path in ('/api/knowledge/documents/', f'/api/knowledge/documents/{doc["id"]}/', f'/api/knowledge/documents/{doc["id"]}/download/'):
                response = self.api.get(path)
                self.assertIn(response.status_code, (401, 403), response.content[:300])
                self.assertNotIn('Contrôler la tension du bus.', response.content.decode('utf-8', errors='replace'))

    def test_document_inputs_cannot_forge_approval_chunks_or_parsed_content(self):
        from core.knowledge_models import TechnicalDocument

        for field, value in (('state', 'approved'), ('text_status', 'extracted'), ('approved_by', self.admin.pk), ('chunks', 'FORGED_SOURCE'), ('stored_name', '../../forged.txt')):
            with self.subTest(field=field):
                body = {'title': 'Notice fictive', 'brand': 'Eaton', 'model': self.unit.model, 'kind': 'manual',
                        'file': SimpleUploadedFile('notice.txt', b'Texte technique fictif.', content_type='text/plain'), field: value}
                response = self.api.post('/api/knowledge/documents/', body, format='multipart')
                self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(TechnicalDocument.objects.exists())
        self.assertFalse(any(path.is_file() for path in Path(self.storage.name).rglob('*')))

    def test_malformed_or_oversized_uploads_do_not_create_sources_or_leave_files(self):
        from core.knowledge_models import TechnicalDocument

        for name, data in (('fake.pdf', b'%PDF-1.7\nThis is not a PDF.'), ('invalid.txt', b'\xff\xfe\x00'),
                           ('script.html', b'<script>alert(1)</script>'), ('large.txt', b'A' * (10 * 1024 * 1024 + 1))):
            with self.subTest(name=name):
                body = {'title': 'Source fictive invalide', 'brand': 'Eaton', 'model': self.unit.model, 'kind': 'manual',
                        'file': SimpleUploadedFile(name, data, content_type='application/octet-stream')}
                response = self.api.post('/api/knowledge/documents/', body, format='multipart')
                self.assertIn(response.status_code, (400, 413), response.json())
                self.assertFalse(TechnicalDocument.objects.exists())
        self.assertFalse(any(path.is_file() for path in Path(self.storage.name).rglob('*')))

    def test_failed_chunk_write_rolls_back_document_and_removes_its_uploaded_bytes(self):
        from core.knowledge_models import TechnicalDocument

        with patch('core.knowledge_service.KnowledgeChunk.objects.bulk_create', side_effect=RuntimeError('Synthetic chunk storage failure')):
            with self.assertRaises(RuntimeError):
                self.document()
        self.assertFalse(TechnicalDocument.objects.exists())
        self.assertFalse(any(path.is_file() for path in Path(self.storage.name).rglob('*')))

    def test_retrieval_excludes_draft_archived_and_other_models_without_fuzzy_fallback(self):
        from core.knowledge_service import approved_chunks

        approved = self.document(text='APPROVED_EXACT_MODEL: contrôler les diodes du bus.')
        draft = self.document(text='PRIVATE_DRAFT_CONTENT: information non approuvée.')
        other = self.document(model='DIAG-LAB850F-OTHER', text='PRIVATE_OTHER_MODEL: procédure incompatible.')
        archived = self.document(text='PRIVATE_ARCHIVED_CONTENT: procédure abandonnée.')
        for doc in (approved, other, archived):
            self.approve_document(doc['id'])
        response = self.api.post(f'/api/knowledge/documents/{archived["id"]}/archive/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        result = list(approved_chunks(brand='eaton', model=self.unit.model))
        self.assertTrue(result)
        self.assertEqual({row.document_id for row in result}, {approved['id']})
        serialized = '\n'.join(row.text for row in result)
        self.assertIn('APPROVED_EXACT_MODEL', serialized)
        for private in ('PRIVATE_DRAFT_CONTENT', 'PRIVATE_OTHER_MODEL', 'PRIVATE_ARCHIVED_CONTENT'):
            self.assertNotIn(private, serialized)
        self.assertEqual(list(approved_chunks(brand='Eaton', model='DIAG-LAB850')), [])
        self.assertEqual(self.api.patch(f'/api/knowledge/documents/{approved["id"]}/', {'model': 'FORGED'}, format='json').status_code, 405)
        self.assertEqual(self.api.delete(f'/api/knowledge/documents/{approved["id"]}/').status_code, 405)

    def test_case_creation_requires_completed_source_and_its_technician_or_manager(self):
        from core.knowledge_models import RepairCase

        Intervention.objects.filter(pk=self.visit.pk).update(status='in_progress', completed_at=None)
        rejected = self.api.post('/api/knowledge/cases/', self.case_body(), format='json')
        self.assertEqual(rejected.status_code, 400, rejected.json())
        self.assertFalse(RepairCase.objects.exists())
        Intervention.objects.filter(pk=self.visit.pk).update(status='completed', completed_at=timezone.now())
        self.api.force_authenticate(self.other_tech)
        rejected = self.api.post('/api/knowledge/cases/', self.case_body(), format='json')
        self.assertIn(rejected.status_code, (403, 404), rejected.json())
        self.assertFalse(RepairCase.objects.exists())
        self.api.force_authenticate(self.tech)
        created = self.api.post('/api/knowledge/cases/', self.case_body(), format='json')
        self.assertIn(created.status_code, (200, 201), created.json())
        self.assertEqual(created.json()['state'], 'draft')
        self.assertNotIn(self.company.email, str(created.json()))
        self.assertNotIn(self.unit.serial_number, str(created.json()))
        self.assertNotIn(self.visit.internal_notes, str(created.json()))

    def test_case_fields_cannot_contain_customer_contact_or_forge_source_model(self):
        from core.knowledge_models import RepairCase

        for changes in ({'symptoms': f'Appeler {self.company.email}.'},
                        {'measurements': f'Contact : {self.company.phone}.'},
                        {'confirmed_cause': f'Panne sur {self.unit.serial_number}.'},
                        {'revision': self.company.email},
                        {'brand': 'FORGED'}, {'state': 'approved'}, {'approved_by': self.admin.pk}):
            with self.subTest(changes=changes):
                response = self.api.post('/api/knowledge/cases/', self.case_body(**changes), format='json')
                self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(RepairCase.objects.exists())

    def test_approved_case_becomes_ineligible_if_its_intervention_is_no_longer_completed(self):
        from core.knowledge_service import approved_cases

        created = self.api.post('/api/knowledge/cases/', self.case_body(), format='json')
        self.assertIn(created.status_code, (200, 201), created.json())
        identifier = created.json()['id']
        self.api.force_authenticate(self.manager)
        approved = self.api.post(f'/api/knowledge/cases/{identifier}/approve/', {}, format='json')
        self.assertEqual(approved.status_code, 200, approved.json())
        self.assertTrue(list(approved_cases(brand='Eaton', model=self.unit.model)))
        self.assertEqual(list(approved_cases(brand='Eaton', model='DIAG-LAB850F-OTHER')), [])
        Intervention.objects.filter(pk=self.visit.pk).update(status='testing', completed_at=None)
        self.assertEqual(list(approved_cases(brand='Eaton', model=self.unit.model)), [])
        detail = self.api.get(f'/api/knowledge/cases/{identifier}/')
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertFalse(detail.json()['eligible_for_retrieval'])
        for actor in (self.customer, self.courier, None):
            self.api.force_authenticate(actor)
            for path in ('/api/knowledge/cases/', f'/api/knowledge/cases/{identifier}/'):
                self.assertIn(self.api.get(path).status_code, (401, 403))

    @override_settings(TVM_AI_ENABLED=False, TVM_AI_API_KEY='')
    def test_disabled_assistant_never_calls_provider_or_fabricates_a_diagnostic(self):
        self.published_document()
        with patch('core.diagnostic_service.call_provider') as provider, patch('socket.socket.connect', side_effect=AssertionError('No external network expected.')):
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'requires_configuration')
        self.assertIsNone(response.json()['output'])
        provider.assert_not_called()

    @override_settings(**AI_CONFIGURED)
    def test_no_approved_relevant_source_abstains_without_provider_call(self):
        self.document(text='PRIVATE_DRAFT_ONLY: tension du bus et contrôle de diode.')
        self.published_document(model='DIAG-LAB850F-OTHER', text='PRIVATE_WRONG_MODEL_ONLY: tension du bus et contrôle de diode.')
        with patch('core.diagnostic_service.call_provider') as provider:
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'abstained')
        self.assertIsNone(response.json()['output'])
        provider.assert_not_called()

    @override_settings(**AI_CONFIGURED)
    def test_provider_receives_only_approved_model_sources_without_business_private_fields(self):
        doc, citation = self.published_document(text='APPROVED_BUS_DIODE: contrôler tension du bus et diode avant remplacement.')
        self.api.force_authenticate(self.tech)
        self.document(text='PRIVATE_DRAFT_NOT_FOR_PROVIDER: tension bus diode.')
        self.published_document(model='DIAG-LAB850F-OTHER', text='PRIVATE_OTHER_MODEL_NOT_FOR_PROVIDER: tension bus diode.')
        with patch('core.diagnostic_service.call_provider', return_value=self.provider_output(citation)) as provider:
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(service_request=self.record.pk), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'completed')
        self.assertIsNotNone(response.json()['output'])
        self.assertEqual(provider.call_count, 1)
        context = str(provider.call_args.args) + str(provider.call_args.kwargs)
        self.assertIn(citation, context)
        self.assertIn('APPROVED_BUS_DIODE', context)
        for private in (self.company.name, self.company.email, self.company.phone, self.company.notes,
                        self.unit.serial_number, self.record.reference, self.record.subject,
                        self.record.description, self.visit.internal_notes,
                        'PRIVATE_DRAFT_NOT_FOR_PROVIDER', 'PRIVATE_OTHER_MODEL_NOT_FOR_PROVIDER'):
            self.assertNotIn(private, context)

    @override_settings(**AI_CONFIGURED)
    def test_source_metadata_is_redacted_before_it_can_reach_the_provider(self):
        _, citation = self.published_document(revision=self.company.email, board_reference=self.company.phone)
        with patch('core.diagnostic_service.call_provider', return_value=self.provider_output(citation)) as provider:
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(service_request=self.record.pk), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'completed')
        context = str(provider.call_args.args) + str(provider.call_args.kwargs)
        self.assertNotIn(self.company.email, context)
        self.assertNotIn(self.company.phone, context)
        self.assertNotIn(self.company.email, str(response.json()))
        self.assertNotIn(self.company.phone, str(response.json()))

    @override_settings(**AI_CONFIGURED)
    def test_specific_procedure_of_another_revision_is_not_a_generic_manual_fallback(self):
        self.published_document(kind='procedure', revision='REV-B', text='BUS_REVISION_B_ONLY: tension bus diode.')
        with patch('core.diagnostic_service.call_provider') as provider:
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(revision='REV-A'), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'abstained')
        self.assertIsNone(response.json()['output'])
        provider.assert_not_called()

    @override_settings(**AI_CONFIGURED)
    def test_unrecognized_citations_or_extra_provider_fields_never_become_valid_output(self):
        _, citation = self.published_document()
        invalid = self.provider_output(citation)
        invalid['output']['hypotheses'][0]['source_ids'] = ['D999999-P1-C1']
        extras = self.provider_output(citation)
        extras['output']['automatic_repair_authorized'] = True
        invalid_unicode = self.provider_output(citation)
        invalid_unicode['output']['summary'] = '\ud800'
        missing_citation = self.provider_output(citation)
        missing_citation['output']['checks'][0]['source_ids'] = []
        fake_confidence = self.provider_output(citation)
        fake_confidence['output']['summary'] = 'Confiance de 99 % sur cette cause.'
        for payload in (invalid, extras, invalid_unicode, missing_citation, fake_confidence,
                        {'output': 'RAW_PRIVATE_PROVIDER_TEXT', 'usage': {}}):
            with self.subTest(payload=payload), patch('core.diagnostic_service.call_provider', return_value=payload):
                response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
                self.assertEqual(response.status_code, 200, response.json())
                self.assertEqual(response.json()['status'], 'invalid_response')
                self.assertIsNone(response.json()['output'])
                self.assertNotIn('RAW_PRIVATE_PROVIDER_TEXT', str(response.json()))

    @override_settings(**AI_CONFIGURED)
    def test_archiving_source_during_provider_call_invalidates_the_whole_result(self):
        doc, citation = self.published_document()

        def archive_while_generating(*args, **kwargs):
            from core.knowledge_models import TechnicalDocument
            TechnicalDocument.objects.filter(pk=doc['id']).update(state='archived', archived_at=timezone.now())
            return self.provider_output(citation)

        with patch('core.diagnostic_service.call_provider', side_effect=archive_while_generating):
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'sources_changed')
        self.assertIsNone(response.json()['output'])

    @override_settings(**AI_CONFIGURED)
    def test_provider_exception_is_normalized_without_raw_error_or_fake_output(self):
        self.published_document()
        with patch('core.diagnostic_service.call_provider', side_effect=RuntimeError('PRIVATE_PROVIDER_TOKEN_RESPONSE_BODY')):
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'provider_error')
        self.assertIsNone(response.json()['output'])
        self.assertNotIn('PRIVATE_PROVIDER_TOKEN_RESPONSE_BODY', str(response.json()))

    @override_settings(**AI_CONFIGURED)
    def test_case_with_intervention_reopened_during_provider_call_cannot_support_a_diagnostic(self):
        self.api.force_authenticate(self.tech)
        created = self.api.post('/api/knowledge/cases/', self.case_body(), format='json')
        self.assertIn(created.status_code, (200, 201), created.json())
        identifier = created.json()['id']
        self.api.force_authenticate(self.manager)
        approved = self.api.post(f'/api/knowledge/cases/{identifier}/approve/', {}, format='json')
        self.assertEqual(approved.status_code, 200, approved.json())

        def reopen_while_generating(*args, **kwargs):
            context = str(args) + str(kwargs)
            self.assertIn(f'R{identifier}', context)
            for private in (self.company.name, self.company.email, self.unit.serial_number,
                            self.record.reference, self.visit.reference, self.visit.internal_notes):
                self.assertNotIn(private, context)
            Intervention.objects.filter(pk=self.visit.pk).update(status='testing', completed_at=None)
            return self.provider_output(f'R{identifier}')

        with patch('core.diagnostic_service.call_provider', side_effect=reopen_while_generating):
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['status'], 'sources_changed')
        self.assertIsNone(response.json()['output'])

    @override_settings(**AI_CONFIGURED)
    def test_diagnostic_history_and_analysis_are_internal_and_technician_history_is_own_only(self):
        self.published_document()
        self.api.force_authenticate(self.tech)
        with patch('core.diagnostic_service.call_provider', return_value=None):
            created = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
        self.assertEqual(created.status_code, 200, created.json())
        identifier = created.json()['id']
        for actor in (self.customer, self.courier, None):
            self.api.force_authenticate(actor)
            for path in ('/api/diagnostics/runs/', f'/api/diagnostics/runs/{identifier}/'):
                self.assertIn(self.api.get(path).status_code, (401, 403))
            response = self.api.post('/api/diagnostics/analyze/', self.analyze_body(), format='json')
            self.assertIn(response.status_code, (401, 403))
        self.api.force_authenticate(self.other_tech)
        self.assertEqual(self.api.get(f'/api/diagnostics/runs/{identifier}/').status_code, 404)
        self.assertEqual(self.api.get('/api/diagnostics/runs/').json()['results'], [])
