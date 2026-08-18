import os
from datetime import timedelta
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'drf_spectacular',
    
    # Local apps
    'api.apps.ApiConfig',
    'quran.apps.QuranConfig',
    'corpus.apps.CorpusConfig',
    'search.apps.SearchConfig',
    'clips.apps.ClipsConfig',
    'accounts.apps.AccountsConfig',
]

MIDDLEWARE = [
    # Transcripts are the biggest payload the API serves (thousands of words per
    # segment) and compress ~5x, so gzip runs first and sees every response body.
    'django.middleware.gzip.GZipMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # Needs to be at the top
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # WhiteNoise static serving
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'core.urls'

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

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# Password validation
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
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# DRF settings
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Applied per view via ScopedRateThrottle + throttle_scope; anonymous
    # readers are the only clients these write paths have (API_CONTRACT.md).
    'DEFAULT_THROTTLE_RATES': {
        'search': '30/min',
        'corrections': '10/hour',
        'clips': '5/hour',
    },
}

# OpenAPI / Swagger configuration
SPECTACULAR_SETTINGS = {
    'TITLE': "Sha'rawy Archive API",
    'DESCRIPTION': (
        "Read API for the Sha'rawy Archive: the Quran text, the audio corpus "
        "(segments, machine transcripts, chunks), search, topics, plus "
        'correction submissions and clip render jobs. All timestamps are '
        'integer milliseconds. Audio and waveform URLs are presigned and '
        'short-lived; raw storage keys never leave the backend.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    # Two unrelated `status` fields would otherwise generate collided enum
    # names like `Status127Enum` in the frontend types.
    'ENUM_NAME_OVERRIDES': {
        'ClipStatusEnum': 'clips.models.ClipStatus',
        'CorrectionStatusEnum': 'corpus.models.CorrectionStatus',
    },
}

# SimpleJWT configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': os.environ.get(
        'SECRET_KEY', 'django-insecure-dev-secret-key-template-project-1234'
    ),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Celery configurations
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Route heavy ingestion work to a dedicated queue consumed by pipeline workers.
CELERY_TASK_ROUTES = {
    'pipeline.*': {'queue': 'pipeline'},
}

# Meilisearch
MEILI_URL = os.environ.get('MEILI_URL', 'http://localhost:7700')
MEILI_MASTER_KEY = os.environ.get('MEILI_MASTER_KEY', 'devmasterkey')
# Prefix lets test runs isolate their indexes on a shared Meilisearch.
MEILI_INDEX_PREFIX = os.environ.get('MEILI_INDEX_PREFIX', '')

# Object storage for audio/waveforms/clips (MinIO in dev, Cloudflare R2 in prod).
AUDIO_S3_ENDPOINT_URL = os.environ.get('AUDIO_S3_ENDPOINT_URL', 'http://localhost:9000')
AUDIO_S3_BUCKET = os.environ.get('AUDIO_S3_BUCKET', 'shaarawy')
AUDIO_S3_ACCESS_KEY_ID = os.environ.get('AUDIO_S3_ACCESS_KEY_ID', 'minioadmin')
AUDIO_S3_SECRET_ACCESS_KEY = os.environ.get('AUDIO_S3_SECRET_ACCESS_KEY', 'minioadmin')
AUDIO_S3_REGION = os.environ.get('AUDIO_S3_REGION', 'auto')
AUDIO_URL_TTL_SECONDS = int(os.environ.get('AUDIO_URL_TTL_SECONDS', str(6 * 3600)))

# Pluggable engines: 'stub' is deterministic and dependency-free (tests/dev);
# real backends live in pipeline/ and are selected in worker environments.
EMBEDDING_BACKEND = os.environ.get('EMBEDDING_BACKEND', 'stub')
ASR_BACKEND = os.environ.get('ASR_BACKEND', 'stub')
