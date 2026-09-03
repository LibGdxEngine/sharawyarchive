import os
from pathlib import Path
from urllib.parse import urlparse

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
    # Session + Basic only: the public API is anonymous and the admin is the
    # only authenticated surface, so there is no token flow to support.
    'DEFAULT_AUTHENTICATION_CLASSES': [
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
        'smart': '20/hour',
        'smart_feedback': '60/hour',
    },
    # How many reverse proxies sit in front of this process. Everything that
    # identifies a client by address — the throttles and
    # ``api.ip.client_ip`` — trusts exactly this many trailing
    # ``X-Forwarded-For`` entries; the rest of the header is client-written and
    # forgeable. One hop is the deployed topology (Caddy → gunicorn).
    'NUM_PROXIES': int(os.environ.get('DRF_NUM_PROXIES', '1')),
}

# Throttle counters live in the cache, so a LocMemCache would give every
# gunicorn worker its own budget and multiply every published rate by the
# worker count. Redis is the shared store that makes the rates in
# DEFAULT_THROTTLE_RATES mean what API_CONTRACT.md says they mean.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('CACHE_REDIS_URL', 'redis://localhost:6379/2'),
    }
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
        'ClipOutputEnum': 'clips.models.ClipOutput',
        'CorrectionStatusEnum': 'corpus.models.CorrectionStatus',
    },
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


# ---------------------------------------------------------------------------
# Smart search («بحث ذكي»): LLM-assisted, cited answers over the machine
# transcripts (docs/smart-search/). Every model call goes through OpenRouter.
# The feature stays off until the Phase 6 evaluation gates pass; with the flag
# off the endpoint answers 503 and no provider call is ever made.
# ---------------------------------------------------------------------------
def _env_flag(name: str, default: str = 'false') -> bool:
    return os.environ.get(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}


SMART_ENABLED = _env_flag('SMART_ENABLED')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
# Slugs verified on openrouter.ai on 2026-09-02 (docs/smart-search/audit.md §4).
SMART_PLANNER_MODEL = os.environ.get('SMART_PLANNER_MODEL', 'google/gemini-3.1-flash-lite')
SMART_RERANK_MODEL = os.environ.get('SMART_RERANK_MODEL', 'google/gemini-3.1-flash-lite')
SMART_GENERATOR_MODEL = os.environ.get('SMART_GENERATOR_MODEL', 'google/gemini-3.8-flash')
# Offline evaluation only (manage.py smart_eval --judge); never on the request path.
SMART_JUDGE_MODEL = os.environ.get('SMART_JUDGE_MODEL', 'google/gemini-3.8-flash')
# Query and passage vectors MUST come from the same model and dimension; the
# tag "<model>@<dims>" is stored on every embedded row and in every cache key.
SMART_EMBEDDING_MODEL = os.environ.get('SMART_EMBEDDING_MODEL', 'qwen/qwen3-embedding-8b')
SMART_EMBEDDING_DIMENSIONS = int(os.environ.get('SMART_EMBEDDING_DIMENSIONS', '1024'))
SMART_DAILY_BUDGET_USD = float(os.environ.get('SMART_DAILY_BUDGET_USD', '5'))
SMART_MAX_INFLIGHT = int(os.environ.get('SMART_MAX_INFLIGHT', '3'))
# Whole-request budget; each stage is given min(its timeout, what is left).
SMART_REQUEST_BUDGET_S = float(os.environ.get('SMART_REQUEST_BUDGET_S', '40'))
SMART_STAGE_TIMEOUTS_S = {'planner': 8.0, 'embed': 6.0, 'rerank': 12.0, 'generate': 30.0}
# Completion budget for the generator. Thinking models bill their reasoning
# against this same cap — medium effort on a tafseer question was measured at
# ~1,650 reasoning tokens — so the answer needs room well beyond its own length
# or the JSON arrives cut off mid-string.
SMART_GENERATOR_MAX_TOKENS = int(os.environ.get('SMART_GENERATOR_MAX_TOKENS', '4000'))
# Tried in order by OpenRouter when the first model errors (it rate-limits its
# shared Google endpoint under load). Empty disables failover.
SMART_GENERATOR_FALLBACK_MODELS = [
    model
    for model in os.environ.get(
        'SMART_GENERATOR_FALLBACK_MODELS', 'google/gemini-3.1-flash-lite'
    ).split(',')
    if model.strip()
]
SMART_CACHE_TTL_S = 7 * 24 * 3600
# rapidfuzz partial_ratio_alignment score a quote must reach to be cited.
SMART_QUOTE_MIN_SCORE = int(os.environ.get('SMART_QUOTE_MIN_SCORE', '90'))
# Fallback prices, USD per million tokens (prompt, completion), used only when
# a response carries no `usage.cost`. List prices as of 2026-09-02.
SMART_PRICES_USD_PER_MTOKEN: dict[str, tuple[float, float]] = {
    'google/gemini-3.1-flash-lite': (0.25, 1.50),
    'google/gemini-3.8-flash': (0.75, 3.75),
    'qwen/qwen3-embedding-8b': (0.01, 0.0),
    'qwen/qwen3-embedding-0.6b': (0.01, 0.0),
}

# Object storage for audio/waveforms/clips (MinIO in dev, Cloudflare R2 in prod).
AUDIO_S3_ENDPOINT_URL = os.environ.get('AUDIO_S3_ENDPOINT_URL', 'http://localhost:9000')
AUDIO_S3_BUCKET = os.environ.get('AUDIO_S3_BUCKET', 'shaarawy')
AUDIO_S3_ACCESS_KEY_ID = os.environ.get('AUDIO_S3_ACCESS_KEY_ID', 'minioadmin')
AUDIO_S3_SECRET_ACCESS_KEY = os.environ.get('AUDIO_S3_SECRET_ACCESS_KEY', 'minioadmin')
AUDIO_S3_REGION = os.environ.get('AUDIO_S3_REGION', 'auto')
AUDIO_URL_TTL_SECONDS = int(os.environ.get('AUDIO_URL_TTL_SECONDS', str(6 * 3600)))
AUDIO_PUBLIC_ENDPOINT_URL = os.environ.get(
    'AUDIO_PUBLIC_ENDPOINT_URL', AUDIO_S3_ENDPOINT_URL
)

# Pluggable engines: 'stub' is deterministic and dependency-free (tests/dev);
# real backends live in pipeline/ and are selected in worker environments.
# core.settings.prod refuses to boot on the stub (core.engines_guard).
# ASR_BACKEND: 'stub' | 'cohere' (hosted API, default in prod) | 'faster-whisper' (local GPU).
ASR_BACKEND = os.environ.get('ASR_BACKEND', 'stub')

# Public site origin, used for sitemap URLs and as the default clip watermark.
SITE_BASE_URL = os.environ.get('SITE_BASE_URL', 'http://localhost:3000')

# Burned into every rendered clip card (US-013), so it has to name the archive
# a viewer can actually reach. Defaults to the deployment's own host rather
# than a literal, which is how a fork ends up stamping somebody else's domain.
# The "machine transcript" mark is *not* part of this string: see
# clips.rendering.MACHINE_TRANSCRIPT_MARK.
CLIP_ATTRIBUTION = os.environ.get(
    'CLIP_ATTRIBUTION',
    f'أرشيف الشعراوي · {urlparse(SITE_BASE_URL).hostname or "shaarawy.archive"}',
)
