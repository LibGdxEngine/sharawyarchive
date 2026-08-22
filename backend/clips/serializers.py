"""Request and response shapes for clip render jobs (``API_CONTRACT.md``)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from corpus.models import Segment
from corpus.storage import clip_key, presigned_url

from .models import MIN_SPAN_MS, Clip, ClipOutput, ClipStatus


class ClipCreateSerializer(serializers.ModelSerializer):
    """``POST /api/clips/``. Rendering is somebody's CPU, so the range is
    checked against the segment before a job is ever created."""

    segment_id = serializers.PrimaryKeyRelatedField(
        source='segment', queryset=Segment.objects.all()
    )

    class Meta:
        model = Clip
        fields = ('segment_id', 'start_ms', 'end_ms', 'preset', 'output')
        # The model's unique constraint would otherwise become a 400. Asking
        # twice for the same clip is a cache hit, not a mistake — the view
        # answers with the job that already exists.
        validators: list[object] = []

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        span = attrs['end_ms'] - attrs['start_ms']
        duration_ms = attrs['segment'].duration_ms
        if not MIN_SPAN_MS <= span <= duration_ms:
            raise serializers.ValidationError(
                {'end_ms': f'clip length must be between {MIN_SPAN_MS} and '
                           f'the segment length ({duration_ms} ms)'}
            )
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
    """``GET /api/clips/{id}/``. Exactly one of ``video_url``/``audio_url``
    appears once the render finishes (which one is set by the job's ``output``);
    a queued or failed job has neither."""

    video_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = Clip
        fields = ('id', 'status', 'output', 'video_url', 'audio_url')

    def _clip_key(self, clip: Clip) -> str:
        return clip.storage_key or clip_key(
            clip.segment_id, clip.start_ms, clip.end_ms, clip.preset, clip.output
        )

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_video_url(self, clip: Clip) -> str | None:
        if clip.status != ClipStatus.DONE or clip.output != ClipOutput.VIDEO:
            return None
        return presigned_url(self._clip_key(clip))

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_audio_url(self, clip: Clip) -> str | None:
        if clip.status != ClipStatus.DONE or clip.output != ClipOutput.AUDIO:
            return None
        return presigned_url(self._clip_key(clip))
