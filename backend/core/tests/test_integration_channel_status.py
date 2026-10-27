"""The integration screen reflects configured channels without sending messages."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IntegrationChannelStatusTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create_user('integration-status-fictional', role='manager'))

    @override_settings(TVM_EMAIL_ENABLED=False, TVM_WHATSAPP_ENABLED=False)
    def test_disabled_channels_and_ai_remain_unavailable_without_any_external_delivery(self):
        with patch('core.outbox_adapters.deliver_email', side_effect=AssertionError('No delivery on GET.')), \
             patch('core.outbox_adapters.deliver_whatsapp', side_effect=AssertionError('No delivery on GET.')):
            response = self.api.get('/api/integrations/')
        self.assertEqual(response.status_code, 200)
        for channel in ('email', 'whatsapp'):
            self.assertFalse(response.data[channel]['enabled'])
            self.assertFalse(response.data[channel]['operational'])
        self.assertFalse(response.data['ai']['operational'])

    @override_settings(TVM_EMAIL_ENABLED=True, EMAIL_HOST='smtp.fictional.invalid', EMAIL_HOST_USER='fictional',
        EMAIL_HOST_PASSWORD='FAKE_SMTP_SECRET_ONLY', DEFAULT_FROM_EMAIL='notification@fictional.invalid',
        EMAIL_USE_TLS=True, EMAIL_USE_SSL=False, TVM_WHATSAPP_ENABLED=True,
        TVM_WHATSAPP_TOKEN='FAKE_META_SECRET_ONLY', TVM_WHATSAPP_PHONE_ID='123456789012345',
        TVM_WHATSAPP_API_VERSION='v23.0', TVM_WHATSAPP_TEMPLATE='fictional_transport', TVM_WHATSAPP_LANGUAGE='fr')
    def test_channel_configuration_is_projected_but_never_discloses_credentials_or_claims_a_send(self):
        response = self.api.get('/api/integrations/')
        self.assertEqual(response.status_code, 200)
        for channel in ('email', 'whatsapp'):
            self.assertTrue(response.data[channel]['configured'])
            self.assertTrue(response.data[channel]['enabled'])
            self.assertTrue(response.data[channel]['operational'])
        self.assertNotIn('FAKE_SMTP_SECRET_ONLY', str(response.data))
        self.assertNotIn('FAKE_META_SECRET_ONLY', str(response.data))
        self.assertIn('journal', response.data['whatsapp']['message'])
        self.assertIn('08:00', response.data['whatsapp']['message'])
        from core.outbox_models import ExternalNotification
        self.assertFalse(ExternalNotification.objects.exists())
