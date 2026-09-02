"""Models of the search app.

Exact search («بحث دقيق») keeps its state in Meilisearch and needs no rows here.
Smart search («بحث ذكي») adds two tables: :class:`Passage`, the retrieval unit
(a window of consecutive chunks with a text-search vector and an embedding),
and :class:`SmartQuery`, one row per request — the observability layer for v1
(cost, latency, statuses, feedback) and the audit trail behind every answer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from pgvector.django import HalfVectorField, HnswIndex


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


EMBEDDING_DIMENSIONS = 1024
"""Width of the ``halfvec`` column. Changing it is a migration and a full re-embed."""


class Passage(models.Model):
    """The smart-search retrieval unit: ~150-300 words of consecutive chunks.

    Built by :mod:`search.smart.passages` over the existing :class:`corpus.Chunk`
    rows (which stay the unit of exact search, corrections and clips), with a
    one-chunk overlap between neighbours. ``text`` is the display text;
    ``text_normalized`` the comparison form (CLAUDE.md rule 2); ``text_stem``
    the lexical-index form (light-stemmed, stop words removed) behind the
    generated ``tsv`` column. ``content_hash`` makes rebuilding idempotent and
    ``embedded_hash`` tells whether the stored vector still matches the text.
    """

    transcript = models.ForeignKey(
        "corpus.Transcript", on_delete=models.CASCADE, related_name="passages"
    )
    segment = models.ForeignKey("corpus.Segment", on_delete=models.CASCADE, related_name="passages")
    surah = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_start = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_end = models.PositiveSmallIntegerField(null=True, blank=True)
    ordinal = models.PositiveIntegerField()
    chunk_idx_start = models.PositiveIntegerField()
    chunk_idx_end = models.PositiveIntegerField()
    start_ms = models.PositiveBigIntegerField()
    end_ms = models.PositiveBigIntegerField()
    word_count = models.PositiveIntegerField()
    header = models.CharField(max_length=300)
    text = models.TextField()
    text_normalized = models.TextField()
    text_stem = models.TextField()
    tsv = models.GeneratedField(
        expression=SearchVector("text_stem", config="simple"),
        output_field=SearchVectorField(),
        db_persist=True,
    )
    content_hash = models.CharField(max_length=64, db_index=True)
    embedding = HalfVectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    embedded_hash = models.CharField(max_length=64, blank=True)
    embedded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["transcript_id", "ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "ordinal"], name="passage_unique_transcript_ordinal"
            ),
        ]
        indexes = [
            GinIndex(fields=["tsv"], name="passage_tsv_gin"),
            HnswIndex(
                name="passage_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["halfvec_cosine_ops"],
            ),
            models.Index(fields=["segment", "ordinal"], name="passage_segment_ordinal_idx"),
            models.Index(fields=["surah", "ayah_start"], name="passage_surah_ayah_idx"),
        ]

    def __str__(self) -> str:
        return f"passage {self.ordinal} of transcript {self.transcript_id}"

    @property
    def is_embedded(self) -> bool:
        return self.embedding is not None and self.embedded_hash == self.content_hash
