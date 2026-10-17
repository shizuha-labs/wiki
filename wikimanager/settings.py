"""
Django settings for Shizuha Wiki - Team Documentation and Knowledge Management
"""
import os
from pathlib import Path
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key secret in production!
# Use JWT_SECRET_KEY if available (shared with shizuha-id), fallback to SECRET_KEY
def _required_env(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f'{name} must be configured with a nonblank value')
    return value


SECRET_KEY = (_required_env('JWT_SECRET_KEY') if 'JWT_SECRET_KEY' in os.environ
              else _required_env('SECRET_KEY'))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
SOURCE_AUTHORITY_CONTRACT_URL = os.environ.get(
    'SOURCE_AUTHORITY_CONTRACT_URL',
    'http://repo-config-probe.origin.svc.cluster.local:8080',
)
SOURCE_AUTHORITY_CONTRACT_TIMEOUT_SECONDS = float(
    os.environ.get('SOURCE_AUTHORITY_CONTRACT_TIMEOUT_SECONDS', '3')
)

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.postgres',
    # Third party
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_celery_beat',
    'drf_spectacular',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'dj_rest_auth',
    'dj_rest_auth.registration',
    # Local apps
    'wiki',
]

MIDDLEWARE = [
    'wikimanager.middleware.ScriptNameMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'wiki.middleware.ServiceAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'wikimanager.middleware.OrganizationMiddleware',
    'wiki.request_metrics.RequestStatusMetricsMiddleware',
]

ROOT_URLCONF = 'wikimanager.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'wikimanager.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'shizuha_wiki'),
        'USER': os.environ.get('POSTGRES_USER', 'shizuha'),
        'PASSWORD': _required_env('POSTGRES_PASSWORD'),
        'HOST': os.environ.get('POSTGRES_HOST', 'shizuha-db'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/shizuha-wiki-static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files (local development only; production sets the shared S3 backend)
MEDIA_URL = '/shizuha-wiki-media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# MinIO/S3 Storage Configuration
WIKI_REQUIRE_SHARED_MEDIA_STORAGE = os.environ.get(
    'WIKI_REQUIRE_SHARED_MEDIA_STORAGE', '0'
).lower() in ('true', '1', 'yes')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '').strip()
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', '').strip()
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
_shared_storage_values = {
    'AWS_STORAGE_BUCKET_NAME': AWS_STORAGE_BUCKET_NAME,
    'AWS_S3_ENDPOINT_URL': AWS_S3_ENDPOINT_URL,
    'AWS_ACCESS_KEY_ID': AWS_ACCESS_KEY_ID,
    'AWS_SECRET_ACCESS_KEY': AWS_SECRET_ACCESS_KEY,
}
if WIKI_REQUIRE_SHARED_MEDIA_STORAGE:
    missing = [
        name for name, value in _shared_storage_values.items() if not value
    ]
    if missing:
        raise ImproperlyConfigured(
            'Shared wiki attachment storage is incomplete; missing ' + ', '.join(missing)
        )
    # Keep this service self-contained. The wiki image is built from this repo,
    # not shizuha-stack, so importing the optional shizuha_storage source package
    # here would crash only after production enables the bucket.
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
            'OPTIONS': {
                'access_key': AWS_ACCESS_KEY_ID,
                'secret_key': AWS_SECRET_ACCESS_KEY,
                'bucket_name': AWS_STORAGE_BUCKET_NAME,
                'endpoint_url': AWS_S3_ENDPOINT_URL,
                'addressing_style': 'path',
                'signature_version': 's3v4',
                'querystring_auth': True,
                'file_overwrite': False,
                'default_acl': None,
            },
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
elif any(_shared_storage_values.values()):
    raise ImproperlyConfigured(
        'Wiki shared-storage settings are atomic: set '
        'WIKI_REQUIRE_SHARED_MEDIA_STORAGE=1 with endpoint, bucket, access key, '
        'and secret key together; refusing an implicit backend selection.'
    )

WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS = int(os.environ.get(
    'WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS', '3600',
))

# Storage quota tracking
STORAGE_QUOTA_SERVICE = 'wiki'
STORAGE_DRIVE_URL = os.environ.get('SHIZUHA_DRIVE_URL', 'http://shizuha-drive:8018')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Sites framework
SITE_ID = 1

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'wiki.authentication.ShizuhaJWTAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        'wiki.permissions.ServiceAccessPermission',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# CORS Settings
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:8002,http://localhost:5176').split(',')
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get(
    'CSRF_TRUSTED_ORIGINS', '',
).split(',') if origin.strip()]

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/5')
CONNECT_SECURITY_EVENT_METRICS_REDIS_URL = os.environ.get(
    'CONNECT_SECURITY_EVENT_METRICS_REDIS_URL', CELERY_BROKER_URL,
)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/5')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SCHEDULE = {
    'retry-pending-attachment-deletions': {
        'task': 'wiki.tasks.retry_attachment_deletions',
        'schedule': 60.0,
    },
    # WIKI-57: rescue upload intents whose one-off clocked cleanup delivery was
    # lost. Every 5 min mirrors the WikiAttachmentCleanupOverdue `for: 5m` hold.
    'rescue-overdue-attachment-upload-intents': {
        'task': 'wiki.tasks.sweep_overdue_upload_intents',
        'schedule': 300.0,
    },
}

# Allauth settings
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = 'optional'

# drf-spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'Shizuha Wiki API',
    'DESCRIPTION': 'Team documentation and knowledge management API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Shizuha ID integration
SHIZUHA_ID_API_URL = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')

# PLAT-4133: authenticated, sanitized boundary-denial events to Connect SIEM-lite.
SHIZUHA_CONNECT_SECURITY_EVENT_URL = os.environ.get(
    'SHIZUHA_CONNECT_SECURITY_EVENT_URL',
    'http://shizuha-connect.shizuha.svc.cluster.local:8019/api/internal/security-events/',
)
CONNECT_SECURITY_EVENT_ORIGIN_SECRET = os.environ.get('CONNECT_SECURITY_EVENT_ORIGIN_SECRET', '')
CONNECT_SECURITY_EVENT_TIMEOUT_SECONDS = float(os.environ.get('CONNECT_SECURITY_EVENT_TIMEOUT_SECONDS', '1.0'))
CONNECT_SECURITY_EVENT_EMIT_ENABLED = os.environ.get('CONNECT_SECURITY_EVENT_EMIT_ENABLED', 'true').lower() in ('1', 'true', 'yes')

# Wiki-specific settings
WIKI_MAX_PAGE_SIZE = int(os.environ.get('WIKI_MAX_PAGE_SIZE', '1048576'))  # 1MB default
WIKI_MAX_ATTACHMENT_SIZE = int(os.environ.get('WIKI_MAX_ATTACHMENT_SIZE', '52428800'))  # 50MB default
WIKI_ALLOWED_ATTACHMENT_TYPES = [
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
    'application/pdf',
    'text/plain', 'text/markdown', 'text/csv',
    'application/json',
    'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/zip', 'application/x-tar', 'application/gzip',
]

# Logging
# The file handler is included only when its directory exists and is writable:
# Django's dictConfig instantiates EVERY handler in the dict at configure time,
# so a hard-coded /var/log/django path crashes manage.py in any environment
# without that directory (CI test pods, local dev, migrations containers).
WIKI_LOG_FILE = os.environ.get('WIKI_LOG_FILE', '/var/log/django/wiki.log')
_wiki_log_dir = os.path.dirname(WIKI_LOG_FILE)
_wiki_file_logging = os.path.isdir(_wiki_log_dir) and os.access(_wiki_log_dir, os.W_OK)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        **({'file': {
            'class': 'logging.FileHandler',
            'filename': WIKI_LOG_FILE,
            'formatter': 'verbose',
        }} if _wiki_file_logging else {}),
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'wiki': {
            'handlers': ['console', 'file'] if (_wiki_file_logging and not DEBUG) else ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# PLS-482 P1 #4: the ONLY identity allowed to create publication snapshots
# (the dedicated Pulse publication service principal — Pulse mints its service
# JWT with this user_id). Unset/0 => the CAS endpoint fails closed.
SHIZUHA_WIKI_SERVICE_USER_ID = int(os.environ.get('SHIZUHA_WIKI_SERVICE_USER_ID', '0') or '0')
