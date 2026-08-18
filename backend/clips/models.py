"""Shareable video clips rendered from a slice of a segment.

A clip row is a render *job*: the API only ever enqueues one, and the renderer
(Phase 8) fills in ``storage_key`` or ``error``. The unique constraint over
(segment, range, preset) makes the job its own cache — asking twice for the
same clip hands back the first one instead of burning another render.

Offsets are integer milliseconds (``CLAUDE.md`` rule 5).
"""

from __future__ import annotations

import uuid

from django.db import models

MIN_SPAN_MS = 15_000
MAX_SPAN_MS = 60_000
"""Clip length bounds from API_CONTRACT.md: long enough to carry a thought,
short enough for a social timeline."""


class ClipPreset(models.TextChoices):
    CLASSIC = "classic", "Classic"
    NIGHT = "night", "Night"
    LIGHT = "light", "Light"


class ClipStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RENDERING = "rendering", "Rendering"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class Clip(models.Model):
    """One render of ``segment[start_ms:end_ms]`` in one visual preset."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        "corpus.Segment", on_delete=models.CASCADE, related_name="clips"
    )
    start_ms = models.PositiveBigIntegerField()
    end_ms = models.PositiveBigIntegerField()
    preset = models.CharField(max_length=16, choices=ClipPreset.choices)
    status = models.CharField(
        max_length=16, choices=ClipStatus.choices, default=ClipStatus.QUEUED
    )
    storage_key = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["segment", "start_ms", "end_ms", "preset"],
                name="clip_unique_render",
            ),
        ]

    def __str__(self) -> str:
        return f"clip {self.pk} of segment {self.segment_id} ({self.status})"
