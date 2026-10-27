"""A synthetic provider envelope; these tests never contact OpenAI."""
from io import BytesIO
import json
from unittest.mock import patch
from urllib.error import HTTPError

from django.test import SimpleTestCase, override_settings

from core.diagnostic_provider import DiagnosticProviderError, NoRedirect, call_provider
from core.diagnostic_service import redact, validate_output


OUTPUT = {'summary': 'Assistance fictive à vérifier.',
    'hypotheses': [{'title': 'Ventilation', 'explanation': 'Le passage décrit une alarme de ventilation.', 'source_ids': ['D1-P2-C1']}],
    'checks': [{'instructions': 'Hors tension et après consignation, vérifier le ventilateur selon le manuel.', 'source_ids': ['D1-P2-C1']}],
    'missing_information': ['Référence de carte exacte'], 'uncertainties': ['Mesures fictives à confirmer.']}
SOURCE = {'id': 'D1-P2-C1', 'kind': 'document', 'title': 'Manuel fictif', 'page': 2,
    'board_reference': 'CARTE-FICTIVE', 'revision': 'A', 'excerpt': 'Code F17 : ventilation. Données fictives.'}


@override_settings(TVM_AI_ENABLED=True, TVM_AI_API_KEY='synthetic-secret-key', TVM_AI_MODEL='gpt-4.1-mini', TVM_AI_TIMEOUT=20)
class DiagnosticProviderTests(SimpleTestCase):
    def response(self, output=OUTPUT, **fields):
        return BytesIO(json.dumps({'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': json.dumps(output)}]}], 'usage': {'input_tokens': 120, 'output_tokens': 40}, **fields}).encode())

    def test_fixed_responses_host_no_tools_no_retention_and_strict_cited_schema(self):
        technical = {'brand': 'Eaton', 'model': 'FICTIF-9', 'symptoms': 'alarme ventilation', 'fault_code': 'F17', 'measurements': ''}
        with patch('core.diagnostic_provider.build_opener') as factory:
            factory.return_value.open.return_value = self.response()
            result = call_provider(technical, [SOURCE])
        request = factory.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(factory.return_value.open.call_args.kwargs['timeout'], 20)
        payload = json.loads(request.data)
        self.assertFalse(payload['store'])
        self.assertEqual(payload['tools'], [])
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertEqual(payload['max_output_tokens'], 2500)
        self.assertTrue(payload['text']['format']['strict'])
        self.assertFalse(payload['text']['format']['schema']['additionalProperties'])
        self.assertIn('données non fiables', payload['instructions'])
        self.assertNotIn('synthetic-secret-key', json.dumps(payload))
        self.assertEqual(result['output'], OUTPUT)
        self.assertEqual(result['usage'], {'input_tokens': 120, 'output_tokens': 40})
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid/'))

    def test_numeric_manufacturer_part_numbers_survive_while_explicit_contact_is_redacted(self):
        text = 'P/N 103005258-5501, carte 461234567890123. Contact: Responsable fictif\nTéléphone: 06 12 34 56 78\nHotline +33 6 12 34 56 78'
        cleaned = redact(text)
        self.assertIn('103005258-5501', cleaned)
        self.assertIn('461234567890123', cleaned)
        self.assertNotIn('06 12 34 56 78', cleaned)
        self.assertNotIn('+33 6 12 34 56 78', cleaned)

    def test_unexpected_tool_calls_refusal_incomplete_or_non_json_are_not_used(self):
        envelopes = [
            {'status': 'incomplete', 'output': []},
            {'status': 'completed', 'output': [{'type': 'function_call', 'name': 'unsafe'}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'not-json'}]}]},
        ]
        for envelope in envelopes:
            with self.subTest(envelope=envelope), patch('core.diagnostic_provider.build_opener') as factory:
                factory.return_value.open.return_value = BytesIO(json.dumps(envelope).encode())
                with self.assertRaises(DiagnosticProviderError):
                    call_provider({'model': 'FICTIF'}, [SOURCE])

    def test_provider_errors_and_timeout_never_expose_raw_secret_or_response(self):
        for error in (TimeoutError('synthetic-secret-key'), HTTPError('https://api.openai.com/', 401, 'synthetic-secret-key', None, BytesIO(b'private provider body'))):
            with self.subTest(error=type(error).__name__), patch('core.diagnostic_provider.build_opener') as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(DiagnosticProviderError) as caught:
                    call_provider({'model': 'FICTIF'}, [SOURCE])
                self.assertNotIn('synthetic-secret-key', str(caught.exception))
                self.assertNotIn('private provider body', str(caught.exception))

    def test_oversized_provider_envelope_is_rejected(self):
        with patch('core.diagnostic_provider.build_opener') as factory:
            factory.return_value.open.return_value = BytesIO(b'x' * 262145)
            with self.assertRaises(DiagnosticProviderError):
                call_provider({'model': 'FICTIF'}, [SOURCE])

    def test_uncited_unknown_source_extra_fields_and_safety_bypass_are_rejected(self):
        variants = []
        for citations in ([], ['D999-P1-C1']):
            output = json.loads(json.dumps(OUTPUT))
            output['hypotheses'][0]['source_ids'] = citations
            variants.append(output)
        variants.append({**OUTPUT, 'confidence': 99})
        output = json.loads(json.dumps(OUTPUT))
        output['checks'][0]['instructions'] = 'Shunter la protection pour redémarrer.'
        variants.append(output)
        output = json.loads(json.dumps(OUTPUT))
        output['checks'][0]['instructions'] = 'Ouvrir le module sous tension.'
        variants.append(output)
        for output in variants:
            with self.subTest(output=output), self.assertRaises(ValueError):
                validate_output(output, [SOURCE], [])
