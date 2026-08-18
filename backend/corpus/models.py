"""Audio corpus: sources, audio assets, segments and their machine transcripts.

Everything produced by the ingestion pipeline lands here. Transcript text is ASR
output and must always be surfaced as a machine transcript — it is never Quran
text (see ``CLAUDE.md`` rule 1).

All durations and offsets are integer **milliseconds** (rule 5).
"""

from __future__ import annotations

from django.db import models
from pgvector.django import HnswIndex, VectorField

EMBEDDING_DIMENSIONS = 1024
"""multilingual-e5-large output width."""


class SegmentKind(models.TextChoices):
    RECITATION = "recitation", "Recitation"
    KHAWATIR = "khawatir", "Khawatir"


class SegmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    TRANSCRIBED = "transcribed", "Transcribed"
    ALIGNED = "aligned", "Aligned"
    INDEXED = "indexed", "Indexed"
    FAILED = "failed", "Failed"


class PipelineRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class Source(models.Model):
    """Where a body of audio came from, and under what rights."""

    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    rights_note = models.TextField(blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class AudioAsset(models.Model):
    """A single stored audio file, deduplicated by content hash."""

    storage_key = models.CharField(max_length=500)
    duration_ms = models.PositiveBigIntegerField()
    mime = models.CharField(max_length=100)
    bitrate = models.PositiveIntegerField(null=True, blank=True)
    sample_rate = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, unique=True)
    size_bytes = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["storage_key"]

    def __str__(self) -> str:
        return f"{self.storage_key} ({self.duration_ms} ms)"


class Segment(models.Model):
    """One playable unit of audio: a recitation range or a khawatir episode."""

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="segments")
    kind = models.CharField(max_length=16, choices=SegmentKind.choices)
    surah = models.ForeignKey(
        "quran.Surah",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segments",
    )
    ayah_start = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_end = models.PositiveSmallIntegerField(null=True, blank=True)
    audio = models.ForeignKey(AudioAsset, on_delete=models.PROTECT, related_name="segments")
    ordinal = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveBigIntegerField()
    title = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16, choices=SegmentStatus.choices, default=SegmentStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source_id", "ordinal", "id"]
        indexes = [
            models.Index(fields=["surah", "ayah_start"], name="segment_surah_ayah_idx"),
        ]

    def __str__(self) -> str:
        if self.surah_id and self.ayah_start:
            return f"{self.get_kind_display()} {self.surah_id}:{self.ayah_start}-{self.ayah_end}"
        return self.title or f"{self.get_kind_display()} segment {self.pk}"


class Transcript(models.Model):
    """Machine transcript of a segment. Never Quran text."""

    segment = models.OneToOneField(Segment, on_delete=models.CASCADE, related_name="transcript")
    engine = models.CharField(max_length=100)
    engine_version = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=16, default="ar")
    raw_text = models.TextField()
    text_normalized = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    is_human_reviewed = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["segment_id"]

    def __str__(self) -> str:
        return f"transcript of segment {self.segment_id} (v{self.version})"


class TranscriptWord(models.Model):
    """One aligned word with millisecond boundaries."""

    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="words")
    idx = models.PositiveIntegerField()
    text = models.CharField(max_length=100)
    start_ms = models.PositiveBigIntegerField()
    end_ms = models.PositiveBigIntegerField()
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["transcript_id", "idx"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "idx"], name="transcriptword_unique_transcript_idx"
            ),
        ]
        indexes = [
            models.Index(fields=["transcript", "start_ms"], name="tw_transcript_start_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.idx}] {self.text} @{self.start_ms}-{self.end_ms} ms"


class Chunk(models.Model):
    """A 20-45s retrievable passage with an optional embedding."""

    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="chunks")
    idx = models.PositiveIntegerField()
    text = models.TextField()
    text_normalized = models.TextField()
    start_ms = models.PositiveBigIntegerField()
    end_ms = models.PositiveBigIntegerField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)

    class Meta:
        ordering = ["transcript_id", "idx"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "idx"], name="chunk_unique_transcript_idx"
            ),
        ]
        indexes = [
            models.Index(fields=["transcript", "idx"], name="chunk_transcript_idx"),
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"chunk {self.idx} of transcript {self.transcript_id}"


class PipelineRun(models.Model):
    """One attempt at one pipeline stage. Failures land here with a traceback."""

    stage = models.CharField(max_length=50)
    segment = models.ForeignKey(
        Segment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    status = models.CharField(max_length=16, choices=PipelineRunStatus.choices)
    detail = models.TextField(blank=True, help_text="Free text or traceback.")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.stage} / {self.status} (segment {self.segment_id})"
