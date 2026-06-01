from .base import *
from dotenv import load_dotenv

# Load dev environment file if available
load_dotenv(os.path.join(BASE_DIR, '.env.dev'))

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
