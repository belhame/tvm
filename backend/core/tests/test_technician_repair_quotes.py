"""Current accepted technicians prepare quotes without acquiring finance rights."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.models import Client, Equipment, ServiceRequest
from core.notification_models import InAppNotification
from core.notification_service import notification_payload
from core.repair_quote_models import RepairQuote, RepairQuoteDecision
from core.repair_quote_service import create_draft, edit_draft, issue_quote
from core.request_assignment import assign_request, confirm_assignment
from core.workflow import CATEGORIES

User = get_user_model()
BASE = '/api/repair-quotes/'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TechnicianRepairQuoteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('tech-quote-admin', role='admin')
        self.manager = User.objects.create_user('tech-quote-manager', role='manager')
        self.tech = User.objects.create_user('tech-quote-tech', role='technician')
        self.other = User.objects.create_user('tech-quote-other', role='technician')
        self.company = Client.objects.create(name='Centre fictif devis technicien')
        self.foreign_company = Client.objects.create(name='Autre centre fictif devis')
        self.client = User.objects.create_user('tech-quote-client', role='client', client=self.company)
        self.foreign_client = User.objects.create_user('tech-quote-foreign', role='client', client=self.foreign_company)
        self.courier = User.objects.create_user('tech-quote-courier', role='courier')
        unit = Equipment.objects.create(client=self.company, serial_number='TECH-QUOTE-FICTIONAL-SN', model='Modèle fictif')
        self.record = ServiceRequest.objects.create(equipment=unit, subject='Réparation fictive', status='quotation', warranty_status='billable')
        self.api = APIClient()

    def body(self, **changes):
        return {'request_key': str(uuid4()), 'service_request': self.record.pk,
                'lines': [{'description': 'Réparation fictive', 'quantity': '1', 'unit_ht': '42.000'}],
                'vat_rate': '19', **changes}

    def assignment(self, technician=None, accept=True):
        self.record.refresh_from_db()
        actor = technician or self.tech
        record = assign_request(self.record.pk, actor=self.admin, technician_id=actor.pk,
                                expected_revision=self.record.assignment_revision)
        if accept:
            record = confirm_assignment(record.pk, actor=actor, expected_revision=record.assignment_revision, accept=True)
        self.record = record
        return record

    def create(self, actor=None):
        self.api.force_authenticate(actor or self.tech)
        result = self.api.post(BASE, self.body(), format='json')
        self.assertEqual(result.status_code, 201, result.data)
        return result.data

    def issue(self, draft):
        with self.captureOnCommitCallbacks(execute=True):
            result = self.api.post(f'{BASE}{draft["id"]}/issue/', {
                'request_key': str(uuid4()), 'expected_revision': draft['revision']}, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        return result.data

    def test_confirmed_technician_prepares_edits_and_sends_portal_quote(self):
        self.assignment()
        draft = self.create()
        self.assertTrue(draft['can_edit'])
        self.assertTrue(draft['can_issue'])
        self.assertTrue(draft['can_create_revision'])
        changed = self.api.patch(f'{BASE}{draft["id"]}/', {
            'expected_revision': draft['revision'], 'terms': 'Conditions publiques fictives.'}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        issued = self.issue(changed.data)
        self.assertFalse(issued['can_edit'])
        self.assertTrue(issued['can_create_revision'])
        quote = RepairQuote.objects.get(pk=issued['id'])
        self.assertEqual((quote.created_by_id, quote.issued_by_id), (self.tech.pk, self.tech.pk))
        self.assertTrue(quote.pdf_data)
        notice = InAppNotification.objects.get(recipient=self.client, kind='repair_quote')
        self.assertEqual(notification_payload(notice, self.client)['target_id'], quote.pk)
        self.assertFalse(InAppNotification.objects.filter(recipient=self.foreign_client).exists())
        self.api.force_authenticate(self.client)
        self.assertEqual(self.api.get(BASE).data[0]['id'], quote.pk)
        self.assertEqual(self.api.get(f'{BASE}{quote.pk}/pdf/').status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual((self.record.status, self.record.get_status_display()), ('quote_sent', 'Devis envoyé — attente de réponse'))

    def test_unassigned_pending_and_foreign_technicians_cannot_create(self):
        self.api.force_authenticate(self.tech)
        self.assertEqual(self.api.post(BASE, self.body(), format='json').status_code, 403)
        self.assignment(accept=False)
        self.assertEqual(self.api.post(BASE, self.body(), format='json').status_code, 403)
        self.assignment()
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.post(BASE, self.body(), format='json').status_code, 403)
        self.assertFalse(RepairQuote.objects.exists())

    def test_pending_assignee_reads_manager_draft_but_has_no_write_capabilities(self):
        self.assignment(accept=False)
        draft = self.create(self.admin)
        self.api.force_authenticate(self.tech)
        view = self.api.get(f'{BASE}{draft["id"]}/')
        self.assertEqual(view.status_code, 200)
        for flag in ('can_edit', 'can_issue', 'can_create_revision'):
            self.assertFalse(view.data[flag])
        self.assertEqual(self.api.patch(f'{BASE}{draft["id"]}/', {
            'expected_revision': 0, 'terms': 'Non confirmé'}, format='json').status_code, 403)
        self.assertEqual(self.api.post(f'{BASE}{draft["id"]}/issue/', {
            'request_key': str(uuid4()), 'expected_revision': 0}, format='json').status_code, 403)

    def test_old_author_loses_mutations_after_reassignment_and_reconfirmation_required(self):
        self.assignment()
        draft = self.create()
        self.assignment(self.other)
        for action in (
            lambda: edit_draft(self.tech, draft['id'], expected_revision=0, terms='Ancien auteur'),
            lambda: issue_quote(self.tech, draft['id'], request_key=uuid4(), expected_revision=0),
            lambda: create_draft(self.tech, **self.body()),
        ):
            with self.assertRaises(PermissionDenied):
                action()
        self.assertEqual(self.api.get(f'{BASE}{draft["id"]}/').status_code, 404)
        self.assignment(self.tech, accept=False)
        with self.assertRaises(PermissionDenied):
            issue_quote(self.tech, draft['id'], request_key=uuid4(), expected_revision=0)
        self.assignment()
        self.api.force_authenticate(self.tech)
        self.assertTrue(self.issue(draft)['is_current'])

    def test_replacement_confirmed_technician_can_finish_previous_authors_draft(self):
        self.assignment()
        draft = self.create()
        self.assignment(self.other)
        self.api.force_authenticate(self.other)
        edited = self.api.patch(f'{BASE}{draft["id"]}/', {
            'expected_revision': 0, 'terms': 'Relève fictive'}, format='json')
        self.assertEqual(edited.status_code, 200, edited.data)
        issued = self.issue(edited.data)
        quote = RepairQuote.objects.get(pk=issued['id'])
        self.assertEqual((quote.created_by_id, quote.issued_by_id), (self.tech.pk, self.other.pk))

    def test_role_or_account_revocation_is_rechecked_from_database(self):
        self.assignment()
        draft = self.create()
        User.objects.filter(pk=self.tech.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            issue_quote(self.tech, draft['id'], request_key=uuid4(), expected_revision=0)
        with self.assertRaises(PermissionDenied):
            edit_draft(self.tech, draft['id'], expected_revision=0, terms='Révoqué')
        User.objects.filter(pk=self.tech.pk).update(is_active=True, role='courier')
        with self.assertRaises(PermissionDenied):
            issue_quote(self.tech, draft['id'], request_key=uuid4(), expected_revision=0)
        self.assertEqual(RepairQuote.objects.get(pk=draft['id']).state, 'draft')
        self.assertFalse(InAppNotification.objects.filter(kind='repair_quote').exists())

    def test_client_decision_notifies_only_current_confirmed_technician_and_management(self):
        self.assignment()
        issued = self.issue(self.create())
        self.api.force_authenticate(self.client)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(f'{BASE}{issued["id"]}/decision/', {
                'request_key': str(uuid4()), 'expected_revision': issued['decision_revision'],
                'decision': 'accepted'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        notices = InAppNotification.objects.filter(kind='repair_quote', payload__event='decision')
        self.assertCountEqual(notices.values_list('recipient_id', flat=True), [self.admin.pk, self.manager.pk, self.tech.pk])
        old_notice = notices.get(recipient=self.tech)
        self.assignment(self.other, accept=False)
        self.assertFalse(notification_payload(old_notice, self.tech)['actionable'])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(f'{BASE}{issued["id"]}/decision/', {
                'request_key': str(uuid4()), 'expected_revision': response.data['decision_revision'],
                'decision': 'refused'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        last = RepairQuoteDecision.objects.order_by('-pk').first()
        current_notices = notices.filter(payload__occurrence=last.pk)
        self.assertCountEqual(current_notices.values_list('recipient_id', flat=True), [self.admin.pk, self.manager.pk])

    def test_client_and_courier_cannot_create_or_issue_and_status_key_stays_stable(self):
        draft = self.create(self.manager)
        for actor in (self.client, self.courier):
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.post(BASE, self.body(), format='json').status_code, 403)
            self.assertIn(self.api.post(f'{BASE}{draft["id"]}/issue/', {
                'request_key': str(uuid4()), 'expected_revision': 0}, format='json').status_code, (403, 404))
        self.assertEqual(ServiceRequest.Status.QUOTATION.value, 'quotation')
        self.assertIn(('quotation', 'À facturer', ('quotation',)), CATEGORIES)
        self.assertEqual(ServiceRequest.WarrantyStatus.QUOTATION.label, 'Devis')
