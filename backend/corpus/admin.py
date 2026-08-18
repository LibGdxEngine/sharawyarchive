"""Admin screens for the corpus.

Two of them do real work — the correction review queue (Phase 6) and the topic
publish gate (Phase 7) — and neither implements it here: the queue calls
:mod:`corpus.corrections` and the gate flips a boolean that
:mod:`corpus.topics` deliberately leaves off. Keeping the logic out of the
admin is what lets it be tested without a browser.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join

from . import corrections
from .models import (
    AudioAsset,
    Chunk,
    ChunkTopic,
    Correction,
    PipelineRun,
    Segment,
    Source,
    Topic,
    Transcript,
    TranscriptWord,
)
from .storage import audio_key, presigned_url

CENTRAL_PREVIEW = 5
"""Passages shown on a topic's page, best match first."""

DASH = "—"


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "kind")
    search_fields = ("title", "description")


@admin.register(AudioAsset)
class AudioAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "storage_key", "duration_ms", "mime", "size_bytes")
    search_fields = ("storage_key", "sha256")


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "kind", "surah", "ayah_start", "ayah_end", "status")
    list_filter = ("kind", "status")
    search_fields = ("title",)
    raw_id_fields = ("source", "surah", "audio")


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("id", "segment", "engine", "version", "word_count", "is_human_reviewed")
    list_filter = ("engine", "is_human_reviewed")
    raw_id_fields = ("segment",)


@admin.register(TranscriptWord)
class TranscriptWordAdmin(admin.ModelAdmin):
    list_display = ("id", "transcript", "idx", "text", "start_ms", "end_ms")
    raw_id_fields = ("transcript",)


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "transcript", "idx", "start_ms", "end_ms")
    raw_id_fields = ("transcript",)
    search_fields = ("text_normalized",)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("id", "stage", "segment", "status", "started_at", "finished_at")
    list_filter = ("stage", "status")
    raw_id_fields = ("segment",)


@admin.register(Correction)
class CorrectionAdmin(admin.ModelAdmin):
    """The review queue: read the two versions, hear the audio, act.

    Every field is read-only. A correction is a record of what a reader sent,
    and the only two things a reviewer may do to it are the two actions —
    which go through :mod:`corpus.corrections` so that approving from a script
    and approving from this screen are the same operation.
    """

    list_display = ("id", "chunk", "word_range", "suggested_text", "status", "created_at")
    list_filter = ("status", "created_at")
    list_select_related = ("chunk",)
    date_hierarchy = "created_at"
    actions = ("approve_selected", "reject_selected")
    fields = (
        "chunk",
        "word_range",
        "comparison",
        "play_range",
        "status",
        "submitted_ip",
        "created_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Corrections arrive from readers, not from reviewers."""
        return False

    @admin.display(description="words")
    def word_range(self, correction: Correction) -> str:
        return f"{correction.word_start}–{correction.word_end}"

    @admin.display(description="original / suggested")
    def comparison(self, correction: Correction) -> str:
        return format_html(
            '<table dir="rtl" lang="ar" style="width:100%; table-layout:fixed">'
            "<tr><th>النص الحالي (تفريغ آلي)</th><th>التصحيح المقترح</th></tr>"
            '<tr><td style="padding:.5rem; vertical-align:top">{}</td>'
            '<td style="padding:.5rem; vertical-align:top">{}</td></tr></table>',
            corrections.original_text_for(correction) or DASH,
            correction.suggested_text,
        )

    @admin.display(description="play range")
    def play_range(self, correction: Correction) -> str:
        """A link straight to the second the words are spoken.

        The href is a presigned URL (rule 4) with a media fragment, so the
        browser's own player seeks there; the millisecond bounds are spelled
        out next to it because the fragment has to be seconds.
        """
        span = corrections.word_span_ms(correction)
        if span is None:
            return DASH
        start_ms, end_ms = span
        segment = correction.chunk.transcript.segment
        return format_html(
            '<a href="{}#t={}" target="_blank" rel="noopener">▶ اسمع</a> '
            "<small>{}–{} ms</small>",
            presigned_url(audio_key(segment.audio.sha256)),
            f"{start_ms / 1000:.3f}",
            start_ms,
            end_ms,
        )

    @admin.action(description="Approve selected corrections (rewrites the transcript)")
    def approve_selected(self, request: HttpRequest, queryset: QuerySet[Correction]) -> None:
        applied, rebuilt = 0, 0
        for correction in queryset.select_related("chunk__transcript__segment"):
            try:
                result = corrections.approve(
                    correction, reviewed_by=request.user.get_username()
                )
            except corrections.CorrectionError as error:
                self.message_user(request, f"correction {correction.pk}: {error}", messages.ERROR)
                continue
            applied += 1
            rebuilt += len(result.chunk_ids)
        if applied:
            self.message_user(
                request,
                f"{applied} correction(s) applied, {rebuilt} passage(s) rebuilt and reindexed",
                messages.SUCCESS,
            )

    @admin.action(description="Reject selected corrections")
    def reject_selected(self, request: HttpRequest, queryset: QuerySet[Correction]) -> None:
        rejected = 0
        for correction in queryset:
            try:
                corrections.reject(correction)
            except corrections.CorrectionError as error:
                self.message_user(request, f"correction {correction.pk}: {error}", messages.ERROR)
                continue
            rejected += 1
        if rejected:
            self.message_user(request, f"{rejected} correction(s) rejected", messages.SUCCESS)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    """The publish gate for machine-made topics.

    ``build_topics`` creates every topic unpublished; nothing about one reaches
    a reader until someone reads its passages here and ticks the box.
    """

    list_display = ("slug", "name_ar", "chunk_count", "is_published", "created_at")
    list_display_links = ("slug",)
    list_editable = ("is_published",)
    list_filter = ("is_published",)
    search_fields = ("slug", "name_ar", "description_ar")
    actions = ("publish_selected", "unpublish_selected")
    fields = ("slug", "name_ar", "description_ar", "is_published", "central_chunks")
    readonly_fields = ("central_chunks",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Topic]:
        return super().get_queryset(request).annotate(chunk_count=Count("chunk_links"))

    @admin.display(description="passages", ordering="chunk_count")
    def chunk_count(self, topic: Topic) -> int:
        return topic.chunk_count  # type: ignore[attr-defined]

    @admin.display(description="most central passages")
    def central_chunks(self, topic: Topic) -> str:
        rows = (
            ChunkTopic.objects.filter(topic=topic)
            .select_related("chunk")
            .order_by("-score")[:CENTRAL_PREVIEW]
        )
        if not rows:
            return DASH
        return format_html(
            '<ol dir="rtl" lang="ar">{}</ol>',
            format_html_join(
                "",
                "<li>{} <small>({})</small></li>",
                ((row.chunk.text, f"{row.score:.3f}") for row in rows),
            ),
        )

    @admin.action(description="Publish selected topics")
    def publish_selected(self, request: HttpRequest, queryset: QuerySet[Topic]) -> None:
        self.message_user(request, f"{queryset.update(is_published=True)} topic(s) published")

    @admin.action(description="Unpublish selected topics")
    def unpublish_selected(self, request: HttpRequest, queryset: QuerySet[Topic]) -> None:
        self.message_user(request, f"{queryset.update(is_published=False)} topic(s) hidden")
