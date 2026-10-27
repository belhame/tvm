import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from core.middleware import static_headers

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if len(SECRET_KEY) < 32:
    raise ImproperlyConfigured('Définissez DJANGO_SECRET_KEY (32 caractères minimum).')
DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
ALLOWED_HOSTS = [x.strip() for x in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()]
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'core',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'core.middleware.PrivateAPIHeaders', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'core.attachment_limits.AttachmentUploadLimitMiddleware',
    'core.serial_photo_limits.SerialPhotoUploadLimitMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'core.logistics_permissions.CourierAPIAccessMiddleware', 'core.workflow_events.WorkflowActorMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.debug', 'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
database_url = os.environ.get('DATABASE_URL', '')
if database_url:
    if not database_url.startswith(('postgres://', 'postgresql://')):
        raise ImproperlyConfigured('DATABASE_URL doit désigner PostgreSQL. SQLite nécessite TVM_ALLOW_SQLITE=1 sans DATABASE_URL.')
    DATABASES = {'default': dj_database_url.parse(database_url, conn_max_age=60, conn_health_checks=True)}
elif os.environ.get('TVM_ALLOW_SQLITE') == '1':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ.get('SQLITE_PATH', str(BASE_DIR / 'test.sqlite3'))}}
else:
    raise ImproperlyConfigured('DATABASE_URL PostgreSQL obligatoire pour le serveur partagé.')
AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = os.environ.get('TVM_TIMEZONE', 'Africa/Lagos')
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = Path(os.environ.get('TVM_MEDIA_ROOT', str(BASE_DIR / 'media')))
FRONTEND_DIST = ROOT_DIR / 'frontend' / 'dist'
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_INDEX_FILE = True
WHITENOISE_MAX_AGE = 3600
WHITENOISE_ADD_HEADERS_FUNCTION = static_headers
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'user': '600/min', 'login': '10/min'},
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DATETIME_FORMAT': 'iso-8601',
    'EXCEPTION_HANDLER': 'core.errors.api_exception_handler',
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('DJANGO_SECURE_COOKIES', '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '0') == '1'
if os.environ.get('DJANGO_TRUST_PROXY_HEADERS', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
TVM_DEMO_MODE = os.environ.get('TVM_DEMO_MODE', '0') == '1'
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# External delivery remains disabled until both server configuration and each
# client's opt-in are explicitly supplied. No secret is returned by the API.
TVM_EMAIL_ENABLED = os.environ.get('TVM_EMAIL_ENABLED', '0') == '1'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('TVM_SMTP_HOST', '')
EMAIL_PORT = int(os.environ.get('TVM_SMTP_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('TVM_SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('TVM_SMTP_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('TVM_SMTP_USE_TLS', '1') == '1'
EMAIL_USE_SSL = os.environ.get('TVM_SMTP_USE_SSL', '0') == '1'
DEFAULT_FROM_EMAIL = os.environ.get('TVM_SMTP_FROM_EMAIL', '')
TVM_NOTIFICATION_TIMEOUT = max(1, min(30, int(os.environ.get('TVM_NOTIFICATION_TIMEOUT', '10'))))
EMAIL_TIMEOUT = TVM_NOTIFICATION_TIMEOUT
TVM_WHATSAPP_ENABLED = os.environ.get('TVM_WHATSAPP_ENABLED', '0') == '1'
TVM_WHATSAPP_TOKEN = os.environ.get('TVM_WHATSAPP_TOKEN', '')
TVM_WHATSAPP_PHONE_ID = os.environ.get('TVM_WHATSAPP_PHONE_ID', '')
TVM_WHATSAPP_API_VERSION = os.environ.get('TVM_WHATSAPP_API_VERSION', '')
TVM_WHATSAPP_TEMPLATE = os.environ.get('TVM_WHATSAPP_TEMPLATE', '')
TVM_WHATSAPP_LANGUAGE = os.environ.get('TVM_WHATSAPP_LANGUAGE', 'fr')

# The local technical library works without a provider. External diagnosis is
# opt-in and credentials stay on the server, never in frontend configuration.
TVM_AI_ENABLED = os.environ.get('TVM_AI_ENABLED', '0') == '1'
TVM_AI_API_KEY = os.environ.get('TVM_AI_API_KEY', '')
TVM_AI_MODEL = os.environ.get('TVM_AI_MODEL', 'gpt-4.1-mini')
TVM_AI_TIMEOUT = max(5, min(30, int(os.environ.get('TVM_AI_TIMEOUT', '20'))))
