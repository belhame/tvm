from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.request_assignment import assign_request, confirm_assignment, takeover_request
from core.request_batteries import battery_configuration_payload, equipment_battery_configuration, serializer_battery_payload
from core.request_tracking import write_followup
from core.serializers import ServiceRequestSerializer


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RequestBatteryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('battery-lab-admin', role='admin')
        cls.tech = User.objects.create_user('battery-lab-tech', role='technician')
        cls.next_tech = User.objects.create_user('battery-lab-next-tech', role='technician')
        cls.courier = User.objects.create_user('battery-lab-courier', role='courier')
        cls.company = Client.objects.create(name='Client batteries du laboratoire')
        cls.customer = User.objects.create_user('battery-lab-customer', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='BATTERY-LAB-001', model='5E700FG2')
        cls.record = ServiceRequest.objects.create(equipment=cls.unit, subject='Batteries de laboratoire')

    def assign(self):
        self.record.refresh_from_db()
        self.record = assign_request(self.record.pk, actor=self.admin, technician_id=self.tech.pk, expected_revision=self.record.assignment_revision)
        return self.record

    def accept(self):
        self.assign()
        self.record = confirm_assignment(self.record.pk, actor=self.tech, expected_revision=self.record.assignment_revision, accept=True)
        return self.record

    def payload(self, **changes):
        self.record.refresh_from_db()
        return dict(status=self.record.status, expected_status=self.record.status, assignment_revision=self.record.assignment_revision,
                    observation='Nombre vérifié sur l’équipement du laboratoire.', **changes)

    def test_reception_assignment_and_read_do_not_initialize_before_acceptance(self):
        self.assertIsNone(self.record.battery_count)
        self.assertIsNone(battery_configuration_payload(self.record))
        self.assign()
        self.assertIsNone(battery_configuration_payload(self.record))
        self.record.refresh_from_db()
        self.assertEqual(self.record.battery_reference, {})

    def test_new_acceptance_proposes_nominal_with_private_provenance(self):
        self.accept()
        self.assertEqual((self.record.battery_count, self.record.battery_count_source), (1, 'reference'))
        self.assertEqual(self.record.battery_reference['nominal_count'], 1)
        events = self.record.operation_events.filter(kind='battery_reference')
        self.assertEqual(events.count(), 1)
        self.assertTrue(events.get().is_internal)
        before = self.record.updated_at
        confirm_assignment(self.record.pk, actor=self.tech, expected_revision=self.record.assignment_revision, accept=True)
        self.record.refresh_from_db()
        self.assertEqual(self.record.updated_at, before)
        self.assertEqual(events.count(), 1)

    def test_old_accepted_request_gets_read_only_advice_without_backfill(self):
        self.assign()
        stamp = timezone.now()
        ServiceRequest.objects.filter(pk=self.record.pk).update(assignment_accepted_at=stamp, assignment_accepted_by=self.tech, assignment_accepted_revision=self.record.assignment_revision)
        self.record.refresh_from_db()
        before = (self.record.updated_at, self.record.battery_reference, self.record.operation_events.count())
        self.assertEqual(battery_configuration_payload(self.record)['nominal_count'], 1)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.battery_count)
        self.assertEqual((self.record.updated_at, self.record.battery_reference, self.record.operation_events.count()), before)

    def test_existing_intervention_counts_are_not_overwritten_or_preempted(self):
        sheet = Intervention.objects.create(service_request=self.record, battery_count=7)
        self.accept()
        self.assertIsNone(self.record.battery_count)
        self.assertEqual(battery_configuration_payload(self.record)['recorded_intervention_counts'][0]['battery_count'], 7)
        write_followup(self.record.pk, self.payload(battery_count=2), actor=self.tech)
        sheet.refresh_from_db()
        self.assertEqual(sheet.battery_count, 7)

    def test_same_nominal_value_requires_explicit_confirmation_for_manual_source(self):
        self.accept()
        result = write_followup(self.record.pk, self.payload(battery_count=1), actor=self.tech)
        self.assertEqual(result.service_request.battery_count_source, 'manual')
        self.assertTrue(any(event.kind == 'battery_count' and event.is_internal for event in result.events))

    def test_count_is_editable_only_after_acceptance_with_followup_permissions(self):
        self.assign()
        with self.assertRaises(PermissionDenied):
            write_followup(self.record.pk, self.payload(battery_count=2), actor=self.tech)
        self.accept()
        for actor in (self.next_tech, self.courier, self.customer):
            with self.assertRaises(PermissionDenied):
                write_followup(self.record.pk, self.payload(battery_count=2), actor=actor)
        self.record.refresh_from_db()
        self.assertEqual(self.record.battery_count, 1)

    def test_count_input_is_strict_and_needs_observation_or_summary(self):
        self.accept()
        for invalid in (True, '2', 2.5, -1, 100001, {}, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                write_followup(self.record.pk, self.payload(battery_count=invalid), actor=self.tech)
        payload = self.payload(battery_count=3)
        payload['observation'] = ''
        with self.assertRaises(ValidationError):
            write_followup(self.record.pk, payload, actor=self.tech)

    def test_zero_internal_with_external_bank_does_not_set_zero_total(self):
        self.unit.model = '9PX 6kVA 3:1'
        self.unit.save(update_fields=['model'])
        self.accept()
        self.assertIsNone(self.record.battery_count)
        self.assertTrue(self.record.battery_reference['external_battery_required'])
        self.assertEqual(self.record.battery_reference['nominal_count'], 0)

    def test_takeover_keeps_confirmed_count_and_old_technician_loses_write(self):
        self.accept()
        write_followup(self.record.pk, self.payload(battery_count=4), actor=self.tech)
        self.record.refresh_from_db()
        result = takeover_request(self.record.pk, actor=self.next_tech, expected_revision=self.record.assignment_revision, reason='Relève de laboratoire')
        self.assertEqual((result.battery_count, result.battery_count_source), (4, 'manual'))
        with self.assertRaises(PermissionDenied):
            write_followup(self.record.pk, self.payload(battery_count=5), actor=self.tech)

    def test_stale_model_and_brand_keep_snapshot_but_warn(self):
        self.accept()
        self.unit.brand = 'Other'
        self.unit.save(update_fields=['brand'])
        self.record.refresh_from_db()
        self.assertEqual(battery_configuration_payload(self.record)['status'], 'stale')
        self.assertEqual(self.record.battery_reference['status'], 'matched')

    def test_internal_count_and_reference_are_hidden_from_client_serialization(self):
        self.accept()
        for actor in (self.customer, self.courier):
            data = ServiceRequestSerializer(self.record, context={'request': SimpleNamespace(user=actor)}).data
            self.assertFalse({'battery_count', 'battery_count_source', 'battery_configuration', 'battery_reference'} & set(data))

    def test_count_and_state_are_atomic_if_save_fails(self):
        self.accept()
        before = self.record.operation_events.count()
        with patch.object(ServiceRequest, 'save', side_effect=RuntimeError('Fictional persistence failure')):
            with self.assertRaises(RuntimeError):
                write_followup(self.record.pk, self.payload(battery_count=6), actor=self.tech)
        self.record.refresh_from_db()
        self.assertEqual((self.record.battery_count, self.record.battery_count_source), (1, 'reference'))
        self.assertEqual(self.record.operation_events.count(), before)

    def test_unique_serial_reference_qualifies_old_model_without_linking_or_saving_equipment(self):
        self.unit.model = '5E700F'
        self.unit.save(update_fields=['model'])
        product = SimpleNamespace(pk=700001, snapshot_id=700002, catalogue_number='5E700F', product_name='Eaton 5E 700 FR G2', range_name='5E G2', version='G2')
        before = list(self.unit.operation_events.filter(service_request__isnull=True).values('id', 'summary'))
        with patch('core.serial_lookup.find_serial_product', return_value=product):
            result = equipment_battery_configuration(self.unit)
            self.assertEqual((result['status'], result['nominal_count']), ('matched', 1))
            self.assertEqual(result['identified_catalogue_product_id'], product.pk)
            self.accept()
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.model, '5E700F')
        self.assertIsNone(self.unit.catalogue_product_id)
        self.assertEqual(self.record.battery_count, 1)
        # New acceptance logs SAV actions only; it does not rewrite the unit.
        self.assertEqual(list(self.unit.operation_events.filter(service_request__isnull=True).values('id', 'summary')), before)

    def test_serial_fallback_does_not_qualify_conflicting_or_unknown_recorded_model(self):
        product = SimpleNamespace(pk=700001, snapshot_id=700002, catalogue_number='5E700F', product_name='Eaton 5E 700 FR G2', range_name='5E G2', version='G2')
        for model in ('Unknown laboratory model', '5E900F'):
            self.unit.model = model
            with patch('core.serial_lookup.find_serial_product', return_value=product):
                self.assertEqual(equipment_battery_configuration(self.unit)['status'], 'unknown')

    def test_generic_request_patch_cannot_write_nominal_or_private_reference(self):
        self.accept()
        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.patch(f'/api/requests/{self.record.pk}/', {'battery_count': 99, 'battery_count_source': 'manual', 'battery_reference': {'nominal_count': 99}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.record.refresh_from_db()
        self.assertEqual((self.record.battery_count, self.record.battery_count_source), (1, 'reference'))

    def test_new_intervention_reuses_only_confirmed_request_count(self):
        self.accept()
        api = APIClient()
        api.force_authenticate(self.tech)
        nominal = api.post('/api/interventions/', {'service_request': self.record.pk}, format='json')
        self.assertEqual(nominal.status_code, 201, nominal.data)
        self.assertIsNone(nominal.data['battery_count'])
        write_followup(self.record.pk, self.payload(battery_count=3), actor=self.tech)
        observed = api.post('/api/interventions/', {'service_request': self.record.pk}, format='json')
        self.assertEqual(observed.status_code, 201, observed.data)
        self.assertEqual(observed.data['battery_count'], 3)
        explicit = api.post('/api/interventions/', {'service_request': self.record.pk, 'battery_count': 4}, format='json')
        self.assertEqual(explicit.data['battery_count'], 4)

    def test_nominal_and_real_count_not_shared_in_public_timeline(self):
        self.accept()
        write_followup(self.record.pk, self.payload(battery_count=4), actor=self.tech)
        public = self.record.operation_events.filter(is_internal=False)
        self.assertFalse(public.filter(kind__in=['battery_count', 'battery_reference']).exists())

    def test_sql_rejects_out_of_range_count_and_unknown_source(self):
        for updates in ({'battery_count': -1}, {'battery_count': 100001}, {'battery_count_source': 'forged'}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ServiceRequest.objects.filter(pk=self.record.pk).update(**updates)

    def test_collection_battery_metadata_uses_two_batched_queries(self):
        self.accept()
        second = Equipment.objects.create(client=self.company, serial_number='BATTERY-LAB-002', model='5S700I')
        other = ServiceRequest.objects.create(equipment=second, subject='Deuxième laboratoire')
        other = assign_request(other.pk, actor=self.admin, technician_id=self.tech.pk, expected_revision=other.assignment_revision)
        other = confirm_assignment(other.pk, actor=self.tech, expected_revision=other.assignment_revision, accept=True)
        rows = list(ServiceRequest.objects.filter(pk__in=[self.record.pk, other.pk]))
        serializer = SimpleNamespace(context={}, parent=SimpleNamespace(instance=rows))
        with self.assertNumQueries(2):
            for row in rows:
                self.assertEqual(serializer_battery_payload(serializer, row)['status'], 'matched')
