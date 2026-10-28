from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.courier_dispatch import accept_outbound
from core.exchange_models import ExchangeProcess
from core.logistics_delivery_note_models import DeliveryNoteMission, LogisticsDeliveryNote
from core.logistics_delivery_notes import DeliveryNoteConflict, create_note
from core.logistics_models import OutboundJob
from core.logistics_service import assign_outbound, cancel_outbound, handoff
from core.models import Client, DeliveryLine, DeliveryNote, Equipment, Part, ServiceRequest, StockMovement

User = get_user_model()
BASE = '/api/logistics/delivery-notes/'


class NoteFactory:
    def job(self, *, company=None, courier=None, accepted=True, address=None):
        company = company or self.company
        courier = courier or self.courier
        index = ServiceRequest.objects.count() + 1
        equipment = Equipment.objects.create(client=company, serial_number=f'BL-SYNTHETIC-{index}', model=f'Modèle fictif {index}', brand='Marque de laboratoire')
        record = ServiceRequest.objects.create(equipment=equipment, subject='PRIVATE_SAV_SUBJECT', description='PRIVATE_SAV_DESCRIPTION', client_reference=f'000CLIENT-{index}')
        ServiceRequest.objects.filter(pk=record.pk).update(status='ready_for_delivery')
        job = assign_outbound(self.manager, {'service_request': record.pk, 'courier': courier.pk,
            'delivery_address': address if address is not None else company.address})
        if accepted:
            job = accept_outbound(courier, job.pk, job.assignment_revision, True)
        return job


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogisticsDeliveryNoteTests(NoteFactory, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('bl-manager', role='manager')
        cls.tech = User.objects.create_user('bl-tech', role='technician')
        cls.courier = User.objects.create_user('bl-tvm', role='courier', first_name='Livreur TVM fictif')
        cls.other = User.objects.create_user('bl-other-tvm', role='courier')
        cls.company = Client.objects.create(name='Client BL fictif A', address='Adresse du centre A', city='Ville A')
        cls.other_company = Client.objects.create(name='Client BL fictif B', address='Adresse du centre B')
        cls.customer = User.objects.create_user('bl-client', role='client', client=cls.company)
        cls.external = User.objects.create_user('bl-external', role='courier', courier_kind='client', client=cls.company)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.courier)

    def prepare(self, jobs, **values):
        return self.api.post(BASE, {'request_key': str(uuid4()), 'job_ids': [job.pk for job in jobs], **values}, format='json')

    def pdf(self, note_id):
        return self.api.get(f'{BASE}{note_id}/pdf/')

    def test_single_and_batch_notes_have_one_line_per_real_ups_and_no_delivery_effect(self):
        first, second = self.job(address='Site de livraison A'), self.job(address='Site de livraison B')
        before = [(job.pk, job.assignment_revision, job.accepted_at, job.handed_over_at, job.service_request.status) for job in [first, second]]
        part = Part.objects.create(sku='BL-STOCK-UNCHANGED', name='Pièce fictive', stock_quantity=9)
        result = self.prepare([first, second], comment='Livraison préparée pour deux sites du même client.')
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['status'], 'prepared')
        self.assertEqual(result.data['line_count'], 2)
        self.assertEqual({row['delivery_address'] for row in result.data['lines']}, {'Site de livraison A', 'Site de livraison B'})
        note = DeliveryNote.objects.get(pk=result.data['id'])
        self.assertEqual((note.status, note.delivered_at), ('ready', None))
        self.assertEqual(list(note.lines.values_list('quantity', flat=True)), [1, 1])
        self.assertFalse(note.lines.exclude(part=None).exists())
        for job in [first, second]:
            job.refresh_from_db()
        after = [(job.pk, job.assignment_revision, job.accepted_at, job.handed_over_at, job.service_request.status) for job in [first, second]]
        self.assertEqual(before, after)
        part.refresh_from_db()
        self.assertEqual(part.stock_quantity, 9)
        self.assertEqual(StockMovement.objects.count(), 0)
        pdf = self.pdf(note.pk)
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        for job in [first, second]:
            self.assertIn(job.service_request.reference, text)
            self.assertIn(job.service_request.client_reference, text)
            self.assertIn(job.delivery_equipment.serial_number, text)
        for private in ['PRIVATE_SAV_SUBJECT', 'PRIVATE_SAV_DESCRIPTION', 'BL-STOCK-UNCHANGED']:
            self.assertNotIn(private, text)

    def test_exact_key_replay_is_idempotent_even_if_order_is_reversed(self):
        first, second = self.job(), self.job()
        payload = {'request_key': str(uuid4()), 'job_ids': [first.pk, second.pk], 'comment': 'Commentaire public'}
        created = self.api.post(BASE, payload, format='json')
        replay = self.api.post(BASE, {**payload, 'job_ids': list(reversed(payload['job_ids']))}, format='json')
        self.assertEqual((created.status_code, replay.status_code), (201, 200))
        self.assertEqual(created.data['id'], replay.data['id'])
        self.assertFalse(replay.data['created'])
        self.assertEqual(LogisticsDeliveryNote.objects.count(), 1)
        altered = self.api.post(BASE, {**payload, 'comment': 'Autre commentaire'}, format='json')
        self.assertEqual(altered.status_code, 409)

    def test_new_key_overlapping_existing_note_conflicts_without_duplicate_lines(self):
        first, second = self.job(), self.job()
        created = self.prepare([first, second])
        conflict = self.prepare([first])
        self.assertEqual(conflict.status_code, 409, conflict.data)
        self.assertEqual(conflict.data['existing_note']['id'], created.data['id'])
        self.assertIs(type(conflict.data['existing_note']['id']), int)
        self.assertEqual(DeliveryNoteMission.objects.filter(active=True).count(), 2)

    def test_courier_needs_own_accepted_jobs_and_manager_does_not_fake_acceptance(self):
        job = self.job(accepted=False)
        self.assertEqual(self.prepare([job]).status_code, 403)
        self.api.force_authenticate(self.manager)
        prepared = self.prepare([job])
        self.assertEqual(prepared.status_code, 201, prepared.data)
        job.refresh_from_db()
        self.assertIsNone(job.accepted_at)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.pdf(prepared.data['id']).status_code, 404)

    def test_mixed_clients_and_couriers_are_rejected_atomically(self):
        first = self.job()
        other_company = self.job(company=self.other_company)
        self.assertEqual(self.prepare([first, other_company]).status_code, 400)
        other_courier = self.job(courier=self.other)
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.prepare([first, other_courier]).status_code, 400)
        self.assertEqual(DeliveryNote.objects.count(), 0)

    def test_client_external_courier_technician_and_anonymous_have_no_bl_access(self):
        prepared = self.prepare([self.job()]).data
        for actor in [self.customer, self.external, self.tech, None]:
            self.api.force_authenticate(actor)
            self.assertEqual(self.api.get(BASE).status_code, 403)
            self.assertEqual(self.pdf(prepared['id']).status_code, 403)
            self.assertEqual(self.api.post(BASE, {'request_key': str(uuid4()), 'job_ids': []}, format='json').status_code, 403)

    def test_cancellation_is_reasoned_releases_lot_and_leaves_original_admin_pdf(self):
        first, second = self.job(), self.job()
        prepared = self.prepare([first, second]).data
        original_pdf = self.pdf(prepared['id']).content
        self.assertEqual(self.api.post(f'{BASE}{prepared["id"]}/cancel/', {'reason': ''}, format='json').status_code, 400)
        cancelled = self.api.post(f'{BASE}{prepared["id"]}/cancel/', {'reason': 'Nouveau regroupement du lot'}, format='json')
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data['status'], 'cancelled')
        self.assertEqual(DeliveryNoteMission.objects.filter(active=True).count(), 0)
        self.assertEqual(self.pdf(prepared['id']).status_code, 404)
        replacement = self.prepare([first])
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.pdf(prepared['id']).content, original_pdf)

    def test_reassignment_invalidates_entire_lot_and_old_courier_loses_pdf(self):
        first, second = self.job(), self.job()
        prepared = self.prepare([first, second]).data
        first = assign_outbound(self.manager, {'courier': self.other.pk}, first.pk)
        note = LogisticsDeliveryNote.objects.get(pk=prepared['id'])
        self.assertEqual(note.state, 'cancelled')
        self.assertFalse(note.missions.filter(active=True).exists())
        self.assertEqual(self.pdf(note.pk).status_code, 404)
        self.assertEqual(self.api.get(BASE).data, [])
        accept_outbound(self.other, first.pk, first.assignment_revision, True)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.prepare([first]).status_code, 201)

    def test_direct_model_assignment_change_invalidates_and_new_acceptance_can_prepare(self):
        job = self.job()
        prepared = self.prepare([job]).data
        job.assigned_courier = self.other
        job.save(update_fields=['assigned_courier'])
        self.assertEqual(LogisticsDeliveryNote.objects.get(pk=prepared['id']).state, 'cancelled')
        accept_outbound(self.other, job.pk, job.assignment_revision, True)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.prepare([job]).status_code, 201)

    def test_handoff_retains_original_pdf_and_prevents_late_cancellation(self):
        job = self.job()
        prepared = self.prepare([job]).data
        original = self.pdf(prepared['id']).content
        handoff(self.courier, job.pk, {'recipient_name': 'Destinataire fictif'})
        self.assertEqual(self.pdf(prepared['id']).content, original)
        payload = self.api.get(f'{BASE}{prepared["id"]}/').data
        self.assertFalse(payload['can_cancel'])
        self.assertEqual(self.api.post(f'{BASE}{prepared["id"]}/cancel/', {'reason': 'Trop tard'}, format='json').status_code, 409)

    def test_reprint_is_exact_bytes_after_profile_client_and_timezone_changes(self):
        job = self.job()
        prepared = self.prepare([job]).data
        original = self.pdf(prepared['id']).content
        Client.objects.filter(pk=self.company.pk).update(name='Nouveau nom du centre', address='Nouvelle adresse')
        User.objects.filter(pk=self.courier.pk).update(first_name='Nouveau prénom')
        with override_settings(TIME_ZONE='Pacific/Auckland'):
            self.assertEqual(self.pdf(prepared['id']).content, original)
        self.api.force_authenticate(self.manager)
        Equipment.objects.filter(pk=job.delivery_equipment_id).update(model='Modèle corrigé après émission')
        self.assertEqual(self.pdf(prepared['id']).content, original)

    def test_changed_legacy_equipment_identity_needs_controlled_cancellation_before_reprint(self):
        job = self.job()
        prepared = self.prepare([job]).data
        original = self.pdf(prepared['id']).content
        equipment = job.delivery_equipment
        equipment.serial_number = 'BL-CORRECTED-LEGACY-SERIAL'
        with self.assertRaises(ValidationError):
            equipment.save(update_fields=['serial_number'])
        self.assertEqual(self.pdf(prepared['id']).content, original)
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.pdf(prepared['id']).content, original)
        cancelled = self.api.post(f'{BASE}{prepared["id"]}/cancel/', {'reason': 'Correction explicite de l’identité du matériel'}, format='json')
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        equipment.save(update_fields=['serial_number'])
        self.api.force_authenticate(self.courier)
        replacement = self.prepare([job])
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertEqual(replacement.data['lines'][0]['serial_number'], equipment.serial_number)

    def test_legacy_general_api_lists_prepared_snapshot_but_cannot_modify_or_delete_it(self):
        prepared = self.prepare([self.job()]).data
        self.api.force_authenticate(self.manager)
        rows = self.api.get('/api/delivery-notes/').data
        row = next(item for item in rows if item['id'] == prepared['id'])
        self.assertEqual(row['logistics_status'], 'prepared')
        self.assertEqual(row['pdf_url'], prepared['pdf_url'])
        changed = self.api.patch(f'/api/delivery-notes/{prepared["id"]}/', {'status': 'delivered', 'lines': [{'description': 'Faux', 'quantity': 99}]}, format='json')
        self.assertEqual(changed.status_code, 400, changed.data)
        self.assertEqual(self.api.delete(f'/api/delivery-notes/{prepared["id"]}/').status_code, 409)
        legacy = self.api.post('/api/delivery-notes/', {'client': self.company.pk, 'lines': [{'description': 'Ancienne ligne libre', 'quantity': 2}]}, format='json')
        self.assertEqual(legacy.status_code, 201, legacy.data)
        self.assertEqual(self.api.patch(f'/api/delivery-notes/{legacy.data["id"]}/', {'notes': 'Ancien CRUD conservé'}, format='json').status_code, 200)

    def test_validated_exchange_prints_replacement_not_original_as_delivered_unit(self):
        job = self.job()
        cancel_outbound(self.manager, job.pk, {'reason': 'Préparer le cas échange synthétique'})
        record = job.service_request
        replacement = Equipment.objects.create(client=self.company, serial_number='BL-REPLACEMENT-LAB', model='Nouveau modèle', brand='Marque neuve')
        ExchangeProcess.objects.create(service_request=record, replacement_equipment=replacement,
            replacement_serial_number=replacement.serial_number, replacement_model=replacement.model, replacement_brand=replacement.brand,
            validated_at=timezone.now(), validated_by=self.manager, ready_at=timezone.now(), ready_by=self.manager)
        job = assign_outbound(self.manager, {'service_request': record.pk, 'courier': self.courier.pk})
        accept_outbound(self.courier, job.pk, job.assignment_revision, True)
        prepared = self.prepare([job])
        self.assertEqual(prepared.status_code, 201, prepared.data)
        line = prepared.data['lines'][0]
        self.assertEqual(line['serial_number'], replacement.serial_number)
        self.assertEqual(line['original_serial_number'], record.equipment.serial_number)

    def test_strict_bounded_input_and_atomic_failure(self):
        job = self.job()
        for extra in [{'quantity': 2}, {'comment': 42}, {'job_ids': [job.pk, job.pk]}, {'job_ids': [True]}, {'job_ids': []}, {'job_ids': [job.pk] * 101}]:
            body = {'request_key': str(uuid4()), 'job_ids': [job.pk], **extra}
            self.assertEqual(self.api.post(BASE, body, format='json').status_code, 400)
        with patch('core.logistics_delivery_note_pdf.render_delivery_note', side_effect=ValueError('Synthetic rendering failure')):
            with self.assertRaises(ValueError):
                create_note(self.courier, request_key=uuid4(), job_ids=[job.pk])
        self.assertEqual(DeliveryNote.objects.count(), 0)
        self.assertEqual(DeliveryNoteMission.objects.count(), 0)

    @skipUnless(connection.vendor == 'postgresql', 'Protection SQL PostgreSQL réelle')
    def test_sql_protects_snapshot_base_lines_and_job_identity(self):
        prepared = self.prepare([self.job()]).data
        note = LogisticsDeliveryNote.objects.get(pk=prepared['id'])
        attempts = [lambda: LogisticsDeliveryNote.objects.filter(pk=note.pk).update(snapshot={}),
                    lambda: LogisticsDeliveryNote.objects.filter(pk=note.pk).update(pdf_data=b'forged'),
                    lambda: DeliveryNote.objects.filter(pk=note.pk).update(status='delivered'),
                    lambda: DeliveryLine.objects.filter(delivery_note_id=note.pk).update(quantity=7),
                    lambda: DeliveryLine.objects.filter(delivery_note_id=note.pk).delete(),
                    lambda: DeliveryNoteMission.objects.filter(note=note).update(assignment_revision=999),
                    lambda: DeliveryNoteMission.objects.filter(note=note).update(active=False)]
        for operation in attempts:
            with self.assertRaises(DatabaseError), transaction.atomic():
                operation()


@skipUnless(connection.vendor == 'postgresql', 'Verrous PostgreSQL réels')
class ConcurrentLogisticsDeliveryNoteTests(NoteFactory, TransactionTestCase):
    def setUp(self):
        self.manager = User.objects.create_user('bl-race-manager', role='manager')
        self.courier = User.objects.create_user('bl-race-courier', role='courier')
        self.other = User.objects.create_user('bl-race-other', role='courier')
        self.company = Client.objects.create(name='Lot concurrent fictif', address='Adresse fictive')

    def parallel(self, functions):
        ready = Barrier(len(functions))
        def run(function):
            try:
                ready.wait(timeout=10)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions, timeout=30))

    def test_same_request_key_concurrently_returns_one_original_and_one_replay(self):
        job = self.job()
        key = uuid4()
        outputs = self.parallel([lambda: create_note(self.courier, request_key=key, job_ids=[job.pk]), lambda: create_note(self.courier, request_key=key, job_ids=[job.pk])])
        self.assertCountEqual([item['created'] for item in outputs], [True, False])
        self.assertEqual(LogisticsDeliveryNote.objects.count(), 1)

    def test_overlapping_lots_never_issue_two_active_notes_for_same_job(self):
        a, b, c = self.job(), self.job(), self.job()
        def prepare(ids):
            try:
                return create_note(self.courier, request_key=uuid4(), job_ids=ids)['id']
            except DeliveryNoteConflict:
                return 'conflict'
        outputs = self.parallel([lambda: prepare([a.pk, b.pk]), lambda: prepare([b.pk, c.pk])])
        self.assertEqual(outputs.count('conflict'), 1)
        self.assertEqual(LogisticsDeliveryNote.objects.count(), 1)
        self.assertEqual(DeliveryNoteMission.objects.filter(job=b, active=True).count(), 1)

    def test_two_reassignments_of_same_lot_do_not_lock_other_sav_via_event_fk(self):
        a, b = self.job(), self.job()
        prepared = create_note(self.courier, request_key=uuid4(), job_ids=[a.pk, b.pk])
        # Both actors own their SAV/job before reaching the shared note. The
        # invalidation must never insert an event requiring the other SAV lock.
        at_invalidation = Barrier(2)
        from core import logistics_delivery_notes as service
        original = service.invalidate_delivery_notes_for_job
        def synchronized(job, **kwargs):
            at_invalidation.wait(timeout=10)
            return original(job, **kwargs)
        def reassign(job):
            with transaction.atomic():
                ServiceRequest.objects.select_for_update().get(pk=job.service_request_id)
                current = OutboundJob.objects.select_for_update().get(pk=job.pk)
                current.assigned_courier = self.other
                current.save(update_fields=['assigned_courier'])
                return current.assignment_revision
        with patch('core.logistics_delivery_notes.invalidate_delivery_notes_for_job', side_effect=synchronized):
            results = self.parallel([lambda: reassign(a), lambda: reassign(b)])
        self.assertEqual(results, [2, 2])
        self.assertEqual(LogisticsDeliveryNote.objects.get(pk=prepared['id']).state, 'cancelled')
        self.assertEqual(DeliveryNoteMission.objects.filter(active=True).count(), 0)
