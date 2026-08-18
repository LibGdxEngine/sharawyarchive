"""Observability bootstrap called from prod settings.

``maybe_init_sentry()`` is a no-op when ``SENTRY_DSN`` is absent or empty,
so importing it in test environments without a real DSN is always safe.
"""

from __future__ import annotations

import os


def maybe_init_sentry() -> None:
    """Initialise Sentry if SENTRY_DSN env var is non-empty."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    traces_sample_rate = float(
        os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")
    )

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=traces_sample_rate,
    )
