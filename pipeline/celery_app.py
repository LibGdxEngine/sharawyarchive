"""The pipeline worker's own Celery app.

Django dispatches work here **by task name only**
(``celery_app.send_task('pipeline.ingest', ...)``), so the web image never
imports this module or anything else under ``pipeline/``.

Run a worker with::

    celery -A pipeline.celery_app worker -Q pipeline

The queue name matches ``CELERY_TASK_ROUTES = {'pipeline.*': {'queue': 'pipeline'}}``
in ``core/settings/base.py``, which is what makes the routing work from the
Django side.
"""

from __future__ import annotations

import os

from celery import Celery

from pipeline.django_setup import setup_django

# Read the broker configuration *before* django.setup(): loading the Django dev
# settings also loads backend/.env.dev, which points at the in-compose hostnames
# (redis://redis:6379/0). A worker started on the host needs localhost instead,
# so the environment as the operator actually set it takes precedence.
_ENV_BROKER = os.environ.get("PIPELINE_BROKER_URL") or os.environ.get("CELERY_BROKER_URL")
_ENV_BACKEND = os.environ.get("PIPELINE_RESULT_BACKEND") or os.environ.get(
    "CELERY_RESULT_BACKEND"
)

BROKER_URL = _ENV_BROKER or "redis://localhost:6379/0"
RESULT_BACKEND = _ENV_BACKEND or BROKER_URL

QUEUE = "pipeline"

setup_django()

app = Celery(
    "pipeline",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    # Imported when the worker finalizes, which is what registers the stages.
    # Late enough that pipeline.stages can import this module in return.
    include=["pipeline.stages"],
)

app.conf.update(
    task_default_queue=QUEUE,
    task_routes={"pipeline.*": {"queue": QUEUE}},
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
