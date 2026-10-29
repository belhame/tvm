"""Published customer quotes drive pending replies and the repair work queue."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, ServiceRequest
from core.notification_models import InAppNotification
from core.notification_service import notification_payload
from core.repair_quote_models import RepairQuoteBook, RepairQuoteDecision
from core.repair_quote_service import create_draft, decide_quote, issue_quote
from core.request_assignment import assign_request, confirm_assignment


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class QuoteResponseWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('response-lab-admin', role='admin')
        cls.manager = User.objects.create_user('response-lab-manager', role='manager')
        cls.tech = User.objects.create_user('response-lab-tech', role='technician')
        cls.other_tech = User.objects.create_user('response-lab-other-tech', role='technician')
        cls.company = Client.objects.create(name='Centre fictif réponse devis')
        cls.foreign_company = Client.objects.create(name='Autre centre fictif réponse devis')
        cls.customer = User.objects.create_user('response-lab-client', role='client', client=cls.company)
        cls.foreign_customer = User.objects.create_user('response-lab-foreign', role='client', client=cls.foreign_company)

    def setUp(self):
        self.api = APIClient()
        self.record = self.record_for('MAIN')

    def record_for(self, suffix, company=None):
        equipment = Equipment.objects.create(client=company or self.company,
            serial_number=f'RESPONSE-WORKFLOW-FICTIVE-{suffix}', model='Onduleur de laboratoire fictif')
        return ServiceRequest.objects.create(equipment=equipment, subject=f'Chiffrage fictif {suffix}',
            status='quotation', warranty_status='billable', client_reference=f'000-CENTRE-{suffix}')

    def assign(self):
        record = assign_request(self.record.pk, actor=self.admin, technician_id=self.tech.pk,
            expected_revision=self.record.assignment_revision)
        self.record = confirm_assignment(record.pk, actor=self.tech,
            expected_revision=record.assignment_revision, accept=True)

    def draft(self, record=None, actor=None):
        quote, _ = create_draft(actor or self.admin, service_request=(record or self.record).pk,
            request_key=uuid4(), lines=[{'description': 'Réparation fictive', 'quantity': '1', 'unit_ht': '50.000'}],
            currency='TND', vat_rate='19')
        return quote

    def issue(self, draft=None, actor=None):
        quote = draft or self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            result, _ = issue_quote(actor or self.admin, quote.pk,
                request_key=uuid4(), expected_revision=quote.revision)
        return result

    def choose(self, quote, decision='accepted', actor=None):
        revision = RepairQuoteBook.objects.get(pk=quote.book_id).decision_revision
        with self.captureOnCommitCallbacks(execute=True):
            result, _ = decide_quote(actor or self.customer, quote.pk, request_key=uuid4(),
                expected_revision=revision, decision=decision)
        return result

    def pending(self, actor=None):
        self.api.force_authenticate(actor or self.customer)
        response = self.api.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['pending_repair_quotes']

    def test_draft_stays_internal_until_publication_changes_the_workflow_status(self):
        draft = self.draft()
        self.assertEqual(self.pending(), {'count': 0, 'results': []})
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quotation')
        quote = self.issue(draft)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quote_sent')
        self.assertEqual(self.record.get_status_display(), 'Devis envoyé — attente de réponse')
        pending = self.pending()
        self.assertEqual(pending['count'], 1)
        self.assertEqual([row['id'] for row in pending['results']], [quote.pk])
        self.assertTrue(pending['results'][0]['can_decide'])
        self.assertEqual(pending['results'][0]['client_reference'], self.record.client_reference)

    def test_acceptance_moves_to_repair_and_reversible_choices_update_pending_home(self):
        quote = self.issue()
        original_pdf = bytes(quote.pdf_data)
        for decision, status in (('accepted', 'to_repair'), ('refused', 'rejected'), ('accepted', 'to_repair')):
            self.choose(quote, decision)
            self.record.refresh_from_db()
            self.assertEqual(self.record.status, status)
            self.assertEqual(self.pending(), {'count': 0, 'results': []})
        self.assertEqual(self.record.get_status_display(), 'À réparer')
        quote.refresh_from_db()
        self.assertEqual(bytes(quote.pdf_data), original_pdf)
        self.assertEqual(list(RepairQuoteDecision.objects.filter(quote=quote).order_by('revision')
            .values_list('decision', flat=True)), ['accepted', 'refused', 'accepted'])
        self.assertFalse(Intervention.objects.exists())

    def test_new_issued_revision_requires_another_reply_and_replaces_home_link(self):
        first = self.issue()
        self.choose(first)
        next_draft = self.draft()
        self.assertEqual(self.pending()['count'], 0)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'to_repair')
        second = self.issue(next_draft)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quote_sent')
        pending = self.pending()
        self.assertEqual((pending['count'], [row['id'] for row in pending['results']]), (1, [second.pk]))
        self.assertTrue(RepairQuoteDecision.objects.filter(quote=first, decision='accepted').exists())

    def test_pending_home_excludes_drafts_obsolete_versions_and_other_centres(self):
        current = self.issue()
        self.draft()  # Preparing another edition does not hide the unanswered one.
        superseded_record = self.record_for('SUPERSEDED')
        previous = self.issue(self.draft(superseded_record))
        latest = self.issue(self.draft(superseded_record))
        decided_record = self.record_for('DECIDED')
        decided = self.issue(self.draft(decided_record))
        self.choose(decided, 'refused')
        self.draft(self.record_for('DRAFT-ONLY'))
        foreign = self.issue(self.draft(self.record_for('FOREIGN', self.foreign_company)))
        own = self.pending()
        self.assertEqual(own['count'], 2)
        self.assertCountEqual([row['id'] for row in own['results']], [current.pk, latest.pk])
        self.assertNotIn(previous.pk, [row['id'] for row in own['results']])
        foreign_home = self.pending(self.foreign_customer)
        self.assertEqual((foreign_home['count'], [row['id'] for row in foreign_home['results']]), (1, [foreign.pk]))

    def test_pending_count_is_exact_when_home_preview_is_bounded(self):
        quotes = [self.issue(self.draft(self.record_for(f'BOUND-{index}'))) for index in range(10)]
        home = self.pending()
        self.assertEqual(home['count'], 10)
        self.assertEqual([row['id'] for row in home['results']], [quote.pk for quote in reversed(quotes[-8:])])

    def test_changed_equipment_owner_never_exposes_old_client_quote_on_either_home(self):
        quote = self.issue()
        Equipment.objects.filter(pk=self.record.equipment_id).update(client=self.foreign_company)
        for actor in (self.customer, self.foreign_customer):
            self.assertEqual(self.pending(actor), {'count': 0, 'results': []})
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.get(f'/api/repair-quotes/{quote.pk}/').status_code, 404)

    def test_internal_dashboard_does_not_load_customer_pending_home_documents(self):
        self.issue()
        self.api.force_authenticate(self.tech)
        response = self.api.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('pending_repair_quotes', response.data)

    def test_technician_dashboard_queues_count_only_their_assignments_and_management_sees_all(self):
        self.assign()
        self.choose(self.issue())
        other_record = self.record_for('METRICS-OTHER')
        other_record = assign_request(other_record.pk, actor=self.admin, technician_id=self.other_tech.pk,
            expected_revision=other_record.assignment_revision)
        confirm_assignment(other_record.pk, actor=self.other_tech,
            expected_revision=other_record.assignment_revision, accept=True)
        self.choose(self.issue(self.draft(other_record)))
        self.choose(self.issue(self.draft(self.record_for('METRICS-UNASSIGNED'))))
        for suffix, technician, company in (
            ('METRICS-WAITING-OWN', self.tech, self.company),
            ('METRICS-WAITING-OTHER', self.other_tech, self.foreign_company),
        ):
            waiting = self.record_for(suffix, company)
            waiting = assign_request(waiting.pk, actor=self.admin, technician_id=technician.pk,
                expected_revision=waiting.assignment_revision)
            confirm_assignment(waiting.pk, actor=technician,
                expected_revision=waiting.assignment_revision, accept=True)
            self.issue(self.draft(waiting))
        for actor, expected in ((self.tech, (1, 1)), (self.other_tech, (1, 1)),
                                (self.admin, (3, 2)), (self.manager, (3, 2))):
            self.api.force_authenticate(actor)
            response = self.api.get('/api/dashboard/')
            self.assertEqual(response.status_code, 200, response.data)
            metrics = response.data['metrics']
            self.assertEqual((metrics['to_repair_requests'], metrics['awaiting_quote_reply_requests']), expected)
        self.api.force_authenticate(self.customer)
        metrics = self.api.get('/api/dashboard/').data['metrics']
        self.assertNotIn('to_repair_requests', metrics)
        self.assertNotIn('awaiting_quote_reply_requests', metrics)

    def test_manual_create_patch_followup_and_timeline_cannot_invent_quote_states(self):
        self.assign()
        self.api.force_authenticate(self.admin)
        initial_events = self.record.operation_events.count()
        for target in ('quote_sent', 'to_repair'):
            with self.subTest(status=target):
                created = self.api.post('/api/requests/', {'equipment': self.record.equipment_id,
                    'subject': 'Tentative fictive sans devis', 'status': target}, format='json')
                self.assertEqual(created.status_code, 400, created.data)
                patched = self.api.patch(f'/api/requests/{self.record.pk}/', {'status': target}, format='json')
                self.assertEqual(patched.status_code, 400, patched.data)
                self.api.force_authenticate(self.tech)
                followed = self.api.post(f'/api/requests/{self.record.pk}/followup/', {
                    'status': target, 'expected_status': self.record.status,
                    'assignment_revision': self.record.assignment_revision, 'observation': 'Essai fictif sans accord.'}, format='json')
                self.assertEqual(followed.status_code, 400, followed.data)
                historical = self.api.post(f'/api/requests/{self.record.pk}/timeline/', {
                    'kind': 'status_changed', 'status_after': target, 'expected_status': self.record.status,
                    'assignment_revision': self.record.assignment_revision, 'observation': 'Essai fictif sans accord.'}, format='json')
                self.assertEqual(historical.status_code, 400, historical.data)
                self.api.force_authenticate(self.admin)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quotation')
        self.assertEqual(self.record.operation_events.count(), initial_events)

    def test_confirmed_technician_can_add_observation_while_waiting_without_inventing_reply(self):
        self.assign()
        self.issue(self.draft(actor=self.tech), actor=self.tech)
        self.record.refresh_from_db()
        self.api.force_authenticate(self.tech)
        response = self.api.post(f'/api/requests/{self.record.pk}/followup/', {
            'status': 'quote_sent', 'expected_status': 'quote_sent', 'assignment_revision': self.record.assignment_revision,
            'observation': 'Contact client effectué, réponse toujours attendue.'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quote_sent')
        self.assertEqual(self.pending()['count'], 1)
        self.assertFalse(RepairQuoteDecision.objects.exists())

    def test_diagnosis_history_allows_explicit_return_to_commercial_quote_before_work(self):
        self.assign()
        self.api.force_authenticate(self.tech)
        for target in ('maintenance', 'quotation'):
            self.record.refresh_from_db()
            response = self.api.post(f'/api/requests/{self.record.pk}/followup/', {
                'status': target, 'expected_status': self.record.status, 'assignment_revision': self.record.assignment_revision,
                'observation': 'Diagnostic fictif avant chiffrage de réparation.'}, format='json')
            self.assertEqual(response.status_code, 201, response.data)
        quote = self.issue(self.draft(actor=self.tech), actor=self.tech)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quote_sent')
        self.choose(quote)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'to_repair')
        self.assertFalse(Intervention.objects.exists())

    def test_changed_opinion_keeps_real_work_and_does_not_reopen_its_repair_queue(self):
        quote = self.issue()
        self.choose(quote)
        self.api.force_authenticate(self.admin)
        response = self.api.patch(f'/api/requests/{self.record.pk}/', {'status': 'maintenance'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.choose(quote, 'refused')
        self.choose(quote, 'accepted')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'maintenance')
        self.assertFalse(RepairQuoteDecision.objects.filter(quote=quote).order_by('-revision').first().status_changed)

    def test_completed_intervention_blocks_quote_status_projection_even_after_manual_commercial_detour(self):
        Intervention.objects.create(service_request=self.record, technician=self.tech, status='completed',
            completed_at=timezone.now(), work_done='Travaux déjà réalisés au laboratoire fictif.')
        ServiceRequest.objects.filter(pk=self.record.pk).update(status='quotation')
        quote = self.issue()
        self.choose(quote)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'quotation')
        self.assertFalse(RepairQuoteDecision.objects.get(quote=quote).status_changed)

    def test_accepted_notice_reaches_admin_and_current_technician_and_keeps_historical_meaning(self):
        self.assign()
        quote = self.issue(self.draft(actor=self.tech), actor=self.tech)
        self.choose(quote)
        accepted = RepairQuoteDecision.objects.get(quote=quote)
        accepted_notices = InAppNotification.objects.filter(kind='repair_quote', payload__event='decision', payload__occurrence=accepted.pk)
        self.assertCountEqual(accepted_notices.values_list('recipient_id', flat=True), [self.admin.pk, self.manager.pk, self.tech.pk])
        admin_notice = accepted_notices.get(recipient=self.admin)
        self.choose(quote, 'refused')
        accepted_payload = notification_payload(admin_notice, self.admin)
        self.assertEqual(accepted_payload['title'], 'Devis accepté')
        self.assertIn('accepté', accepted_payload['body'])
        self.assertIn(quote.reference, accepted_payload['body'])
        refused = RepairQuoteDecision.objects.filter(quote=quote, decision='refused').get()
        refused_notice = InAppNotification.objects.get(recipient=self.tech, kind='repair_quote', payload__event='decision', payload__occurrence=refused.pk)
        self.assertEqual(notification_payload(refused_notice, self.tech)['title'], 'Devis refusé')
        self.assertNotIn(self.foreign_customer.pk, accepted_notices.values_list('recipient_id', flat=True))

