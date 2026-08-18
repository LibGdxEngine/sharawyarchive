import os

from .base import *  # noqa: F401, F403

# Enforce secret key configuration in production
SECRET_KEY = os.environ['SECRET_KEY']

DEBUG = False

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

# Enforce PostgreSQL database configuration in production
DB_NAME = os.environ['DB_NAME']
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_HOST = os.environ['DB_HOST']
DB_PORT = os.environ['DB_PORT']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
    }
}

# CORS settings
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
CORS_ALLOWED_ORIGINS = [origin for origin in CORS_ALLOWED_ORIGINS if origin]

# CSRF settings (essential when running behind Caddy/Nginx)
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
CSRF_TRUSTED_ORIGINS = [origin for origin in CSRF_TRUSTED_ORIGINS if origin]

# Production Security Best Practices
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# HSTS settings (only apply if SSL redirect is active)
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# Engines: a production deploy must never run on the stub ASR/embedding
# backends. base.py defaults both to 'stub', so an operator who follows
# DEPLOY.md without exporting them would otherwise index fabricated speech and
# attribute it to the Sheikh (CLAUDE.md rule 1). Refuse to boot instead.
# ---------------------------------------------------------------------------
from core.engines_guard import check_engines  # noqa: E402

check_engines(os.environ)

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "core.logging.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# Suppress noisy third-party loggers.
for _noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
    LOGGING["loggers"][_noisy] = {  # type: ignore[index]
        "handlers": ["console"],
        "level": "WARNING",
        "propagate": False,
    }

# ---------------------------------------------------------------------------
# Sentry — no-op when SENTRY_DSN is absent.
# ---------------------------------------------------------------------------
from core.observability import maybe_init_sentry  # noqa: E402

maybe_init_sentry()
