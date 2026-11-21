"""
Django settings for School Shuttle Bus Tracking System.
"""

import os
from pathlib import Path

import dj_database_url
from decouple import config
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: don't run with debug turned on in production!
# Accept the standard boolean values plus common deployment labels.  This keeps
# an environment setting such as ``DEBUG=release`` from preventing Django from
# starting, while treating release/production as debug disabled.


def _debug_setting(value):
    value = str(value).strip().lower()
    if value in {'1', 'true', 'yes', 'on', 'debug', 'development'}:
        return True
    if value in {'0', 'false', 'no', 'off', 'release', 'production'}:
        return False
    raise ValueError('DEBUG must be a boolean or a development/release label.')


RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
DEBUG = config(
    'DEBUG',
    default=not bool(RENDER_EXTERNAL_HOSTNAME or DATABASE_URL),
    cast=_debug_setting,
)
if RENDER_EXTERNAL_HOSTNAME and DEBUG:
    raise ImproperlyConfigured('DEBUG must be False on Render.')

if DEBUG:
    SECRET_KEY = config('SECRET_KEY', default='').strip()
    DATABASE_URL = config('DATABASE_URL', default='').strip()
else:
    SECRET_KEY = os.environ.get('SECRET_KEY', '').strip()
    DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY must be configured when DEBUG is False.')
    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = [
    host.strip()
    for host in (
        config('ALLOWED_HOSTS', default='localhost,127.0.0.1')
        if DEBUG else os.environ.get('ALLOWED_HOSTS', '')
    ).split(',')
    if host.strip()
]
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        'Set ALLOWED_HOSTS or deploy on Render with RENDER_EXTERNAL_HOSTNAME.'
    )

CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip('/')
    for origin in (
        config('CSRF_TRUSTED_ORIGINS', default='')
        if DEBUG else os.environ.get('CSRF_TRUSTED_ORIGINS', '')
    ).split(',')
    if origin.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    render_origin = f'https://{RENDER_EXTERNAL_HOSTNAME}'
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)
if not DEBUG:
    for host in ALLOWED_HOSTS:
        if '*' not in host:
            origin = f'https://{host}'
            if origin not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(origin)
    if not CSRF_TRUSTED_ORIGINS:
        raise ImproperlyConfigured(
            'Set CSRF_TRUSTED_ORIGINS or configure a production hostname.'
        )

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# Application definition
INSTALLED_APPS = [
    'daphne',
    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'channels',

    # Local apps
    'accounts',
    'school_settings',
    'buses',
    'routes',
    'tracking',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Custom: injects school_settings into every template
                'school_settings.context_processors.school_settings_processor',
            ],
        },
    },
]

# ASGI application (required for Django Channels)
ASGI_APPLICATION = 'config.asgi.application'

# WSGI application
WSGI_APPLICATION = 'config.wsgi.application'

# SQLite is the local-development default; production requires PostgreSQL.
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    if not DEBUG:
        raise ImproperlyConfigured('DATABASE_URL must be configured in production.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

if not DEBUG:
    if DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
        raise ImproperlyConfigured('Production DATABASE_URL must use PostgreSQL.')
    DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = 'require'

# In-memory delivery is suitable only for local development. Production uses
# Redis so broadcasts reach every worker and connected student's socket.
REDIS_URL = (
    config('REDIS_URL', default='').strip()
    if DEBUG else os.environ.get('REDIS_URL', '').strip()
)
if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        }
    }
else:
    if not DEBUG:
        raise ImproperlyConfigured('REDIS_URL must be configured in production.')
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Media files (uploaded logos, etc.)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login redirects
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

# File upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB max upload
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
