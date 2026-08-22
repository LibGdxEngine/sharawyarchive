"""Audio corpus: sources, audio assets, segments and their machine transcripts.

Everything produced by the ingestion pipeline lands here. Transcript text is ASR
output and must always be surfaced as a machine transcript — it is never Quran
text (see ``CLAUDE.md`` rule 1).

All durations and offsets are integer **milliseconds** (rule 5).
"""

from __future__ import annotations

from django.db import models


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


class CorrectionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


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
    """A 20-45s retrievable passage, the unit of search indexing."""

    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="chunks")
    idx = models.PositiveIntegerField()
    text = models.TextField()
    text_normalized = models.TextField()
    start_ms = models.PositiveBigIntegerField()
    end_ms = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["transcript_id", "idx"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "idx"], name="chunk_unique_transcript_idx"
            ),
        ]
        indexes = [
            models.Index(fields=["transcript", "idx"], name="chunk_transcript_idx"),
        ]

    def __str__(self) -> str:
        return f"chunk {self.idx} of transcript {self.transcript_id}"


class Topic(models.Model):
    """A theme the corpus keeps returning to, e.g. الصبر.

    Deliberately minimal: a topic is a human-curated label over a set of
    chunks. Nothing is visible to readers until a human sets ``is_published``,
    because an unreviewed topic label is a guess.
    """

    slug = models.SlugField(max_length=100, unique=True)
    name_ar = models.CharField(max_length=200)
    description_ar = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.slug} ({self.name_ar})"


class ChunkTopic(models.Model):
    """Membership of a chunk in a topic, with the cluster's confidence."""

    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="topic_links")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="chunk_links")
    score = models.FloatField()

    class Meta:
        ordering = ["topic_id", "-score"]
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "topic"], name="chunktopic_unique_chunk_topic"
            ),
        ]

    def __str__(self) -> str:
        return f"chunk {self.chunk_id} in {self.topic_id} ({self.score:.3f})"


class Correction(models.Model):
    """A reader's proposed fix to a span of machine transcript.

    Submitted anonymously and rate-limited by IP, so it is a suggestion queue,
    not an edit: approving one is a separate reviewed action (Phase 6). Word
    offsets are indices into ``TranscriptWord.idx`` of the chunk's transcript.
    """

    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="corrections")
    word_start = models.PositiveIntegerField()
    word_end = models.PositiveIntegerField()
    suggested_text = models.CharField(max_length=1000)
    status = models.CharField(
        max_length=16, choices=CorrectionStatus.choices, default=CorrectionStatus.PENDING
    )
    submitted_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="correction_status_idx"),
        ]

    def __str__(self) -> str:
        return f"correction {self.pk} on chunk {self.chunk_id} ({self.status})"


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
