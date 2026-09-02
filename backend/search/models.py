"""Models of the search app.

Exact search («بحث دقيق») keeps its state in Meilisearch and needs no rows here.
Smart search («بحث ذكي») records every request as a :class:`SmartQuery`: it is
the observability layer for v1 (cost, latency, statuses, feedback) and the
audit trail behind every answer the archive has shown.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class SmartStatus(models.TextChoices):
    ANSWERED = "answered", "answered"
    PARTIAL = "partial", "partial"
    NOT_FOUND = "not_found", "not_found"
    DEGRADED = "degraded", "degraded"
    ERROR = "error", "error"


class SmartVote(models.TextChoices):
    UP = "up", "up"
    DOWN = "down", "down"


class SmartQuery(models.Model):
    """One smart-search request, cache hits included.

    ``answer`` holds the verified response as returned to the client; ``plan``,
    ``candidate_ids`` and ``reranked`` hold the intermediate stages so a bad
    answer can be traced back to the stage that produced it. Client addresses
    are stored only as :func:`search.smart.cache.ip_hash` output.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_queries",
    )
    session_key = models.CharField(max_length=64, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)

    question = models.TextField()
    question_normalized = models.TextField()
    question_hash = models.CharField(max_length=64, db_index=True)
    lang = models.CharField(max_length=8, blank=True)
    filters = models.JSONField(default=dict, blank=True)

    plan = models.JSONField(null=True, blank=True)
    candidate_ids = models.JSONField(default=list, blank=True)
    reranked = models.JSONField(null=True, blank=True)
    answer = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=SmartStatus.choices)

    # Named ``models_used`` rather than ``models``: a field called ``models``
    # would shadow ``django.db.models`` inside this class body.
    models_used = models.JSONField(default=dict, blank=True)
    prompt_version = models.CharField(max_length=16, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    latency_ms = models.JSONField(default=dict, blank=True)
    cache_hit = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    feedback = models.CharField(max_length=4, choices=SmartVote.choices, blank=True)
    feedback_note = models.CharField(max_length=1000, blank=True)
    feedback_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="smartquery_status_created_idx"),
        ]

    def __str__(self) -> str:
        return f"smart query {self.id} [{self.status}]"

    @property
    def total_latency_ms(self) -> int | None:
        value = (self.latency_ms or {}).get("total")
        return int(value) if value is not None else None
