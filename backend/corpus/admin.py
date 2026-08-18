from django.contrib import admin

from .models import (
    AudioAsset,
    Chunk,
    PipelineRun,
    Segment,
    Source,
    Transcript,
    TranscriptWord,
)


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
