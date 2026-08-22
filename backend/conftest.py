"""Pytest bootstrap for the backend.

The suite runs against Postgres for production parity (and the migration
history still creates pgvector columns from 0001). These defaults point the
suite at the docker compose ``db`` service as published on the host; anything
already exported in the environment wins.
"""

from __future__ import annotations

import os

_DB_DEFAULTS = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "postgres",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
}

for _key, _value in _DB_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")
