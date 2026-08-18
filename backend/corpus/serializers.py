"""Response shapes for the corpus endpoints (``API_CONTRACT.md``).

Two project rules shape this module. Storage keys and content hashes never
appear in a payload — audio and waveforms are exposed only as presigned URLs
(rule 4). And every offset is an integer millisecond (rule 5), which is why the
transcript word keys are the one-letter ``i/t/s/e/c`` form: a segment can carry
thousands of words and the key names would otherwise outweigh the data.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Chunk, Correction, Segment, Source, Topic
from .storage import audio_key, presigned_url, waveform_key


class SourceBriefSerializer(serializers.ModelSerializer):
    """Provenance line shown next to a segment."""

    class Meta:
        model = Source
        fields = ('title', 'kind')


class SegmentDetailSerializer(serializers.ModelSerializer):
    """``GET /api/segments/{id}/``. Requires ``select_related`` on ``audio``,
    ``source`` and ``transcript``."""

    surah = serializers.IntegerField(source='surah_id', allow_null=True)
    source = SourceBriefSerializer(read_only=True)
    audio_url = serializers.SerializerMethodField()
    waveform_url = serializers.SerializerMethodField()
    transcript_version = serializers.SerializerMethodField()
    is_human_reviewed = serializers.SerializerMethodField()

    class Meta:
        model = Segment
        fields = (
            'id',
            'kind',
            'title',
            'surah',
            'ayah_start',
            'ayah_end',
            'duration_ms',
            'ordinal',
            'audio_url',
            'waveform_url',
            'source',
            'transcript_version',
            'is_human_reviewed',
        )

    @extend_schema_field(serializers.URLField())
    def get_audio_url(self, segment: Segment) -> str:
        return presigned_url(audio_key(segment.audio.sha256))

    @extend_schema_field(serializers.URLField())
    def get_waveform_url(self, segment: Segment) -> str:
        return presigned_url(waveform_key(segment.audio.sha256))

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_transcript_version(self, segment: Segment) -> int | None:
        transcript = getattr(segment, 'transcript', None)
        return None if transcript is None else transcript.version

    @extend_schema_field(serializers.BooleanField())
    def get_is_human_reviewed(self, segment: Segment) -> bool:
        transcript = getattr(segment, 'transcript', None)
        return bool(transcript and transcript.is_human_reviewed)


class TranscriptWordSerializer(serializers.Serializer):
    """``i`` index, ``t`` text, ``s``/``e`` start/end ms, ``c`` confidence."""

    i = serializers.IntegerField()
    t = serializers.CharField()
    s = serializers.IntegerField()
    e = serializers.IntegerField()
    c = serializers.FloatField(allow_null=True)


class TranscriptSerializer(serializers.Serializer):
    """``GET /api/segments/{id}/transcript/``.

    Declared for the schema only: the view assembles the word list straight
    from ``values_list`` because running six thousand rows through a serializer
    per request is pure overhead for a payload this mechanical.
    """

    version = serializers.IntegerField()
    engine = serializers.CharField()
    is_human_reviewed = serializers.BooleanField()
    words = TranscriptWordSerializer(many=True)


class ChunkResultSerializer(serializers.Serializer):
    """The search-result shape, reused wherever chunks are surfaced (topics,
    related passages) so one renderer on the frontend handles all of them.
    Mirrors :class:`search.services.SearchResult`."""

    chunk_id = serializers.IntegerField()
    segment_id = serializers.IntegerField()
    segment_title = serializers.CharField()
    surah = serializers.IntegerField(allow_null=True)
    ayah_start = serializers.IntegerField(allow_null=True)
    ayah_end = serializers.IntegerField(allow_null=True)
    kind = serializers.CharField()
    text = serializers.CharField()
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()

    def to_representation(self, instance: Chunk) -> dict[str, Any]:
        segment = instance.transcript.segment
        return {
            'chunk_id': instance.pk,
            'segment_id': segment.pk,
            'segment_title': segment.title,
            'surah': segment.surah_id,
            'ayah_start': segment.ayah_start,
            'ayah_end': segment.ayah_end,
            'kind': segment.kind,
            'text': instance.text,
            'start_ms': instance.start_ms,
            'end_ms': instance.end_ms,
        }


class TopicListSerializer(serializers.ModelSerializer):
    """One row of ``GET /api/topics/``."""

    chunk_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Topic
        fields = ('slug', 'name_ar', 'description_ar', 'chunk_count')


class TopicDetailSerializer(serializers.ModelSerializer):
    """``GET /api/topics/{slug}/``. The view attaches ``chunks`` — the topic's
    passages, best match first — before serialization."""

    chunk_count = serializers.IntegerField(read_only=True)
    chunks = ChunkResultSerializer(many=True, read_only=True)

    class Meta:
        model = Topic
        fields = ('slug', 'name_ar', 'description_ar', 'chunk_count', 'chunks')


class CorrectionCreateSerializer(serializers.ModelSerializer):
    """``POST /api/corrections/``. Word offsets index ``TranscriptWord.idx``;
    a one-word fix has ``word_start == word_end``."""

    chunk_id = serializers.PrimaryKeyRelatedField(
        source='chunk', queryset=Chunk.objects.all()
    )

    class Meta:
        model = Correction
        fields = ('chunk_id', 'word_start', 'word_end', 'suggested_text')

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs['word_end'] < attrs['word_start']:
            raise serializers.ValidationError(
                {'word_end': 'must not come before word_start'}
            )
        return attrs


class CorrectionCreatedSerializer(serializers.ModelSerializer):
    """The 201 body: a receipt, nothing the submitter did not already send."""

    class Meta:
        model = Correction
        fields = ('id', 'status')
