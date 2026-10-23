import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import Client, DemoInitialization, Intervention, StockMovement


@override_settings(TVM_DEMO_MODE=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SeedTests(TestCase):
    @patch.dict(os.environ, {'TVM_DEMO_PASSWORD': 'LongDemoTestingPhrase42!'})
    def test_seed_repeat_after_manual_creation_preserves_data_and_passwords(self):
        call_command('seed_demo', stdout=StringIO())
        admin = get_user_model().objects.get(username='admin')
        admin.set_password('ChangedSecurePhrase73!')
        admin.save()
        Client.objects.create(name='Client ajouté manuellement')
        counts = (Client.objects.count(), Intervention.objects.count(), StockMovement.objects.count())
        call_command('seed_demo', stdout=StringIO())
        self.assertEqual((Client.objects.count(), Intervention.objects.count(), StockMovement.objects.count()), counts)
        admin.refresh_from_db()
        self.assertTrue(admin.check_password('ChangedSecurePhrase73!'))
        self.assertTrue(DemoInitialization.objects.filter(pk='powercare-demo-v1').exists())

    @patch.dict(os.environ, {'TVM_DEMO_PASSWORD': 'LongDemoTestingPhrase42!'})
    def test_existing_real_data_blocks_demo_initialization(self):
        Client.objects.create(name='Client réel')
        with self.assertRaises(CommandError):
            call_command('seed_demo', stdout=StringIO())
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(Client.objects.count(), 1)

    @override_settings(TVM_DEMO_MODE=False)
    def test_demo_requires_explicit_mode(self):
        with self.assertRaises(CommandError):
            call_command('seed_demo', stdout=StringIO())
