"""Request and response shapes for clip render jobs (``API_CONTRACT.md``)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from corpus.models import Segment
from corpus.storage import clip_key, presigned_url

from .models import MAX_VIDEO_SPAN_MS, MIN_SPAN_MS, Clip, ClipOutput, ClipStatus
from .naming import download_filename


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
        # A video card is a 1080x1920 H.264 encode with an animated waveform
        # under burned-in subtitles. An hour of that is hours of CPU on a
        # two-core worker, and the render queue is shared with the site.
        # Audio is a straight AAC transcode and needs no such ceiling.
        if attrs.get('output', ClipOutput.VIDEO) == ClipOutput.VIDEO and span > MAX_VIDEO_SPAN_MS:
            raise serializers.ValidationError(
                {'end_ms': f'a video clip may not exceed {MAX_VIDEO_SPAN_MS} ms'}
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
    media_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    download_filename = serializers.SerializerMethodField()

    class Meta:
        model = Clip
        fields = (
            'id',
            'status',
            'output',
            'video_url',
            'audio_url',
            'media_url',
            'download_url',
            'download_filename',
        )

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

    def _site_url(self, route: str, clip: Clip) -> str:
        """Absolute address of one of the clip's own routes.

        Built from ``SITE_BASE_URL`` rather than from the request, because the
        request is not always the browser's: the frontend renders the clip page
        server-side against ``BACKEND_API_URL`` (``http://backend:8000/api``),
        and ``build_absolute_uri`` would put that cluster-internal host into
        markup and OpenGraph metadata that only ever leaves the cluster.
        """
        path = reverse(route, kwargs={'pk': clip.pk})
        return f'{settings.SITE_BASE_URL.rstrip("/")}{path}'

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_media_url(self, clip: Clip) -> str | None:
        """A stable address for playing the clip, whatever its output.

        Unlike ``video_url``/``audio_url`` this is a site URL that re-signs the
        bucket object per request, so it survives being embedded in a shared
        page or an OpenGraph card past the presigned URL's six hours.
        """
        if clip.status != ClipStatus.DONE:
            return None
        return self._site_url('clip-media', clip)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_download_url(self, clip: Clip) -> str | None:
        """The same bytes, but as a save rather than a play.

        One field covers both outputs — it points at whichever object the job
        produced. Being a site URL also means the browser is never asked to
        honour ``download`` across origins, which HTML ignores.
        """
        if clip.status != ClipStatus.DONE:
            return None
        return self._site_url('clip-download', clip)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_filename(self, clip: Clip) -> str | None:
        if clip.status != ClipStatus.DONE:
            return None
        return download_filename(clip)
