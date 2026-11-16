"""
Django settings for mysite project.

Django 5.0 settings for the SMART AGRIASSIST project.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the root .env file (beside manage.py).
# This must run before any os.environ.get() calls below so that values
# from .env are available to Django settings.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / '.env', override=False)
except ImportError:
    pass

# Direct fallback parser to guarantee .env values are always in os.environ
env_path = BASE_DIR / '.env'
if env_path.exists():
    try:
        with open(env_path, 'r', encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"\'')
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass


def env_bool(name, default=False):
    """Read a boolean environment variable without treating 'False' as truthy."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=''):
    """Read a comma-separated environment variable as a clean list."""
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


def env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Override via the DJANGO_SECRET_KEY environment variable (see .env.example).
DEFAULT_SECRET_KEY = 'django-insecure-zsnno#^l!whuzs%55j6*366px#r09+borh$1^2mj*_ovz47!o_'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', DEFAULT_SECRET_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DJANGO_DEBUG', True)

# A known/placeholder key in production is a critical security issue.
if not DEBUG and SECRET_KEY in {
    DEFAULT_SECRET_KEY,
    'django-insecure-smart-agri-assistant-change-in-production',
    '',
}:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY must be set to a unique value when DJANGO_DEBUG=False. '
        'Generate one with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
    )

# DJANGO_ALLOWED_HOSTS is the preferred name; ALLOWED_HOSTS is accepted for
# backwards compatibility with existing local .env files.
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS') or env_list('ALLOWED_HOSTS')
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']
elif not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']

CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'http://10.204.124.12:8000',
    'https://*.loca.lt',
    'https://*.trycloudflare.com',
    'https://*.ngrok-free.app',
    'https://*.ngrok.io',
]
CSRF_TRUSTED_ORIGINS.extend(env_list('DJANGO_CSRF_TRUSTED_ORIGINS'))

# Make CSRF work automatically for the production host(s) without requiring a
# second environment variable. PythonAnywhere terminates TLS at its proxy.
for _host in ALLOWED_HOSTS:
    if _host == '*' or _host.startswith('.'):
        continue
    for _scheme in ('https', 'http'):
        _origin = f'{_scheme}://{_host}'
        if _origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(_origin)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'apps.core',
    'apps.info',
    'apps.catalog',
    'apps.crops',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.core.middleware.UserTimezoneMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mysite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'libraries': {
                'admin_filter_tags': 'apps.core.templatetags.admin_filter_tags',
            },
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.unread_notifications',
                'apps.core.context_processors.admin_sidebar_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'mysite.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
# Connection settings are read from the environment (see .env.example).
# SQLite is the default. Set DB_ENGINE to mysql or postgres in .env to switch.

DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').lower().strip()

if DB_ENGINE == 'mysql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'smart'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
            },
        }
    }
elif DB_ENGINE in ('postgres', 'postgresql'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'smart'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.environ.get('DB_NAME', 'db.sqlite3'),
        }
    }

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

SILENCED_SYSTEM_CHECKS = ['mysql.W002']

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Target for `python manage.py collectstatic` (used by PythonAnywhere).
STATIC_ROOT = BASE_DIR / 'staticfiles'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = '/home/'
LOGOUT_REDIRECT_URL = '/'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Absolute site URL used in notification emails and other outbound links.
SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000').rstrip('/')

# In-process automation thread. This is convenient during local development,
# but production deployments should run the automation as a one-shot scheduled
# task instead. WSGI workers can be recycled, and multiple workers would each
# start their own thread and duplicate automation cycles.
ENABLE_BACKGROUND_SCHEDULER = env_bool('ENABLE_BACKGROUND_SCHEDULER', DEBUG)

# ------------------------------------------------------------------ Security
# PythonAnywhere terminates HTTPS at its proxy and forwards the original
# protocol in X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', not DEBUG)
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', not DEBUG)
SECURE_HSTS_SECONDS = env_int('DJANGO_SECURE_HSTS_SECONDS', 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# ------------------------------------------------------------------ Email
# SMTP is enabled automatically when EMAIL_HOST is configured. Otherwise
# messages are printed to the console so local development remains zero-setup.
EMAIL_HOST = os.environ.get('EMAIL_HOST', '').strip()
if EMAIL_HOST:
    EMAIL_BACKEND = os.environ.get(
        'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend'
    )
    EMAIL_PORT = env_int('EMAIL_PORT', 587)
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
    EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
else:
    EMAIL_BACKEND = os.environ.get(
        'EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'
    )

DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL', 'SMART AGRIASSIST <no-reply@smart-agri.local>'
)

# ------------------------------------------------------------------ Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{levelname} {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# External Services & APIs
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')