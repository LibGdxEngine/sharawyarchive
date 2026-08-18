from dotenv import load_dotenv

from .base import *  # noqa: F401, F403

# Load .env.dev from backend/ first (BASE_DIR), then repo root (BASE_DIR.parent).
# Docker compose mounts the file at the repo root; bare-venv runs expect it there
# too.  First hit wins; missing file is silently skipped.
_env_candidates = [
    BASE_DIR / ".env.dev",
    BASE_DIR.parent / ".env.dev",
]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
        break

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-secret-key-template-project-1234')

DEBUG = True

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Default to SQLite for easy non-docker runs, but swap to Postgres when available in environment
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')

if all([DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT]):
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
    }

# CORS settings for dev
CORS_ALLOW_ALL_ORIGINS = True
