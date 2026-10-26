"""A recorded physical handoff freezes technical identity, not unpaid finance."""
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.disposition_workflow import (approve_free_diagnostic, close_disposition, confirm_diagnostic_invoice,
    disposition_payload, edit_quote_draft, issue_quote, mark_nonrepairable, mark_repaired, reset_disposition)
from core.exchange_workflow import (bill_exchange, close_exchange, exchange_payload, prepare_exchange,
    ready_exchange, reset_exchange, validate_exchange)
from core.logistics_models import OutboundJob
from core.models import Client, Equipment, ServiceRequest, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RecordedHandoffWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('handoff-guard-admin', role='admin')
        self.driver = User.objects.create_user('handoff-guard-driver', role='courier')
        self.company = Client.objects.create(name='Centre Remise Fictif')
        self.unit = Equipment.objects.create(client=self.company, serial_number='REMISE-FICTIVE-001', model='Modèle fictif')
        self.request = ServiceRequest.objects.create(equipment=self.unit, subject='Remise fictive', status='testing')

    def handoff(self, *, equipment=None, kind='delivery'):
        return OutboundJob.objects.create(service_request=self.request, client=self.company, delivery_equipment=equipment or self.unit,
            kind=kind, assigned_courier=self.driver, assigned_at=timezone.now(), assigned_by=self.admin,
            handed_over_at=timezone.now(), handed_over_by=self.driver, recipient_name='Destinataire fictif', active=False)

    def test_repaired_handoff_blocks_reclassification_and_reset_but_keeps_replay_and_close(self):
        data = {'diagnosis': 'Tests fictifs réussis.', 'tests_passed': True, 'tested_on': timezone.localdate()}
        mark_repaired(self.request.pk, data, actor=self.admin)
        self.handoff()
        with self.assertRaises(ValidationError):
            reset_disposition(self.request.pk, actor=self.admin, reason='Reprise après remise interdite')
        with self.assertRaises(ValidationError):
            mark_nonrepairable(self.request.pk, {'diagnosis': 'Nouvelle qualification interdite'}, actor=self.admin)
        replay = mark_repaired(self.request.pk, data, actor=self.admin)
        self.assertEqual(replay.status, 'ready_for_delivery')
        payload = disposition_payload(replay, self.admin)
        self.assertFalse(payload['can_reset'])
        self.assertFalse(payload['can_mark_nonrepairable'])
        self.assertEqual(close_disposition(self.request.pk, actor=self.admin).status, 'closed')

    def test_return_handoff_preserves_invoice_gate_and_allows_quote_then_invoice_and_close(self):
        mark_nonrepairable(self.request.pk, {'diagnosis': 'Diagnostic fictif non réparable.'}, actor=self.admin)
        self.handoff(kind='return')
        with self.assertRaises(ValidationError):
            close_disposition(self.request.pk, actor=self.admin)
        edit_quote_draft(self.request.pk, {'price_ht': '50.000', 'vat_rate': '19.00', 'currency': 'TND'}, actor=self.admin)
        issue_quote(self.request.pk, actor=self.admin)
        confirm_diagnostic_invoice(self.request.pk, {'invoice_reference': 'FACTURE-FICTIVE-001', 'invoiced_on': timezone.localdate()}, actor=self.admin)
        self.assertEqual(close_disposition(self.request.pk, actor=self.admin).status, 'closed')

    def test_return_handoff_still_allows_explicit_financial_gratuity(self):
        mark_nonrepairable(self.request.pk, {'diagnosis': 'Diagnostic fictif non réparable.', 'fee_mode': 'free', 'free_reason': 'Proposition fictive'}, actor=self.admin)
        self.handoff(kind='return')
        edit_quote_draft(self.request.pk, {'price_ht': '0.000', 'vat_rate': '0.00', 'currency': 'TND'}, actor=self.admin)
        issue_quote(self.request.pk, actor=self.admin)
        approve_free_diagnostic(self.request.pk, actor=self.admin, reason='Gratuité autorisée fictive')
        self.assertEqual(close_disposition(self.request.pk, actor=self.admin).status, 'closed')

    def test_exchange_handoff_keeps_replacement_and_still_allows_external_invoice_then_close(self):
        self.request.status = 'exchange'
        self.request.save(update_fields=['status'])
        prepare_exchange(self.request.pk, {'replacement_serial_number': 'REMISE-FICTIVE-002', 'replacement_model': 'Remplacement fictif'}, actor=self.admin)
        validated = validate_exchange(self.request.pk, actor=self.admin)
        ready_exchange(self.request.pk, actor=self.admin)
        self.handoff(equipment=validated.exchange_process.replacement_equipment)
        with self.assertRaises(ValidationError):
            reset_exchange(self.request.pk, actor=self.admin, reason='Reprise après remise interdite')
        with self.assertRaises(ValidationError):
            prepare_exchange(self.request.pk, {'replacement_serial_number': 'REMISE-FICTIVE-003'}, actor=self.admin)
        self.request.refresh_from_db()
        payload = exchange_payload(self.request, self.admin)
        self.assertFalse(payload['can_reset'])
        self.assertTrue(payload['can_validate_billing'])
        bill_exchange(self.request.pk, {'invoice_reference': 'FACTURE-FICTIVE-002', 'invoiced_on': timezone.localdate()}, actor=self.admin)
        self.assertEqual(close_exchange(self.request.pk, actor=self.admin).status, 'closed')
