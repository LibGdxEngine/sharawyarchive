"""Liveness and readiness probes.

Mounted at the site root rather than under ``/api/`` so an orchestrator can
reach them without knowing the API prefix. Plain Django views on purpose:
``/healthz`` must answer without touching a single dependency, and neither
probe belongs in the public OpenAPI schema.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

__all__ = ['healthz', 'readyz']


@require_GET
def healthz(request: HttpRequest) -> JsonResponse:
    """``GET /healthz`` — the process is up. No database, no network."""
    return JsonResponse({'status': 'ok'})


def _database_ok() -> bool:
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        return cursor.fetchone() == (1,)


def _redis_ok() -> bool:
    import redis

    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2)
    try:
        return bool(client.ping())
    finally:
        client.close()


def _meilisearch_ok() -> bool:
    from search.services import meili_client

    return meili_client().health().get('status') == 'available'


CHECKS = {
    'db': _database_ok,
    'redis': _redis_ok,
    'meilisearch': _meilisearch_ok,
}


@require_GET
def readyz(request: HttpRequest) -> JsonResponse:
    """``GET /readyz`` — every dependency answered. 503 names the ones that did
    not, so a failing deploy says *which* backing service is missing."""
    results = {}
    for name, check in CHECKS.items():
        try:
            results[name] = check()
        except Exception:
            logger.exception('readiness check %s failed', name)
            results[name] = False
    status = 200 if all(results.values()) else 503
    return JsonResponse(results, status=status)
