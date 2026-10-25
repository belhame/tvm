"""Intake tests use fictional catalogue fixtures and isolated test databases."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from core.catalogue_models import CatalogueProduct
from core.catalogue_service import import_catalogue
from core.intake_service import IntakeConflict, add_calendar_months, create_intake
from core.models import AuditLog, Client, Contract, Equipment, ServiceRequest, Warranty


FIXTURE = Path(__file__).with_name('fixtures') / 'request_intake_synthetic.xls'


class CalendarMonthTests(SimpleTestCase):
    def test_calendar_months_clamp_without_using_180_days(self):
        self.assertEqual(add_calendar_months(date(2020, 8, 31), 6), date(2021, 2, 28))
        self.assertEqual(add_calendar_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_calendar_months(date(2023, 12, 4), 6), date(2024, 6, 4))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Client du laboratoire intake')
        cls.other_company = Client.objects.create(name='Autre client du laboratoire')
        cls.admin = User.objects.create_user('intake-admin', password='TestingIntake42!', role='admin')
        cls.manager = User.objects.create_user('intake-manager', password='TestingIntake42!', role='manager')
        cls.tech = User.objects.create_user('intake-tech', password='TestingIntake42!', role='technician')
        cls.customer = User.objects.create_user('intake-client', password='TestingIntake42!', role='client', client=cls.company)
        cls.snapshot = import_catalogue(FIXTURE.read_bytes(), FIXTURE.name, actor=cls.admin).snapshot
        cls.product = cls.snapshot.products.get(product_code='AB2')
        cls.reference = cls.snapshot.warranties.get(product_name='Laboratoire Garantie')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.payload = {
            'request_key': str(uuid4()), 'serial_number': 'LAB2A49123', 'client': self.company.pk,
            'profile': 'Eaton', 'catalogue_import_id': self.snapshot.pk,
            'subject': 'Alarme de l’onduleur fictif', 'description': 'Signalement du laboratoire.', 'priority': 'high',
        }

    def post(self, **changes):
        return self.api.post('/api/requests/intake/', {**self.payload, **changes}, format='json')

    def test_real_lookup_creates_equipment_request_and_warranty_atomically(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        equipment = Equipment.objects.get(pk=response.data['equipment']['id'])
        request = ServiceRequest.objects.get(pk=response.data['request']['id'])
        warranty = Warranty.objects.get(equipment=equipment)
        self.assertEqual(equipment.model, 'LAB850F')
        self.assertEqual(equipment.brand, 'Eaton')
        self.assertEqual(equipment.catalogue_product_id, self.product.pk)
        self.assertEqual(equipment.manufactured_on, date(2023, 12, 4))
        self.assertEqual(equipment.warranty_until, date(2026, 6, 4))
        self.assertEqual((warranty.starts_on, warranty.ends_on), (date(2024, 6, 4), date(2026, 6, 4)))
        self.assertEqual(warranty.scope, 'unspecified')
        self.assertIn('+ 6 mois calendaires', warranty.terms)
        self.assertIn(self.snapshot.sha256, warranty.terms)
        self.assertEqual(request.equipment_id, equipment.pk)
        self.assertEqual(request.requested_by_id, self.admin.pk)
        self.assertEqual(str(request.intake_key), self.payload['request_key'])
        self.assertEqual(response.data['intake']['selected_product']['id'], self.product.pk)
        self.assertEqual(response.data['intake']['computed_warranty']['starts_on'], '2024-06-04')
        self.assertTrue(response.data['intake']['computed_warranty']['applied_to_equipment'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_same_key_actor_and_payload_replay_without_lookup_or_new_writes(self):
        first = self.post()
        counts = (Equipment.objects.count(), ServiceRequest.objects.count(), Warranty.objects.count(), AuditLog.objects.count())
        with patch('core.intake_service._lookup_serial', side_effect=AssertionError('Replay must not rerun lookup')):
            second = self.post()
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data['created'])
        self.assertEqual(second.data['request']['id'], first.data['request']['id'])
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count(), Warranty.objects.count(), AuditLog.objects.count()), counts)

    def test_unusable_or_overlong_short_reference_falls_back_without_truncation(self):
        for reference in ('NA', 'R' * 121):
            with self.subTest(reference_length=len(reference)):
                self.product.catalogue_number = reference
                self.product.save(update_fields=['catalogue_number'])
                response = self.post(request_key=str(uuid4()), serial_number='LAB2A4912' + ('3' if reference == 'NA' else '4'))
                self.assertEqual(response.status_code, 201, response.data)
                equipment = Equipment.objects.get(pk=response.data['equipment']['id'])
                self.assertEqual(equipment.model, self.product.product_name)
                self.assertEqual(response.data['intake']['selected_product']['catalogue_number'], reference)

    def test_catalogue_choice_unproven_by_serial_requires_explicit_manual_reason(self):
        response = self.post(serial_number='UNKNOWN-LAB-SERIAL', product_id=self.product.pk)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('manual_reason', response.data)
        self.assertFalse(Equipment.objects.exists())
        response = self.post(
            serial_number='UNKNOWN-LAB-SERIAL', product_id=self.product.pk,
            manual_reason='La référence a été vérifiée sur la plaque physique.',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Equipment.objects.get().model, 'LAB850F')
        self.assertIsNone(Equipment.objects.get().manufactured_on)
        self.assertFalse(Warranty.objects.exists())

    def test_same_key_with_changed_payload_is_a_non_disclosing_conflict(self):
        first = self.post()
        response = self.post(subject='Un autre dossier')
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(first.data['request']['reference'], str(response.data))
        self.assertNotIn('LAB850F', str(response.data))
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_same_key_reused_by_another_actor_does_not_disclose_existing_request(self):
        first = self.post()
        self.api.force_authenticate(self.manager)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(first.data['request']['reference'], str(response.data))
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_default_values_and_case_normalization_are_stable_for_retry(self):
        self.payload.pop('description')
        self.payload.pop('priority')
        first = self.post()
        response = self.post(serial_number='lab2a49123', description='', priority='normal')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['request']['id'], first.data['request']['id'])

    def test_technician_can_open_request_for_existing_equipment_without_changing_it(self):
        equipment = Equipment.objects.create(
            client=self.company, serial_number='EXISTING-INTAKE-001', model='Modèle déjà enregistré',
            manufactured_on=date(2020, 1, 2), warranty_until=date(2030, 4, 5), catalogue_product=self.product,
        )
        warranty = Warranty.objects.create(
            equipment=equipment, starts_on=date(2021, 3, 4), ends_on=date(2030, 4, 5),
            scope='unspecified', provider='Contrat enregistré', terms='Conditions préexistantes',
        )
        Contract.objects.create(
            number='CONTRACT-INTAKE-EXISTING', client=self.company, equipment=equipment,
            starts_on=date(2020, 1, 1), ends_on=date(2030, 1, 1), status='active',
        )
        before_equipment = Equipment.objects.values().get(pk=equipment.pk)
        before_warranty = Warranty.objects.values().get(pk=warranty.pk)
        self.api.force_authenticate(self.tech)
        response = self.post(serial_number=equipment.serial_number, equipment=equipment.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['created_equipment'])
        self.assertIsNone(response.data['warranty'])
        self.assertEqual(Equipment.objects.values().get(pk=equipment.pk), before_equipment)
        self.assertEqual(Warranty.objects.values().get(pk=warranty.pk), before_warranty)
        self.assertEqual((Equipment.objects.count(), Warranty.objects.count(), Contract.objects.count()), (1, 1, 1))
        summary = response.data['intake']
        self.assertEqual(summary['computed_warranty']['status'], 'recorded_priority')
        self.assertEqual(summary['computed_warranty']['starts_on'], '2021-03-04')
        self.assertEqual(summary['computed_warranty']['ends_on'], '2030-04-05')
        self.assertFalse(summary['computed_warranty']['applied_to_equipment'])
        self.assertEqual(summary['recorded_warranties'][0]['scope'], 'unspecified')
        self.assertIn('catalogue_estimate', summary)
        self.assertNotIn('history', summary)

    def test_recorded_battery_dates_are_not_reused_for_unspecified_catalogue_coverage(self):
        equipment = Equipment.objects.create(
            client=self.company, serial_number='BATTERY-ONLY-EXISTING', model='Modèle conservé',
            catalogue_product=self.product, manufactured_on=date(2020, 1, 2),
        )
        warranty = Warranty.objects.create(
            equipment=equipment, starts_on=date(2021, 3, 4), ends_on=date(2030, 4, 5),
            scope='batteries', provider='Couverture batterie enregistrée',
        )
        response = self.post(serial_number=equipment.serial_number, equipment=equipment.pk)
        self.assertEqual(response.status_code, 201, response.data)
        summary = response.data['intake']
        self.assertEqual(summary['computed_warranty']['status'], 'recorded_priority')
        self.assertIsNone(summary['computed_warranty']['starts_on'])
        self.assertIsNone(summary['computed_warranty']['ends_on'])
        self.assertEqual(summary['computed_warranty']['coverage_status'], 'unknown')
        self.assertEqual(summary['recorded_warranties'][0]['scope'], 'batteries')
        self.assertEqual(summary['recorded_warranties'][0]['starts_on'], '2021-03-04')
        self.assertEqual(Warranty.objects.get(pk=warranty.pk).ends_on, date(2030, 4, 5))
        self.assertEqual(Warranty.objects.count(), 1)

    def test_serial_alone_reuses_existing_equipment_case_insensitively(self):
        equipment = Equipment.objects.create(client=self.company, serial_number='ALREADY-001', model='Ancien modèle')
        self.api.force_authenticate(self.tech)
        response = self.post(serial_number='already-001')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['request']['equipment'], equipment.pk)
        self.assertEqual(Equipment.objects.count(), 1)

    def test_unicode_casefold_expansion_does_not_merge_distinct_physical_serials(self):
        equipment = Equipment.objects.create(client=self.company, serial_number='UNICODE-ß', model='Modèle observé')
        first = self.post(serial_number=equipment.serial_number, equipment=equipment.pk)
        self.assertEqual(first.status_code, 201, first.data)
        replay = self.post(serial_number='UNICODE-SS', equipment=equipment.pk)
        self.assertEqual(replay.status_code, 409)
        mismatch = self.post(request_key=str(uuid4()), serial_number='UNICODE-SS', equipment=equipment.pk)
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn('equipment', mismatch.data)
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_technician_cannot_create_equipment_through_intake(self):
        self.api.force_authenticate(self.tech)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Equipment.objects.exists())
        self.assertFalse(ServiceRequest.objects.exists())

    def test_clients_and_anonymous_users_cannot_use_internal_intake(self):
        for actor in (self.customer, None):
            self.api.force_authenticate(actor)
            response = self.post()
            self.assertIn(response.status_code, (401, 403))
        self.assertFalse(Equipment.objects.exists())

    def test_existing_equipment_cannot_be_reparented_or_mismatched_with_serial(self):
        equipment = Equipment.objects.create(client=self.other_company, serial_number='OTHER-OWNER', model='Modèle propriétaire')
        response = self.post(serial_number='OTHER-OWNER', equipment=equipment.pk)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('client', response.data)
        response = self.post(equipment=equipment.pk, client=self.other_company.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('equipment', response.data)
        equipment.refresh_from_db()
        self.assertEqual(equipment.client_id, self.other_company.pk)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_new_equipment_requires_a_valid_owner(self):
        for client in (None, 9_000_000):
            with self.subTest(client=client):
                response = self.post(client=client)
                self.assertEqual(response.status_code, 400)
                self.assertIn('client', response.data)
        self.assertFalse(Equipment.objects.exists())

    def test_ambiguous_product_does_not_silently_take_first_candidate(self):
        response = self.post(serial_number='LQX1A49123')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('product_id', response.data)
        self.assertFalse(Equipment.objects.exists())
        variant = self.snapshot.products.get(source_row=3)
        response = self.post(serial_number='LQX1A49123', product_id=variant.pk)
        self.assertEqual(response.status_code, 201, response.data)
        equipment = Equipment.objects.get()
        self.assertEqual(equipment.model, 'DEMO-002')
        self.assertEqual(equipment.catalogue_product_id, variant.pk)

    def test_product_or_warranty_id_from_wrong_candidate_is_rejected(self):
        wrong_product = self.snapshot.products.get(source_row=2)
        wrong_warranty = self.snapshot.warranties.get(source_row=6, source_column='H')
        for changes in ({'product_id': wrong_product.pk}, {'warranty_reference_id': wrong_warranty.pk}):
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Equipment.objects.exists())
        self.assertFalse(Warranty.objects.exists())

    def test_manual_unknown_model_requires_reason_and_preserves_provenance(self):
        response = self.post(
            serial_number='UNKNOWN-LAB-SERIAL', profile=None, manual_model='Modèle observé sur étiquette',
            manufactured_on_override='2024-08-31', duration_months_override=12,
            manual_reason='Étiquette et facture contrôlées au laboratoire.',
        )
        self.assertEqual(response.status_code, 201, response.data)
        equipment = Equipment.objects.get()
        self.assertEqual(equipment.brand, 'À confirmer')
        self.assertEqual(equipment.model, 'Modèle observé sur étiquette')
        self.assertIsNone(equipment.catalogue_product_id)
        warranty = Warranty.objects.get()
        self.assertEqual((warranty.starts_on, warranty.ends_on), (date(2025, 2, 28), date(2026, 2, 28)))
        self.assertNotIn('Étiquette et facture', warranty.terms)
        self.assertIn('Étiquette et facture', ServiceRequest.objects.get().intake_data['summary']['manual_reason'])
        self.assertEqual(response.data['intake']['manufacture_date_basis']['type'], 'manual')
        self.api.force_authenticate(self.customer)
        visible = self.api.get('/api/warranties/')
        self.assertEqual(visible.status_code, 200)
        self.assertNotIn('Étiquette et facture', str(visible.data))

    def test_manual_values_without_reason_are_refused_before_any_write(self):
        response = self.post(manufactured_on_override='2024-08-31')
        self.assertEqual(response.status_code, 400)
        self.assertIn('manual_reason', response.data)
        self.assertFalse(Equipment.objects.exists())

    def test_technician_cannot_override_manufacture_or_coverage(self):
        equipment = Equipment.objects.create(client=self.company, serial_number='EXISTING-TECH', model='Technicien')
        self.api.force_authenticate(self.tech)
        response = self.post(
            equipment=equipment.pk, serial_number=equipment.serial_number,
            manufactured_on_override='2020-01-01', manual_reason='Tentative de correction.',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_manual_start_cannot_bypass_six_calendar_month_rule(self):
        response = self.post(warranty_start_override='2024-01-01', manual_reason='Date saisie au laboratoire.')
        self.assertEqual(response.status_code, 400)
        self.assertIn('warranty_start_override', response.data)
        self.assertFalse(Equipment.objects.exists())

    def test_manual_duration_cannot_contradict_selected_reference(self):
        response = self.post(duration_months_override=12, manual_reason='Durée supposée.')
        self.assertEqual(response.status_code, 400)
        self.assertIn('duration_months_override', response.data)
        self.assertFalse(Equipment.objects.exists())

    def test_zero_months_creates_no_warranty_or_one_day_coverage(self):
        self.reference.duration_months = 0
        self.reference.save(update_fields=['duration_months'])
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(Warranty.objects.exists())
        self.assertIsNone(Equipment.objects.get().warranty_until)
        computed = response.data['intake']['computed_warranty']
        self.assertEqual(computed['status'], 'no_coverage')
        self.assertEqual(computed['coverage_status'], 'not_covered')
        self.assertIsNone(computed['starts_on'])
        self.assertIsNone(computed['ends_on'])

    def test_future_coverage_is_not_reported_as_active(self):
        response = self.post(manufactured_on_override='2090-01-01', manual_reason='Scénario futur entièrement fictif.')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['intake']['computed_warranty']['coverage_status'], 'not_started')

    def test_component_scope_is_retained_from_the_selected_reference(self):
        self.reference.scope = 'batteries'
        self.reference.save(update_fields=['scope'])
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Warranty.objects.get().scope, 'batteries')
        self.assertEqual(response.data['warranty']['scope'], 'batteries')

    def test_request_failure_rolls_back_new_equipment_warranty_and_audit(self):
        before = (Equipment.objects.count(), Warranty.objects.count(), AuditLog.objects.count())
        with patch('core.intake_service.ServiceRequest.objects.create', side_effect=RuntimeError('synthetic request failure')):
            with self.assertRaisesMessage(RuntimeError, 'synthetic request failure'):
                create_intake(self.payload, actor=self.admin)
        self.assertEqual((Equipment.objects.count(), Warranty.objects.count(), AuditLog.objects.count()), before)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_integrity_failure_is_safe_conflict_and_rolls_back_all_new_rows(self):
        before = (Equipment.objects.count(), Warranty.objects.count(), AuditLog.objects.count())
        with patch('core.intake_service.ServiceRequest.objects.create', side_effect=IntegrityError('synthetic constraint failure')):
            response = self.post()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual((Equipment.objects.count(), Warranty.objects.count(), AuditLog.objects.count()), before)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_private_catalogue_intake_json_is_never_visible_in_client_portal(self):
        created = self.post()
        self.assertEqual(created.status_code, 201, created.data)
        request_id = created.data['request']['id']
        equipment_id = created.data['equipment']['id']
        self.api.force_authenticate(self.customer)
        detail = self.api.get(f'/api/requests/{request_id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn('intake_data', detail.data)
        self.assertNotIn('intake_key', detail.data)
        equipment = self.api.get(f'/api/equipment/{equipment_id}/')
        self.assertNotIn('catalogue_product', equipment.data)
        search = self.api.get('/api/search/?q=LAB2')
        self.assertNotIn('intake_data', str(search.data))
        self.assertNotIn(self.snapshot.sha256, str(search.data))

    def test_intake_fields_cannot_be_forged_through_generic_crud(self):
        created = self.post()
        request_id = created.data['request']['id']
        equipment_id = created.data['equipment']['id']
        response = self.api.patch(f'/api/requests/{request_id}/', {'intake_data': {'injected': True}, 'intake_key': str(uuid4())}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('injected', ServiceRequest.objects.get(pk=request_id).intake_data)
        self.assertEqual(str(ServiceRequest.objects.get(pk=request_id).intake_key), self.payload['request_key'])
        response = self.api.patch(f'/api/equipment/{equipment_id}/', {'manufactured_on': '1901-01-01', 'catalogue_product': None}, format='json')
        self.assertEqual(response.status_code, 200)
        equipment = Equipment.objects.get(pk=equipment_id)
        self.assertEqual(equipment.manufactured_on, date(2023, 12, 4))
        self.assertEqual(equipment.catalogue_product_id, self.product.pk)

    def test_unknown_fields_or_invalid_uuid_are_refused(self):
        for changes in ({'intake_data': {'forged': True}}, {'request_key': 'not-a-uuid'}, {'duration_months_override': -1}):
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Equipment.objects.exists())


@skipUnless(connection.vendor == 'postgresql', 'Les courses de création exigent PostgreSQL.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IntakeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user('intake-concurrent', role='admin')
        self.company = Client.objects.create(name='Client concurrence fictif')
        self.snapshot = import_catalogue(FIXTURE.read_bytes(), FIXTURE.name, actor=self.actor).snapshot
        self.payload = {
            'request_key': str(uuid4()), 'serial_number': 'LAB2A49123', 'client': self.company.pk,
            'subject': 'Création simultanée fictive', 'profile': 'Eaton', 'catalogue_import_id': self.snapshot.pk,
        }

    def race(self, payloads):
        from core.serial_lookup import lookup_serial
        barrier = Barrier(2)

        def synchronized_lookup(data):
            lookup = lookup_serial(
                data['serial_number'], profile=data.get('profile'), product_id=data.get('product_id'),
                catalogue_import_id=data.get('catalogue_import_id'), warranty_reference_id=data.get('warranty_reference_id'),
            )
            barrier.wait(timeout=15)
            return lookup

        def save(payload):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                try:
                    result = create_intake(payload, actor=actor)
                    return ('created' if result.created else 'replayed', result.request.pk)
                except IntakeConflict:
                    return ('conflict', None)
            finally:
                connections.close_all()

        with patch('core.intake_service._lookup_serial', side_effect=synchronized_lookup):
            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(save, payloads, timeout=40))

    def test_concurrent_identical_key_replays_one_atomic_request(self):
        outcomes = self.race([dict(self.payload), dict(self.payload)])
        self.assertCountEqual([kind for kind, _ in outcomes], ['created', 'replayed'])
        self.assertEqual(len({pk for _, pk in outcomes}), 1)
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count(), Warranty.objects.count()), (1, 1, 1))

    def test_two_keys_cannot_create_case_variant_serial_duplicates_or_orphans(self):
        other = {**self.payload, 'request_key': str(uuid4()), 'serial_number': self.payload['serial_number'].lower()}
        outcomes = self.race([dict(self.payload), other])
        self.assertCountEqual([kind for kind, _ in outcomes], ['created', 'conflict'])
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count(), Warranty.objects.count()), (1, 1, 1))
