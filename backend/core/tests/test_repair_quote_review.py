"""Independent repair quote security checks, with wholly fictional records."""
from hashlib import sha256
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Client, Equipment, ServiceRequest
from core.repair_quote_models import RepairQuote, RepairQuoteDecision


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentRepairQuoteReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre devis fictif A', notes='PRIVATE_CUSTOMER_NOTE_REPAIR_REVIEW')
        cls.foreign_company = Client.objects.create(name='Centre devis fictif B')
        cls.admin = User.objects.create_user('repair-review-admin', role='admin')
        cls.manager = User.objects.create_user('repair-review-manager', role='manager')
        cls.tech = User.objects.create_user('repair-review-tech', role='technician')
        cls.customer = User.objects.create_user('repair-review-client', role='client', client=cls.company)
        cls.coworker = User.objects.create_user('repair-review-client-colleague', role='client', client=cls.company)
        cls.foreign_customer = User.objects.create_user('repair-review-foreign-client', role='client', client=cls.foreign_company)
        cls.courier = User.objects.create_user('repair-review-courier', role='courier')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.unit = Equipment.objects.create(client=self.company, serial_number='REPAIR-REVIEW-FICTITIOUS-SN', model='Modèle fictif de contrôle')
        self.record = ServiceRequest.objects.create(equipment=self.unit, subject='Réparation fictive', client_reference='000-042-CENTRE-FICTIF', assigned_technician=self.tech)

    def path(self, quote=None, action=''):
        return '/api/repair-quotes/' + (f'{quote["id"]}/' if quote else '') + (f'{action}/' if action else '')

    def draft(self, **changes):
        body = {'request_key': str(uuid4()), 'service_request': self.record.pk,
                'lines': [{'description': 'Réparation fictive', 'quantity': '2.5', 'unit_ht': '10.125'},
                          {'description': 'Essais fictifs', 'quantity': '3', 'unit_ht': '4.200'}],
                'vat_rate': '19', 'currency': 'TND', 'discount_kind': 'percent', 'discount_value': '7.5',
                'terms': 'Conditions publiques de laboratoire uniquement.'}
        body.update(changes)
        response = self.api.post(self.path(), body, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def issue(self, quote):
        response = self.api.post(self.path(quote, 'issue'), {'request_key': str(uuid4()), 'expected_revision': quote['revision']}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def decide(self, quote, decision, *, expected=None, key=None):
        return self.api.post(self.path(quote, 'decision'), {'request_key': str(key or uuid4()),
            'expected_revision': quote['decision_revision'] if expected is None else expected, 'decision': decision}, format='json')

    def test_client_drafts_are_hidden_and_no_nonmanager_can_prepare_or_forge_a_decision(self):
        draft = self.draft()
        for actor in (self.customer, self.courier):
            self.api.force_authenticate(actor)
            self.assertIn(self.api.get(self.path(draft)).status_code, (403, 404))
            self.assertIn(self.api.get(self.path(draft, 'pdf')).status_code, (403, 404))
        self.api.force_authenticate(self.admin)
        issued = self.issue(draft)
        for actor in (self.tech, self.manager, self.courier):
            self.api.force_authenticate(actor)
            self.assertEqual(self.decide(issued, 'accepted').status_code, 403)
        self.api.force_authenticate(self.tech)
        self.assertEqual(self.api.get(self.path(issued)).status_code, 200)
        response = self.api.post(self.path(), {'request_key': str(uuid4()), 'service_request': self.record.pk,
            'lines': [{'description': 'Contournement fictif', 'quantity': '1', 'unit_ht': '1.000'}], 'vat_rate': '0'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.api.force_authenticate(None)
        for path in (self.path(), self.path(issued), self.path(issued, 'pdf')):
            self.assertIn(self.api.get(path).status_code, (401, 403))

    def test_current_and_frozen_client_ownership_both_gate_list_pdf_and_decision(self):
        quote = self.issue(self.draft())
        self.api.force_authenticate(self.foreign_customer)
        self.assertEqual(self.api.get(self.path()).data, [])
        for path in (self.path(quote), self.path(quote, 'pdf')):
            self.assertEqual(self.api.get(path).status_code, 404)
        self.assertEqual(self.decide(quote, 'accepted').status_code, 404)
        # Deliberately emulate a corrupt/out-of-band transfer: neither portal
        # may inherit the other company's old frozen commercial document.
        Equipment.objects.filter(pk=self.unit.pk).update(client=self.foreign_company)
        for actor in (self.customer, self.foreign_customer):
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.get(self.path()).data, [])
            self.assertEqual(self.api.get(self.path(quote)).status_code, 404)
            self.assertEqual(self.api.get(self.path(quote, 'pdf')).status_code, 404)
            self.assertEqual(self.decide(quote, 'refused').status_code, 404)
        self.assertFalse(RepairQuoteDecision.objects.exists())

    def test_reversible_current_decisions_and_same_price_new_version_never_inherit_consent(self):
        first = self.issue(self.draft())
        first_bytes = bytes(RepairQuote.objects.get(pk=first['id']).pdf_data)
        self.api.force_authenticate(self.customer)
        for choice, status in (('accepted', 'approved'), ('refused', 'rejected'), ('accepted', 'approved')):
            response = self.decide(first, choice)
            self.assertEqual(response.status_code, 200, response.data)
            first = response.data
            self.record.refresh_from_db()
            self.assertEqual(self.record.status, status)
        self.assertEqual([row['decision'] for row in first['history']], ['accepted', 'refused', 'accepted'])
        self.api.force_authenticate(self.admin)
        second = self.draft()
        self.api.force_authenticate(self.customer)
        self.assertTrue(self.api.get(self.path(first)).data['is_current'])
        self.assertEqual(self.api.get(self.path(first)).data['decision'], 'accepted')
        self.api.force_authenticate(self.admin)
        second = self.issue(second)
        self.assertEqual(second['amounts'], first['amounts'])
        self.assertEqual(second['decision'], 'pending')
        self.assertEqual(second['history'], [])
        self.api.force_authenticate(self.customer)
        self.assertEqual(self.decide(first, 'refused').status_code, 409)
        old = self.api.get(self.path(first)).data
        self.assertFalse(old['is_current'])
        self.assertFalse(old['can_decide'])
        self.assertEqual(old['decision'], 'accepted')
        self.assertEqual(self.api.get(self.path(first, 'pdf')).content, first_bytes)
        accepted = self.decide(second, 'accepted')
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data['version'], first['version'] + 1)

    def test_decision_cas_and_idempotency_do_not_overwrite_a_later_opinion(self):
        quote = self.issue(self.draft())
        self.api.force_authenticate(self.customer)
        key, original_revision = uuid4(), quote['decision_revision']
        first = self.decide(quote, 'accepted', key=key)
        self.assertEqual(first.status_code, 200, first.data)
        current = first.data
        self.assertEqual(self.decide(current, 'refused', expected=original_revision).status_code, 409)
        self.assertEqual(self.decide(quote, 'accepted', key=key).status_code, 200)
        self.assertEqual(RepairQuoteDecision.objects.count(), 1)
        self.assertEqual(self.decide(quote, 'refused', key=key).status_code, 409)
        self.api.force_authenticate(self.coworker)
        self.assertEqual(self.decide(quote, 'accepted', key=key).status_code, 409)
        self.assertEqual(RepairQuoteDecision.objects.count(), 1)
        self.api.force_authenticate(self.customer)
        later = self.decide(current, 'refused')
        self.assertEqual(later.status_code, 200, later.data)
        replay = self.decide(quote, 'accepted', key=key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data['decision'], 'refused')
        self.assertEqual(RepairQuoteDecision.objects.count(), 2)

    def test_issued_prices_pdf_and_public_references_cannot_be_patched_or_forged(self):
        quote = self.issue(self.draft())
        original = self.api.get(self.path(quote, 'pdf'))
        self.assertEqual(original.status_code, 200)
        self.assertEqual(sha256(original.content).hexdigest(), quote['pdf_sha256'])
        self.assertEqual(quote['client_reference'], '000-042-CENTRE-FICTIF')
        for body in ({'expected_revision': quote['revision'], 'discount_value': '100'},
                     {'expected_revision': quote['revision'], 'state': 'draft', 'snapshot': {}},
                     {'expected_revision': quote['revision'], 'decision': 'accepted'}):
            response = self.api.patch(self.path(quote), body, format='json')
            self.assertIn(response.status_code, (400, 409), response.data)
        self.api.force_authenticate(self.customer)
        bad = self.api.post(self.path(quote, 'decision'), {'request_key': str(uuid4()), 'expected_revision': quote['decision_revision'],
            'decision': 'accepted', 'actor': self.admin.pk, 'discount_value': '100'}, format='json')
        self.assertEqual(bad.status_code, 400, bad.data)
        self.assertFalse(RepairQuoteDecision.objects.exists())
        self.assertNotIn(self.company.notes, str(self.api.get(self.path(quote)).data))
        self.assertEqual(self.api.get(self.path(quote, 'pdf')).content, original.content)

    def test_invalid_money_never_creates_partial_drafts_and_full_discount_does_not_invoice(self):
        baseline = RepairQuote.objects.count()
        valid = {'request_key': str(uuid4()), 'service_request': self.record.pk,
                 'lines': [{'description': 'Essai fictif', 'quantity': '1', 'unit_ht': '10.000'}], 'vat_rate': '19',
                 'currency': 'TND', 'discount_kind': 'none', 'discount_value': '0'}
        changes = [
            {'lines': [{'description': 'Fictif', 'quantity': '0', 'unit_ht': '10.000'}]},
            {'lines': [{'description': 'Fictif', 'quantity': '1', 'unit_ht': 1.5}]},
            {'lines': [{'description': 'Fictif', 'quantity': '1', 'unit_ht': '1e2'}]},
            {'vat_rate': 'NaN'}, {'discount_kind': 'percent', 'discount_value': '7.555'},
            {'discount_kind': 'fixed', 'discount_value': '10.001'},
            {'currency': 'EUR', 'lines': [{'description': 'Fictif', 'quantity': '1', 'unit_ht': '1.001'}]},
        ]
        for change in changes:
            with self.subTest(change=change):
                response = self.api.post(self.path(), {**valid, **change}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(RepairQuote.objects.count(), baseline)
        quote = self.issue(self.draft(discount_kind='percent', discount_value='100'))
        self.assertTrue(quote['amounts']['fully_discounted'])
        self.assertEqual(quote['amounts']['total_ttc'], '0.000')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quotation')
        self.assertIsNone(self.record.closed_at)
        self.assertFalse(hasattr(self.record, 'disposition_process'))
        self.assertFalse(hasattr(self.record, 'exchange_process'))

    def test_later_client_reversal_records_opinion_without_rewinding_real_work(self):
        quote = self.issue(self.draft())
        self.api.force_authenticate(self.customer)
        quote = self.decide(quote, 'accepted').data
        self.api.force_authenticate(self.admin)
        changed = self.api.patch(f'/api/requests/{self.record.pk}/', {'status': 'maintenance'}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.api.force_authenticate(self.customer)
        response = self.decide(quote, 'refused')
        self.assertEqual(response.status_code, 200, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'maintenance')
        self.assertEqual(response.data['decision'], 'refused')
        self.assertFalse(response.data['history'][-1]['status_changed'])

    def test_notifications_are_in_app_owned_and_revalidated_after_identity_changes(self):
        from core.notification_models import InAppNotification
        from core.repair_quote_service import quote_notification_payload

        with self.captureOnCommitCallbacks(execute=True):
            quote = self.issue(self.draft())
        items = InAppNotification.objects.filter(kind='repair_quote')
        self.assertEqual(set(items.values_list('recipient_id', flat=True)), {self.customer.pk, self.coworker.pk})
        own = items.get(recipient=self.customer)
        payload = quote_notification_payload(own, self.customer)
        self.assertTrue(payload['actionable'])
        self.assertNotIn(self.company.notes, str(payload))
        self.assertNotIn(self.unit.serial_number, str(own.payload))
        Equipment.objects.filter(pk=self.unit.pk).update(client=self.foreign_company)
        stale = quote_notification_payload(own, self.customer)
        self.assertFalse(stale['actionable'])
        self.assertIsNone(stale['target'])
        self.assertEqual(stale['details'], {})
        self.assertNotIn(quote['reference'], str(stale))

    def test_session_authenticated_client_mutation_requires_real_csrf(self):
        quote = self.issue(self.draft())
        session_api = APIClient(enforce_csrf_checks=True)
        session_api.force_login(self.customer)
        response = session_api.post(self.path(quote, 'decision'), {'request_key': str(uuid4()),
            'expected_revision': quote['decision_revision'], 'decision': 'accepted'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RepairQuoteDecision.objects.exists())
