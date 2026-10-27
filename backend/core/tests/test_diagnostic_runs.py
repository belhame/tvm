"""Persisted idempotency and PostgreSQL admission bounds, with mocked network."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import Throttled

from core.diagnostic_models import DiagnosticRun
from core.diagnostic_service import DiagnosticConflict, analyze
from core.knowledge_models import KnowledgeChunk, TechnicalDocument
from core.models import User


def fixture(suffix='', *, model='FICTIF-9', board_reference=''):
    actor = User.objects.create_user(f'diagnostic-run{suffix}', role='technician')
    document = TechnicalDocument.objects.create(title='Manuel fictif de ventilation', brand='Eaton', model=model, board_reference=board_reference, kind='manual',
        stored_name=f'{uuid4()}.txt', original_name='manuel-fictif.txt', mime_type='text/plain', size_bytes=100,
        sha256='0'*64, pages=1, text_status='extracted', created_by=actor, created_by_label='Technicien fictif')
    KnowledgeChunk.objects.create(document=document, page=1, ordinal=1, text='Alarme ventilation F17 : contrôler le ventilateur hors tension après consignation.')
    document.state, document.approved_by, document.approved_by_label, document.approved_at = 'approved', actor, 'Responsable fictif', timezone.now()
    document.save()
    return actor, document


def payload():
    return {'request_key': uuid4(), 'model': 'FICTIF-9', 'brand': 'Eaton', 'symptoms': 'alarme ventilation', 'fault_code': 'F17',
            'measurements': '', 'board_reference': '', 'revision': ''}


def provider_result(technical, sources):
    return {'output': {'summary': 'Contrôle à valider.',
        'hypotheses': [{'title': 'Ventilation', 'explanation': 'Le manuel documente cette alarme.', 'source_ids': [sources[0]['id']]}],
        'checks': [{'instructions': 'Hors tension après consignation, consulter la procédure du ventilateur.', 'source_ids': [sources[0]['id']]}],
        'missing_information': [], 'uncertainties': ['Référence exacte à confirmer.']}, 'usage': {'input_tokens': 20, 'output_tokens': 30}}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TVM_AI_ENABLED=True,
    TVM_AI_API_KEY='synthetic-secret-key', TVM_AI_MODEL='gpt-4.1-mini')
class DiagnosticRunTests(TestCase):
    def setUp(self):
        self.actor, self.document = fixture()

    def test_actor_uuid_is_idempotent_and_changed_payload_cannot_reuse_it(self):
        data = payload()
        with patch('core.diagnostic_service.call_provider', side_effect=provider_result) as provider:
            first = analyze(self.actor, data)
            second = analyze(self.actor, data)
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(first.status, 'completed')
            provider.assert_called_once()
            with self.assertRaises(DiagnosticConflict):
                analyze(self.actor, {**data, 'symptoms': 'Autres symptômes'})

    def test_ten_requests_per_hour_cap_is_database_backed_even_without_provider(self):
        with override_settings(TVM_AI_ENABLED=False), patch('core.diagnostic_service.call_provider') as provider:
            for _ in range(10):
                self.assertEqual(analyze(self.actor, payload()).status, 'requires_configuration')
            with self.assertRaises(Throttled):
                analyze(self.actor, payload())
        provider.assert_not_called()
        self.assertEqual(DiagnosticRun.objects.count(), 10)

    def test_invalid_model_configuration_is_reported_without_database_or_provider_error(self):
        with override_settings(TVM_AI_MODEL='x'*101), patch('core.diagnostic_service.call_provider') as provider:
            run = analyze(self.actor, payload())
        provider.assert_not_called()
        self.assertEqual(run.status, 'requires_configuration')
        self.assertEqual(run.provider_model, '')

    def test_long_numeric_model_and_board_reference_keep_exact_lookup_identity(self):
        model, board = 'LAB-IA-1782456789012-TEST', '461234567890123'
        actor, _ = fixture('numeric', model=model, board_reference=board)
        data = {**payload(), 'model': model, 'board_reference': board}
        with patch('core.diagnostic_service.call_provider', side_effect=provider_result) as provider:
            run = analyze(actor, data)
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.technical_input['model'], model)
        self.assertEqual(run.technical_input['board_reference'], board)
        self.assertEqual(provider.call_args.args[1][0]['board_reference'], board)


@skipUnless(connection.vendor == 'postgresql', 'Concurrency requires real PostgreSQL connections.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TVM_AI_ENABLED=True,
    TVM_AI_API_KEY='synthetic-secret-key', TVM_AI_MODEL='gpt-4.1-mini')
class DiagnosticAdmissionConcurrencyTests(TransactionTestCase):
    def test_same_uuid_two_connections_calls_provider_once(self):
        actor, _ = fixture('concurrent')
        data = payload()
        barrier = Barrier(2)
        def work():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return analyze(User.objects.get(pk=actor.pk), data).pk
            finally:
                connections.close_all()
        with patch('core.diagnostic_service.call_provider', side_effect=provider_result) as provider, ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(identifiers[0], identifiers[1])
        provider.assert_called_once()
        self.assertEqual(DiagnosticRun.objects.count(), 1)

    def test_second_uuid_from_same_actor_is_throttled_while_provider_is_running(self):
        actor, _ = fixture('bounded')
        entered, release = Event(), Event()
        def slow(technical, sources):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Synthetic provider release timeout')
            return provider_result(technical, sources)
        def work():
            close_old_connections()
            try:
                return analyze(User.objects.get(pk=actor.pk), payload()).pk
            finally:
                connections.close_all()
        with patch('core.diagnostic_service.call_provider', side_effect=slow), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaises(Throttled):
                    analyze(actor, payload())
            finally:
                release.set()
            future.result(timeout=15)

    def test_two_global_slots_prevent_third_actor_from_starting_provider(self):
        actors = [fixture(f'global-{index}')[0] for index in range(3)]
        entered = Barrier(3)
        release = Event()
        def slow(technical, sources):
            entered.wait(timeout=10)
            if not release.wait(10):
                raise AssertionError('Synthetic provider release timeout')
            return provider_result(technical, sources)
        def work(identifier):
            close_old_connections()
            try:
                return analyze(User.objects.get(pk=identifier), payload()).pk
            finally:
                connections.close_all()
        with patch('core.diagnostic_service.call_provider', side_effect=slow) as provider, ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(work, actor.pk) for actor in actors[:2]]
            try:
                entered.wait(timeout=10)
                with self.assertRaises(Throttled):
                    analyze(actors[2], payload())
            finally:
                release.set()
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(provider.call_count, 2)
