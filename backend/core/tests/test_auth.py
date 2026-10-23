from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from core.models import LoginAttempt


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AuthenticationTests(TestCase):
    def setUp(self):
        self.password = 'StrongSessionPhrase42!'
        self.user = get_user_model().objects.create_user('auth-admin', password=self.password, role='admin')
        self.browser = Client(enforce_csrf_checks=True)

    def login(self, password=None):
        self.browser.get('/api/session/')
        return self.browser.post('/api/login/', {'username': self.user.username, 'password': password or self.password}, content_type='application/json', HTTP_X_CSRFTOKEN=self.browser.cookies['csrftoken'].value)

    def test_login_requires_csrf_even_for_anonymous_user(self):
        response = self.browser.post('/api/login/', {'username': self.user.username, 'password': self.password}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_cookie_sessions_csrf_rotation_and_logout(self):
        self.browser.get('/api/session/')
        old_token = self.browser.cookies['csrftoken'].value
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(old_token, self.browser.cookies['csrftoken'].value)
        self.assertTrue(self.browser.cookies['sessionid']['httponly'])
        self.assertEqual(self.browser.get('/api/clients/').status_code, 200)
        self.assertEqual(self.browser.post('/api/clients/', {'name': 'No CSRF'}, content_type='application/json').status_code, 403)
        self.assertEqual(self.browser.post('/api/logout/', content_type='application/json').status_code, 403)
        response = self.browser.post('/api/logout/', content_type='application/json', HTTP_X_CSRFTOKEN=self.browser.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.browser.get('/api/session/').json()['user'])

    def test_database_login_throttle_survives_new_browser(self):
        for _ in range(10):
            self.assertEqual(self.login('wrong-password').status_code, 400)
        self.browser = Client(enforce_csrf_checks=True)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '900')
        self.assertGreaterEqual(LoginAttempt.objects.count(), 2)

    def test_admin_password_change_preserves_own_session_and_rejects_old_password(self):
        self.login()
        changed = 'NewSecureTestingPhrase58!'
        response = self.browser.patch(f'/api/users/{self.user.pk}/', {'password': changed}, content_type='application/json', HTTP_X_CSRFTOKEN=self.browser.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(self.browser.get('/api/session/').json()['user'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(changed))
        self.assertFalse(self.user.check_password(self.password))

    def test_malformed_login_returns_json_error(self):
        self.browser.get('/api/session/')
        response = self.browser.post('/api/login/', data='[]', content_type='application/json', HTTP_X_CSRFTOKEN=self.browser.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 400)
