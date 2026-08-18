"""Bootstrap Django for a process that lives outside ``backend/``.

Every pipeline entry point (driver CLI, Celery worker, test session) calls
:func:`setup_django` before importing anything from ``corpus``/``quran``. It is
idempotent, so importing several pipeline modules in one process is fine.

Defaults assume the host-published docker compose services (postgres on
``localhost:5432``). Anything already exported in the environment wins, so a
container that sets ``DB_HOST=db`` keeps working unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
"""The Django project root — added to ``sys.path`` so ``core.settings`` imports."""

DEFAULT_SETTINGS_MODULE = "core.settings.dev"

ENV_DEFAULTS: dict[str, str] = {
    "DJANGO_SETTINGS_MODULE": DEFAULT_SETTINGS_MODULE,
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "postgres",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
}

_done = False


def setup_django() -> None:
    """Put ``backend/`` on ``sys.path``, apply env defaults, call ``django.setup()``.

    Safe to call repeatedly; the second and later calls are no-ops.
    """
    global _done
    if _done:
        return

    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)

    for key, value in ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)

    import django

    django.setup()
    _done = True
