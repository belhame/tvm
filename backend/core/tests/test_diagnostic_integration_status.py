"""Integration status describes configuration without making a provider call."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DiagnosticIntegrationStatusTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user('diagnostic-status-fictional', role='manager'))

    @override_settings(TVM_AI_ENABLED=False, TVM_AI_API_KEY='', TVM_AI_MODEL='gpt-4.1-mini')
    def test_local_library_available_without_external_diagnosis_or_fake_result(self):
        with patch('core.diagnostic_provider.call_provider', side_effect=AssertionError('No provider on GET.')):
            integration = self.api.get('/api/integrations/')
            status = self.api.get('/api/diagnostics/status/')
        self.assertEqual(integration.status_code, 200)
        self.assertEqual(status.status_code, 200)
        for result in (integration.data['ai'], status.data):
            self.assertFalse(result['enabled'])
            self.assertFalse(result['configured'])
            self.assertFalse(result['operational'])
            self.assertEqual(result['library']['documents'], 0)

    @override_settings(TVM_AI_ENABLED=True, TVM_AI_API_KEY='FICTIONAL_PRIVATE_KEY_NOT_REAL', TVM_AI_MODEL='gpt-4.1-mini')
    def test_ready_configuration_does_not_claim_provider_verified_or_expose_key(self):
        with patch('core.diagnostic_provider.call_provider', side_effect=AssertionError('No provider on GET.')):
            integration = self.api.get('/api/integrations/')
            status = self.api.get('/api/diagnostics/status/')
        for result in (integration.data['ai'], status.data):
            self.assertTrue(result['enabled'])
            self.assertTrue(result['configured'])
            self.assertTrue(result['configuration_only'])
            self.assertNotIn('FICTIONAL_PRIVATE_KEY_NOT_REAL', str(result))
        from core.diagnostic_models import DiagnosticRun
        self.assertFalse(DiagnosticRun.objects.exists())
