"""Explicit internal billing permission: grants, revocations and client boundaries."""
from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client as Browser, RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from core.admin import PowerCareUserAdmin
from core.models import Client
from core.permissions import can_validate_billing
from core.serializers import UserSerializer


User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class BillingPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('billing-admin', role='admin', password='FictionalBillingPhrase42!')
        cls.manager = User.objects.create_user('billing-manager', role='manager', password='FictionalBillingPhrase42!')
        cls.tech = User.objects.create_user('billing-technician', role='technician', password='FictionalBillingPhrase42!')
        cls.company = Client.objects.create(name='Société de facturation fictive')
        cls.customer = User.objects.create_user('billing-client', role='client', client=cls.company, password='FictionalBillingPhrase42!')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def endpoint(self, user):
        return f'/api/users/{user.pk}/'

    def test_only_admin_is_authorized_by_default_and_the_flag_stays_false(self):
        for user in (self.admin, self.manager, self.tech, self.customer):
            with self.subTest(role=user.role):
                self.assertFalse(user.can_validate_billing)
                self.assertEqual(can_validate_billing(user), user.role == 'admin')
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.can_validate_billing)

    def test_explicit_internal_permission_stops_working_for_an_inactive_account(self):
        for role in ('manager', 'technician'):
            with self.subTest(role=role):
                user = User(role=role, can_validate_billing=True, is_active=True)
                self.assertTrue(can_validate_billing(user))
                user.is_active = False
                self.assertFalse(can_validate_billing(user))
        self.assertFalse(can_validate_billing(User(role='admin', is_active=False)))

    def test_anonymous_and_client_accounts_never_validate_billing(self):
        self.assertFalse(can_validate_billing(None))
        self.assertFalse(can_validate_billing(AnonymousUser()))
        self.assertFalse(can_validate_billing(User(role='client', can_validate_billing=True)))
        self.assertFalse(can_validate_billing(User(role='client', is_superuser=True, can_validate_billing=True)))

    def test_admin_can_grant_and_revoke_without_changing_role_or_password(self):
        for target in (self.manager, self.tech):
            with self.subTest(role=target.role):
                password_hash, role = target.password, target.role
                grant = self.api.patch(self.endpoint(target), {'can_validate_billing': True}, format='json')
                self.assertEqual(grant.status_code, 200, grant.data)
                self.assertTrue(grant.data['can_validate_billing'])
                self.assertNotIn('password', grant.data)
                target.refresh_from_db()
                self.assertTrue(can_validate_billing(target))
                self.assertEqual((target.password, target.role), (password_hash, role))
                revoke = self.api.patch(self.endpoint(target), {'can_validate_billing': False}, format='json')
                self.assertEqual(revoke.status_code, 200, revoke.data)
                target.refresh_from_db()
                self.assertFalse(can_validate_billing(target))
                self.assertEqual((target.password, target.role), (password_hash, role))

    def test_admin_can_create_internal_account_with_explicit_permission(self):
        result = self.api.post('/api/users/', {
            'username': 'billing-explicit-staff', 'role': 'technician',
            'password': 'UniqueSyntheticBillingPhrase52!', 'can_validate_billing': True,
        }, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        user = User.objects.get(pk=result.data['id'])
        self.assertEqual(user.role, 'technician')
        self.assertTrue(can_validate_billing(user))
        self.assertNotIn('password', result.data)

    def test_manager_technician_and_client_cannot_grant_or_revoke_permissions(self):
        for actor in (self.manager, self.tech, self.customer):
            with self.subTest(role=actor.role):
                self.api.force_authenticate(actor)
                for value in (True, False):
                    response = self.api.patch(self.endpoint(self.tech), {'can_validate_billing': value}, format='json')
                    self.assertEqual(response.status_code, 403)
                create = self.api.post('/api/users/', {
                    'username': 'billing-escalation-attempt', 'role': 'technician',
                    'password': 'UniqueSyntheticBillingPhrase52!', 'can_validate_billing': True,
                }, format='json')
                self.assertEqual(create.status_code, 403)
        self.tech.refresh_from_db()
        self.assertFalse(self.tech.can_validate_billing)
        self.assertFalse(User.objects.filter(username='billing-escalation-attempt').exists())

    def test_direct_serializer_cannot_bypass_admin_guard(self):
        for actor in (None, self.manager, self.tech, self.customer):
            with self.subTest(actor=actor):
                context = {'request': SimpleNamespace(user=actor)} if actor else {}
                serializer = UserSerializer(self.tech, data={'can_validate_billing': True}, partial=True, context=context)
                self.assertFalse(serializer.is_valid())
                self.assertIn('can_validate_billing', serializer.errors)
        self.admin.is_active = False
        serializer = UserSerializer(self.tech, data={'can_validate_billing': True}, partial=True,
                                    context={'request': SimpleNamespace(user=self.admin)})
        self.assertFalse(serializer.is_valid())

    def test_client_permission_rejected_on_creation_and_update_even_by_admin(self):
        create = self.api.post('/api/users/', {
            'username': 'billing-forbidden-client', 'role': 'client', 'client': self.company.pk,
            'password': 'UniqueSyntheticBillingPhrase52!', 'can_validate_billing': True,
        }, format='json')
        self.assertEqual(create.status_code, 400, create.data)
        self.assertIn('can_validate_billing', create.data)
        update = self.api.patch(self.endpoint(self.customer), {'can_validate_billing': True}, format='json')
        self.assertEqual(update.status_code, 400, update.data)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_validate_billing)

    def test_role_change_to_client_requires_explicit_revocation(self):
        self.tech.can_validate_billing = True
        self.tech.save(update_fields=['can_validate_billing'])
        rejected = self.api.patch(self.endpoint(self.tech), {'role': 'client', 'client': self.company.pk}, format='json')
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.role, 'technician')
        self.assertTrue(self.tech.can_validate_billing)
        accepted = self.api.patch(self.endpoint(self.tech), {
            'role': 'client', 'client': self.company.pk, 'can_validate_billing': False,
        }, format='json')
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.role, 'client')
        self.assertFalse(can_validate_billing(self.tech))

    def test_database_and_model_clean_protect_client_flag(self):
        candidate = User(username='invalid-billing-client', role='client', client=self.company, can_validate_billing=True)
        with self.assertRaises(ValidationError) as error:
            candidate.clean()
        self.assertIn('can_validate_billing', error.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.customer.pk).update(can_validate_billing=True)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_validate_billing)
        self.tech.can_validate_billing = True
        self.tech.save(update_fields=['can_validate_billing'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.tech.pk).update(role='client', client=self.company)

    def test_live_session_observes_grant_and_revocation_without_new_login(self):
        browser = Browser()
        browser.force_login(self.manager)
        self.assertFalse(browser.get('/api/session/').json()['user']['can_validate_billing'])
        self.api.patch(self.endpoint(self.manager), {'can_validate_billing': True}, format='json')
        self.assertTrue(browser.get('/api/session/').json()['user']['can_validate_billing'])
        self.api.patch(self.endpoint(self.manager), {'can_validate_billing': False}, format='json')
        payload = browser.get('/api/session/').json()['user']
        self.assertFalse(payload['can_validate_billing'])
        self.assertEqual(payload['role'], 'manager')
        self.assertNotIn('password', payload)

    def test_login_and_admin_user_payloads_expose_persisted_flag(self):
        browser = Browser()
        result = browser.post('/api/login/', {
            'username': self.admin.username, 'password': 'FictionalBillingPhrase42!',
        }, content_type='application/json')
        self.assertEqual(result.status_code, 200, result.content)
        payload = result.json()['user']
        self.assertEqual(payload['role'], 'admin')
        self.assertIs(payload['can_validate_billing'], False)
        self.assertNotIn('password', payload)
        listed = self.api.get(self.endpoint(self.manager))
        self.assertIs(listed.data['can_validate_billing'], False)

    def test_staff_directory_does_not_expose_other_users_permission_management(self):
        self.api.force_authenticate(self.manager)
        result = self.api.get('/api/users/')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data)
        self.assertTrue(all('can_validate_billing' not in user for user in result.data))

    def test_django_admin_user_writes_are_also_reserved_to_app_administrators(self):
        model_admin = PowerCareUserAdmin(User, admin.site)
        request = RequestFactory().get('/admin/core/user/')
        request.user = self.manager
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, self.tech))
        self.assertFalse(model_admin.has_delete_permission(request, self.tech))
        request.user = User(role='admin', is_superuser=True)
        self.assertTrue(model_admin.has_add_permission(request))
        self.assertTrue(model_admin.has_change_permission(request, self.tech))
        self.assertTrue(model_admin.has_delete_permission(request, self.tech))
