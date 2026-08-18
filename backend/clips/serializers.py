"""Request and response shapes for clip render jobs (``API_CONTRACT.md``)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from corpus.models import Segment
from corpus.storage import clip_key, presigned_url

from .models import MAX_SPAN_MS, MIN_SPAN_MS, Clip, ClipStatus


class ClipCreateSerializer(serializers.ModelSerializer):
    """``POST /api/clips/``. Rendering is somebody's CPU, so the range is
    checked against the segment before a job is ever created."""

    segment_id = serializers.PrimaryKeyRelatedField(
        source='segment', queryset=Segment.objects.all()
    )

    class Meta:
        model = Clip
        fields = ('segment_id', 'start_ms', 'end_ms', 'preset')
        # The model's unique constraint would otherwise become a 400. Asking
        # twice for the same clip is a cache hit, not a mistake — the view
        # answers with the job that already exists.
        validators: list[object] = []

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        span = attrs['end_ms'] - attrs['start_ms']
        if not MIN_SPAN_MS <= span <= MAX_SPAN_MS:
            raise serializers.ValidationError(
                {'end_ms': f'clip length must be between {MIN_SPAN_MS} and {MAX_SPAN_MS} ms'}
            )
        duration_ms = attrs['segment'].duration_ms
        if attrs['end_ms'] > duration_ms:
            raise serializers.ValidationError(
                {'end_ms': f'must not run past the segment ({duration_ms} ms)'}
            )
        return attrs


class ClipStatusSerializer(serializers.ModelSerializer):
    """The body of both clip POST outcomes: created, or already queued."""

    class Meta:
        model = Clip
        fields = ('id', 'status')


class ClipDetailSerializer(serializers.ModelSerializer):
    """``GET /api/clips/{id}/``. ``video_url`` appears only once the render
    finished — a queued or failed job has nothing to hand out."""

    video_url = serializers.SerializerMethodField()

    class Meta:
        model = Clip
        fields = ('id', 'status', 'video_url')

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_video_url(self, clip: Clip) -> str | None:
        if clip.status != ClipStatus.DONE:
            return None
        key = clip.storage_key or clip_key(
            clip.segment_id, clip.start_ms, clip.end_ms, clip.preset
        )
        return presigned_url(key)
