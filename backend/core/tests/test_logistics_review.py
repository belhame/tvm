"""Independent courier isolation checks; all fixtures are fictional."""

from uuid import uuid4
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client as BrowserClient, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, RequestAttachment, ServiceRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentCourierIsolationReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Logistique Fictif', notes='PRIVATE_CUSTOMER_LOGISTICS_REVIEW', tax_id='00000042/PRIVATE')
        cls.admin = User.objects.create_user('logistics-review-admin', role='admin')
        cls.courier = User.objects.create_user('logistics-review-courier', role='courier')
        cls.customer = User.objects.create_user('logistics-review-client', role='client', client=cls.company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='LOGISTICS-REVIEW-UNIT-001', model='Modèle fictif')
        cls.request = ServiceRequest.objects.create(equipment=cls.unit, subject='PRIVATE_SERVICE_REQUEST_LOGISTICS_REVIEW')
        cls.visit = Intervention.objects.create(service_request=cls.request, diagnosis='PRIVATE_DIAGNOSIS_LOGISTICS_REVIEW', internal_notes='PRIVATE_TECHNICIAN_LOGISTICS_REVIEW')
        cls.document = RequestAttachment.objects.create(
            service_request=cls.request, stored_name=f'requests/{cls.request.pk}/{uuid4().hex}.txt',
            original_name='fictional-private.txt', label='PRIVATE_DOCUMENT_LOGISTICS_REVIEW',
            mime_type='text/plain', size_bytes=3, sha256='0' * 64,
            uploaded_by=cls.admin, uploaded_by_label='Auteur fictif',
        )

    def setUp(self):
        # A real Django session exercises the production middleware boundary,
        # rather than relying only on DRF's in-process force-auth helper.
        self.browser = BrowserClient(enforce_csrf_checks=True)
        self.browser.force_login(self.courier)
        self.token = self.browser.get('/api/session/').json()['csrfToken']

    def old_read_paths(self):
        request = self.request.pk
        visit = self.visit.pk
        return [
            '/api/', '/api/dashboard/', '/api/search/?q=PRIVATE',
            '/api/clients/', f'/api/clients/{self.company.pk}/',
            '/api/equipment/', f'/api/equipment/{self.unit.pk}/', f'/api/equipment/{self.unit.pk}/timeline/',
            '/api/requests/', '/api/requests/categories/', f'/api/requests/{request}/',
            f'/api/requests/{request}/timeline/', f'/api/requests/{request}/report/',
            '/api/interventions/', f'/api/interventions/{visit}/', f'/api/interventions/{visit}/report/',
            '/api/parts/', '/api/stock-movements/', '/api/contracts/', '/api/warranties/', '/api/delivery-notes/',
            '/api/users/', '/api/users/me/', f'/api/users/{self.admin.pk}/', '/api/audit/',
            '/api/catalogue/', '/api/catalogue/products/', '/api/catalogue/warranties/', '/api/integrations/',
            '/api/exchanges/', '/api/exchanges/billing/', f'/api/requests/{request}/exchange/',
            '/api/dispatch/ready/', '/api/dispatch/returns/', '/api/dispatch/billing/',
            f'/api/requests/{request}/disposition/', '/api/diagnostic-quotes/1/pdf/',
            f'/api/requests/{request}/documents/', f'/api/documents/{self.document.pk}/download/',
        ]

    def test_courier_cannot_read_or_discover_any_legacy_business_api_with_safe_methods(self):
        for path in self.old_read_paths():
            for method in ('get', 'head', 'options'):
                with self.subTest(method=method, path=path):
                    response = getattr(self.browser, method)(path)
                    self.assertEqual(response.status_code, 403, response.content[:300])
                    for private in (b'PRIVATE_CUSTOMER_LOGISTICS_REVIEW', b'PRIVATE_SERVICE_REQUEST_LOGISTICS_REVIEW', b'PRIVATE_DOCUMENT_LOGISTICS_REVIEW'):
                        self.assertNotIn(private, response.content)

    def test_courier_cannot_write_old_intake_finance_status_or_attachment_routes(self):
        bodies = [
            ('post', '/api/serial-analysis/', {'serial_number': self.unit.serial_number}),
            ('post', '/api/serial-lookup/', {'serial_number': self.unit.serial_number}),
            ('post', '/api/requests/intake/', {'request_key': str(uuid4()), 'serial_number': self.unit.serial_number, 'subject': 'FORGED'}),
            ('patch', f'/api/requests/{self.request.pk}/', {'status': 'closed', 'arrived_at': '2000-01-01T00:00:00Z'}),
            ('post', f'/api/requests/{self.request.pk}/timeline/', {'kind': 'status_changed', 'status_after': 'closed'}),
            ('post', f'/api/requests/{self.request.pk}/exchange/billing/', {'invoice_reference': 'FORGED', 'invoiced_on': '2025-10-15'}),
            ('post', f'/api/requests/{self.request.pk}/disposition/free/', {'reason': 'FORGED'}),
            ('delete', f'/api/documents/{self.document.pk}/', {}),
            ('patch', f'/api/users/{self.courier.pk}/', {'role': 'admin', 'can_validate_billing': True}),
        ]
        before = ServiceRequest.objects.count(), Equipment.objects.count(), Intervention.objects.count()
        for method, path, body in bodies:
            with self.subTest(method=method, path=path):
                response = getattr(self.browser, method)(path, body, content_type='application/json', HTTP_X_CSRFTOKEN=self.token)
                self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertEqual((ServiceRequest.objects.count(), Equipment.objects.count(), Intervention.objects.count()), before)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'new')
        self.assertIsNone(self.request.arrived_at)
        self.courier.refresh_from_db()
        self.assertEqual(self.courier.role, 'courier')
        self.assertFalse(self.courier.can_validate_billing)

    def test_courier_has_only_own_session_and_no_django_admin_even_with_fake_http_role_headers(self):
        response = self.browser.get('/api/session/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['id'], self.courier.pk)
        self.assertEqual(response.json()['user']['role'], 'courier')
        self.assertEqual(self.browser.get('/api/health/').status_code, 200)
        for path in ('/admin/', '/admin/core/client/', '/api/dashboard/'):
            response = self.browser.get(path, HTTP_X_ROLE='admin', HTTP_X_USER_ROLE='manager')
            self.assertEqual(response.status_code, 403)

    def test_database_forbids_privileged_staff_superuser_or_billing_flags_on_a_courier(self):
        for flag in ('is_staff', 'is_superuser', 'can_validate_billing'):
            with self.subTest(flag=flag), self.assertRaises(IntegrityError), transaction.atomic():
                get_user_model().objects.filter(pk=self.courier.pk).update(**{flag: True})
        self.courier.refresh_from_db()
        self.assertFalse(self.courier.is_staff)
        self.assertFalse(self.courier.is_superuser)
        self.assertFalse(self.courier.can_validate_billing)

    def test_client_cannot_use_internal_photo_recognition_or_minimal_receiving_api(self):
        api = APIClient()
        api.force_authenticate(self.customer)
        response = api.post('/api/logistics/recognize-serial/', {}, format='multipart')
        self.assertEqual(response.status_code, 403)
        response = api.post('/api/logistics/receive/', {'serial_number': self.unit.serial_number}, format='json')
        self.assertEqual(response.status_code, 403)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IndependentLogisticsWorkflowReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Centre Missions Fictif', address='Adresse de mission fictive', contact_name='Contact mission', notes='PRIVATE_LOGISTICS_CLIENT_NOTE', tax_id='000042/PRIVATE')
        cls.other_company = Client.objects.create(name='Autre Centre Missions Fictif')
        cls.admin = User.objects.create_user('missions-review-admin', role='admin')
        cls.courier = User.objects.create_user('missions-review-courier', role='courier')
        cls.other_courier = User.objects.create_user('missions-review-other-courier', role='courier')
        cls.tech = User.objects.create_user('missions-review-tech', role='technician')
        cls.customer = User.objects.create_user('missions-review-client', role='client', client=cls.company)
        cls.other_customer = User.objects.create_user('missions-review-other-client', role='client', client=cls.other_company)
        cls.unit = Equipment.objects.create(client=cls.company, serial_number='MISSION-REVIEW-001', model='Onduleur de mission fictif')
        cls.foreign_unit = Equipment.objects.create(client=cls.other_company, serial_number='MISSION-FOREIGN-001', model='Autre onduleur fictif')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.courier)

    def receive_body(self, **changes):
        data = {'request_key': str(uuid4()), 'serial_number': self.unit.serial_number, 'client': self.company.pk, 'source': 'usb', 'client_reference': '000042-MISSION', 'fault_description': 'Signalement fictif de réception'}
        data.update(changes)
        return data

    def pickup_body(self, **changes):
        data = {'request_key': str(uuid4()), 'equipment': self.unit.pk, 'client_reference': '000042-MISSION', 'fault_description': 'Signalement fictif de collecte', 'pickup_address': 'Adresse de collecte fictive', 'contact_name': 'Contact fictif', 'contact_phone': '+000 123 456'}
        data.update(changes)
        return data

    def pickup(self, **changes):
        self.api.force_authenticate(self.customer)
        response = self.api.post('/api/logistics/pickups/', self.pickup_body(**changes), format='json')
        self.assertIn(response.status_code, (200, 201), response.json())
        return response.json()

    def assign_pickup(self, identifier, courier=None):
        self.api.force_authenticate(self.admin)
        response = self.api.post(f'/api/logistics/pickups/{identifier}/assign/', {'courier': (courier or self.courier).pk}, format='json')
        self.assertEqual(response.status_code, 200, response.json())

    def outbound(self, record):
        self.api.force_authenticate(self.admin)
        response = self.api.post('/api/logistics/outbound/', {'service_request': record.pk, 'courier': self.courier.pk}, format='json')
        self.assertIn(response.status_code, (200, 201), response.json())
        return response.json()

    def ready_exchange(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Échange de livraison fictif', status='exchange')
        replacement = Equipment.objects.create(client=self.company, serial_number='MISSION-REPLACEMENT-001', model='Remplacement de mission fictif')
        self.api.force_authenticate(self.admin)
        response = self.api.patch(f'/api/requests/{record.pk}/exchange/', {'replacement_equipment': replacement.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        response = self.api.post(f'/api/requests/{record.pk}/exchange/validate/', {'mark_ready': True}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        record.refresh_from_db()
        return record, replacement

    def test_courier_bootstrap_and_serial_lookup_are_minimal_without_case_contents(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='PRIVATE_LOGISTICS_SUBJECT', description='PRIVATE_LOGISTICS_DESCRIPTION')
        Intervention.objects.create(service_request=record, diagnosis='PRIVATE_LOGISTICS_DIAGNOSIS', internal_notes='PRIVATE_LOGISTICS_INTERNAL_NOTE')
        response = self.api.get('/api/logistics/bootstrap/')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['couriers'], [])
        self.assertTrue(all(set(row) <= {'id', 'name'} for row in response.json()['clients']))
        lookup = self.api.post('/api/logistics/lookup/', {'serial_number': self.unit.serial_number}, format='json')
        self.assertEqual(lookup.status_code, 200, lookup.json())
        self.assertEqual(lookup.json()['equipment']['client'], {'id': self.company.pk, 'name': self.company.name})
        self.assertTrue(all(set(row) <= {'id', 'call_number', 'client_reference', 'arrived_at', 'status'} for row in lookup.json()['open_requests']))
        serialized = str(lookup.json()) + str(response.json())
        for private in ('PRIVATE_LOGISTICS_SUBJECT', 'PRIVATE_LOGISTICS_DESCRIPTION', 'PRIVATE_LOGISTICS_DIAGNOSIS', 'PRIVATE_LOGISTICS_INTERNAL_NOTE', 'PRIVATE_LOGISTICS_CLIENT_NOTE', self.company.tax_id, 'raw_data', 'warranty_until', 'invoice_reference', 'intake_data'):
            self.assertNotIn(private, serialized)

    def test_catalogue_match_lookup_never_forwards_full_catalogue_or_warranty_data(self):
        from core.catalogue_service import import_catalogue
        from core.models import CatalogueProduct, CatalogueWarranty

        fixture = Path(__file__).parent / 'fixtures' / 'request_intake_synthetic.xls'
        imported = import_catalogue(fixture.read_bytes(), 'PRIVATE_CATALOGUE_FILENAME.xls', actor=self.admin)
        for product in CatalogueProduct.objects.filter(snapshot=imported.snapshot):
            product.raw_data = {**product.raw_data, 'private_test_marker': 'PRIVATE_CATALOGUE_RAW_CELL'}
            product.save(update_fields=['raw_data'])
        CatalogueWarranty.objects.filter(snapshot=imported.snapshot).update(conditions='PRIVATE_WARRANTY_CONDITIONS')
        response = self.api.post('/api/logistics/lookup/', {'serial_number': 'LAB2A49123'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertIn(response.json()['status'], ('catalogue_match', 'ambiguous'))
        serialized = str(response.json())
        for private in ('PRIVATE_CATALOGUE_FILENAME', 'PRIVATE_CATALOGUE_RAW_CELL', 'PRIVATE_WARRANTY_CONDITIONS', 'raw_data', 'warranty_options', 'computed_warranty', 'manufacturing_part_number', 'intake_data'):
            self.assertNotIn(private, serialized)

    def test_client_pickup_and_courier_collection_do_not_invent_workshop_arrival(self):
        from core.models import PickupRequest

        before = Equipment.objects.count(), ServiceRequest.objects.count()
        pickup = self.pickup()
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count()), before)
        self.assign_pickup(pickup['id'])
        self.api.force_authenticate(self.courier)
        response = self.api.post(f'/api/logistics/pickups/{pickup["id"]}/collect/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        stored = PickupRequest.objects.get(pk=pickup['id'])
        self.assertEqual(stored.status, 'collected')
        self.assertIsNotNone(stored.collected_at)
        self.assertIsNone(stored.received_at)
        self.assertIsNone(stored.service_request_id)
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count()), before)

    def test_new_serial_pickup_does_not_create_inventory_and_cannot_target_another_customer(self):
        before = Equipment.objects.count(), ServiceRequest.objects.count()
        body = self.pickup_body(serial_number='PICKUP-UNKNOWN-FICTION', model='Modèle déclaré fictif')
        body.pop('equipment')
        self.api.force_authenticate(self.customer)
        response = self.api.post('/api/logistics/pickups/', body, format='json')
        self.assertIn(response.status_code, (200, 201), response.json())
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count()), before)
        response = self.api.post('/api/logistics/pickups/', self.pickup_body(equipment=self.foreign_unit.pk), format='json')
        self.assertIn(response.status_code, (400, 404), response.json())
        self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count()), before)

    def test_only_assigned_courier_can_read_or_collect_a_pickup(self):
        pickup = self.pickup()
        self.assign_pickup(pickup['id'])
        self.api.force_authenticate(self.other_courier)
        response = self.api.get('/api/logistics/pickups/')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json(), [])
        self.assertEqual(self.api.get(f'/api/logistics/pickups/{pickup["id"]}/').status_code, 404)
        self.assertIn(self.api.post(f'/api/logistics/pickups/{pickup["id"]}/collect/', {}, format='json').status_code, (403, 404))
        self.api.force_authenticate(self.other_customer)
        self.assertEqual(self.api.get(f'/api/logistics/pickups/{pickup["id"]}/').status_code, 404)

    def test_physical_receiving_is_server_dated_unassigned_and_scan_retries_do_not_duplicate(self):
        from core.models import Contract, CourierReceipt, Warranty

        body = self.receive_body(serial_number='RECEIVE-NEW-FICTION', manual_model='Modèle fictif reçu', manual_brand='À confirmer', manual_reason='Série fictive sans catalogue')
        before = timezone.now()
        response = self.api.post('/api/logistics/receive/', body, format='json')
        self.assertIn(response.status_code, (200, 201), response.json())
        identifier = response.json()['request']['id']
        record = ServiceRequest.objects.get(pk=identifier)
        self.assertEqual(record.status, 'new')
        self.assertIsNone(record.assigned_technician_id)
        self.assertGreaterEqual(record.arrived_at, before)
        self.assertLessEqual(record.arrived_at, timezone.now())
        self.assertFalse(Intervention.objects.filter(service_request=record).exists())
        self.assertFalse(Warranty.objects.filter(equipment=record.equipment).exists())
        self.assertFalse(Contract.objects.filter(equipment=record.equipment).exists())
        original_arrival = record.arrived_at
        retry = self.api.post('/api/logistics/receive/', body, format='json')
        self.assertEqual(retry.status_code, 200, retry.json())
        self.assertEqual(retry.json()['request']['id'], identifier)
        self.assertEqual(CourierReceipt.objects.filter(actor=self.courier, request_key=body['request_key']).count(), 1)
        rescan = self.api.post('/api/logistics/receive/', {**body, 'request_key': str(uuid4())}, format='json')
        self.assertEqual(rescan.status_code, 200, rescan.json())
        self.assertTrue(rescan.json()['already_received'])
        self.assertEqual(rescan.json()['request']['id'], identifier)
        record.refresh_from_db()
        self.assertEqual(record.arrived_at, original_arrival)
        self.assertEqual(ServiceRequest.objects.filter(equipment=record.equipment).count(), 1)

    def test_receiving_rejects_customer_mismatch_and_forged_business_fields_atomically(self):
        before = Equipment.objects.count(), ServiceRequest.objects.count()
        bodies = [
            self.receive_body(client=self.other_company.pk),
            self.receive_body(serial_number='RECEIVE-FORGE-STATUS', manual_model='Modèle fictif', manual_reason='Exemple fictif', status='closed'),
            self.receive_body(serial_number='RECEIVE-FORGE-DATE', manual_model='Modèle fictif', manual_reason='Exemple fictif', arrived_at='2000-01-01T00:00:00Z'),
            self.receive_body(assigned_technician=self.tech.pk),
            self.receive_body(warranty_start_override='2000-01-01', duration_months_override=600),
        ]
        for body in bodies:
            with self.subTest(body=body):
                response = self.api.post('/api/logistics/receive/', body, format='json')
                self.assertIn(response.status_code, (400, 404), response.json())
                self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count()), before)

    def test_receipt_key_cannot_be_reused_with_a_different_customer_or_serial(self):
        from core.models import CourierReceipt

        body = self.receive_body()
        original = self.api.post('/api/logistics/receive/', body, format='json')
        self.assertIn(original.status_code, (200, 201), original.json())
        counts = Equipment.objects.count(), ServiceRequest.objects.count(), CourierReceipt.objects.count()
        for changes in ({'client': self.other_company.pk}, {'serial_number': 'OTHER-RECEIPT-FICTION', 'manual_model': 'Autre modèle fictif', 'manual_reason': 'Test de reprise modifiée'}):
            with self.subTest(changes=changes):
                response = self.api.post('/api/logistics/receive/', {**body, **changes}, format='json')
                self.assertIn(response.status_code, (400, 409), response.json())
                self.assertEqual((Equipment.objects.count(), ServiceRequest.objects.count(), CourierReceipt.objects.count()), counts)
        receipt = CourierReceipt.objects.get(actor=self.courier, request_key=body['request_key'])
        self.assertEqual(receipt.service_request_id, original.json()['request']['id'])

    def test_receiving_a_pickup_preserves_its_customer_serial_and_assigned_courier(self):
        from core.models import PickupRequest

        pickup = self.pickup()
        self.assign_pickup(pickup['id'])
        self.api.force_authenticate(self.other_courier)
        response = self.api.post('/api/logistics/receive/', self.receive_body(pickup=pickup['id']), format='json')
        self.assertIn(response.status_code, (403, 404), response.json())
        self.api.force_authenticate(self.courier)
        for changes in ({'client': self.other_company.pk}, {'serial_number': self.foreign_unit.serial_number}):
            with self.subTest(changes=changes):
                response = self.api.post('/api/logistics/receive/', self.receive_body(pickup=pickup['id'], **changes), format='json')
                self.assertIn(response.status_code, (400, 404), response.json())
        stored = PickupRequest.objects.get(pk=pickup['id'])
        self.assertEqual(stored.status, 'assigned')
        self.assertIsNone(stored.received_at)
        self.assertIsNone(stored.service_request_id)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_historical_pickup_with_foreign_linked_case_never_confers_case_access(self):
        pickup = self.pickup()
        self.assign_pickup(pickup['id'])
        self.api.force_authenticate(self.courier)
        response = self.api.post(f'/api/logistics/pickups/{pickup["id"]}/collect/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        body = self.receive_body(pickup=pickup['id'])
        received = self.api.post('/api/logistics/receive/', body, format='json')
        self.assertEqual(received.status_code, 200, received.json())
        identifier = received.json()['request']['id']
        # An inconsistent legacy relation is not an authorization grant. This
        # fixture deliberately bypasses current application write guards.
        ServiceRequest.objects.filter(pk=identifier).update(equipment=self.foreign_unit)
        self.api.force_authenticate(self.customer)
        listing = self.api.get('/api/logistics/pickups/')
        self.assertEqual(listing.status_code, 200, listing.json())
        self.assertEqual(listing.json(), [])
        self.assertEqual(self.api.get(f'/api/logistics/pickups/{pickup["id"]}/').status_code, 404)
        self.api.force_authenticate(self.courier)
        retry = self.api.post('/api/logistics/receive/', {**body, 'request_key': str(uuid4())}, format='json')
        self.assertIn(retry.status_code, (400, 403, 404), retry.json())
        self.assertNotIn(str(self.foreign_unit.serial_number), str(retry.json()))
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_receiving_multiple_open_cases_requires_a_matching_explicit_choice(self):
        first = ServiceRequest.objects.create(equipment=self.unit, subject='Premier dossier fictif')
        second = ServiceRequest.objects.create(equipment=self.unit, subject='Second dossier fictif')
        foreign = ServiceRequest.objects.create(equipment=self.foreign_unit, subject='Dossier étranger fictif')
        response = self.api.post('/api/logistics/receive/', self.receive_body(), format='json')
        self.assertEqual(response.status_code, 400, response.json())
        response = self.api.post('/api/logistics/receive/', self.receive_body(service_request=foreign.pk), format='json')
        self.assertIn(response.status_code, (400, 404), response.json())
        response = self.api.post('/api/logistics/receive/', self.receive_body(service_request=second.pk), format='json')
        self.assertIn(response.status_code, (200, 201), response.json())
        self.assertEqual(response.json()['request']['id'], second.pk)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.arrived_at)
        self.assertIsNotNone(second.arrived_at)
        self.assertEqual(ServiceRequest.objects.count(), 3)

    def test_exchange_outbound_uses_canonical_replacement_and_handoff_is_not_invoicing_or_closure(self):
        from core.models import OutboundJob

        record, replacement = self.ready_exchange()
        job = self.outbound(record)
        self.assertEqual(job['serial_number'], replacement.serial_number)
        self.api.force_authenticate(self.other_courier)
        self.assertEqual(self.api.get(f'/api/logistics/outbound/{job["id"]}/').status_code, 404)
        self.assertIn(self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json').status_code, (403, 404))
        self.api.force_authenticate(self.courier)
        response = self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        stored = OutboundJob.objects.get(pk=job['id'])
        self.assertEqual(stored.delivery_equipment_id, replacement.pk)
        self.assertEqual(stored.handed_over_by_id, self.courier.pk)
        first_handoff = stored.handed_over_at
        self.assertIsNotNone(first_handoff)
        response = self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        stored.refresh_from_db()
        self.assertEqual(stored.handed_over_at, first_handoff)
        self.assertEqual(self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Autre destinataire'}, format='json').status_code, 400)
        record.refresh_from_db()
        self.assertEqual(record.status, 'ready_for_delivery')
        self.assertIsNone(record.closed_at)
        self.assertIsNone(record.exchange_process.billing_validated_at)

    def test_technical_exchange_reset_is_blocked_after_physical_handoff(self):
        record, _ = self.ready_exchange()
        job = self.outbound(record)
        self.api.force_authenticate(self.courier)
        response = self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.api.force_authenticate(self.admin)
        response = self.api.post(f'/api/requests/{record.pk}/exchange/reset/', {'reason': 'Tentative après remise physique'}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        record.refresh_from_db()
        self.assertIsNotNone(record.exchange_process.validated_at)

    def test_two_requests_cannot_dispatch_the_same_physical_equipment_at_once(self):
        records = [ServiceRequest.objects.create(equipment=self.unit, subject=f'Réparation fictive {index}', status='testing') for index in range(2)]
        self.api.force_authenticate(self.admin)
        for record in records:
            response = self.api.post(f'/api/requests/{record.pk}/disposition/repair/', {
                'diagnosis': 'Tests fictifs réussis', 'tests_passed': True,
                'tested_on': timezone.localdate().isoformat(),
            }, format='json')
            self.assertEqual(response.status_code, 200, response.json())
        first = self.outbound(records[0])
        response = self.api.post('/api/logistics/outbound/', {'service_request': records[1].pk, 'courier': self.other_courier.pk}, format='json')
        self.assertIn(response.status_code, (400, 409), response.json())
        from core.models import OutboundJob
        self.assertEqual(OutboundJob.objects.filter(active=True, delivery_equipment=self.unit).count(), 1)
        self.assertEqual(OutboundJob.objects.get(pk=first['id']).assigned_courier_id, self.courier.pk)

    def test_nonrepairable_return_delivers_original_without_automatic_free_approval_or_closure(self):
        record = ServiceRequest.objects.create(equipment=self.unit, subject='Retour physique fictif', status='testing')
        self.api.force_authenticate(self.admin)
        response = self.api.post(f'/api/requests/{record.pk}/disposition/nonrepairable/', {'diagnosis': 'Diagnostic de retour fictif', 'fee_mode': 'billable'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        job = self.outbound(record)
        self.assertEqual(job['kind'], 'return')
        self.assertEqual(job['serial_number'], self.unit.serial_number)
        self.api.force_authenticate(self.courier)
        response = self.api.post(f'/api/logistics/outbound/{job["id"]}/handoff/', {'recipient_name': 'Destinataire fictif'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        record.refresh_from_db()
        self.assertEqual(record.status, 'return_to_client')
        self.assertIsNone(record.closed_at)
        self.assertIsNone(record.disposition_process.finance_validated_at)
        self.assertEqual(record.disposition_process.invoice_reference, '')
        self.assertEqual(record.disposition_process.finance_free_reason, '')
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.patch(f'/api/requests/{record.pk}/', {'status': 'closed'}, format='json').status_code, 400)
