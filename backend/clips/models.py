"""Shareable clips rendered from a slice of a segment — video cards or audio.

A clip row is a render *job*: the API only ever enqueues one, and the renderer
(Phase 8) fills in ``storage_key`` or ``error``. The unique constraint over
(segment, range, preset, output) makes the job its own cache — asking twice for
the same clip hands back the first one instead of burning another render.

Offsets are integer milliseconds (``CLAUDE.md`` rule 5).
"""

from __future__ import annotations

import uuid

from django.db import models

MIN_SPAN_MS = 1_000
"""Shortest clip the API accepts: one full second, so a render is never a
degenerate empty file."""

MAX_VIDEO_SPAN_MS = 5 * 60 * 1_000
"""Ceiling on a *video* clip — a capacity limit, not an editorial one.

A card is a 1080x1920 H.264 encode with an animated waveform under burned-in
subtitles; on the two-core worker that also serves the site, an hour-long
segment rendered whole would occupy both cores for hours. Audio-only clips are
a straight AAC transcode and stay uncapped, so they may still run to the end of
the segment as ``API_CONTRACT.md`` amendment 9 allows."""


class ClipPreset(models.TextChoices):
    CLASSIC = "classic", "Classic"
    NIGHT = "night", "Night"
    LIGHT = "light", "Light"


class ClipOutput(models.TextChoices):
    """What a clip job produces: a video card or a plain audio file."""

    VIDEO = "video", "Video"
    AUDIO = "audio", "Audio"


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
    output = models.CharField(
        max_length=8, choices=ClipOutput.choices, default=ClipOutput.VIDEO
    )
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
                fields=["segment", "start_ms", "end_ms", "preset", "output"],
                name="clip_unique_render",
            ),
        ]

    def __str__(self) -> str:
        return f"clip {self.pk} of segment {self.segment_id} ({self.status})"
