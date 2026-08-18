"""Response shapes for the corpus endpoints (``API_CONTRACT.md``).

Two project rules shape this module. Rule 4: no payload carries a raw storage
key or a content hash as a *field* — audio and waveforms are exposed only
through :func:`~corpus.storage.presigned_url`, and there is no ``sha256`` or
``storage_key`` for a client to read, derive a bucket path from, or store. A
presigned URL does necessarily contain the object's path, because that is what
it is a signature over; what it does not give away is the hash of anything
else, a stable link, or access after the signature expires.

Rule 5: every offset is an integer millisecond, which is why the transcript
word keys are the one-letter ``i/t/s/e/c`` form — a segment can carry thousands
of words and the key names would otherwise outweigh the data.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .corrections import chunk_word_range
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


class ChunkSpanSerializer(serializers.Serializer):
    """One row of ``GET /api/segments/{id}/chunks/``.

    The map from a word to the passage that holds it: the correction UI lets a
    reader select words in the transcript and has to name a ``chunk_id`` when
    it posts, so it needs the chunks' word ranges. ``word_start``/``word_end``
    are inclusive ``TranscriptWord.idx`` values — the same transcript-wide
    indices ``POST /api/corrections/`` takes — and are null only for a chunk
    whose span holds no aligned words.
    """

    chunk_id = serializers.IntegerField()
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()
    word_start = serializers.IntegerField(allow_null=True)
    word_end = serializers.IntegerField(allow_null=True)


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
    a one-word fix has ``word_start == word_end``.

    The range is checked against the named chunk's own words here, not only at
    approval time. :func:`corpus.corrections.approve` refuses a range that
    reaches outside its chunk, so accepting one at submission would queue a
    suggestion that no reviewer can ever act on: a dead letter that costs the
    submitter their rate limit and the reviewer a decision they cannot make.
    """

    chunk_id = serializers.PrimaryKeyRelatedField(
        source='chunk', queryset=Chunk.objects.all()
    )

    class Meta:
        model = Correction
        fields = ('chunk_id', 'word_start', 'word_end', 'suggested_text')

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        word_start, word_end = attrs['word_start'], attrs['word_end']
        if word_end < word_start:
            raise serializers.ValidationError(
                {'word_end': 'must not come before word_start'}
            )
        chunk = attrs['chunk']
        chunk_range = chunk_word_range(chunk)
        if chunk_range is None:
            raise serializers.ValidationError(
                {'chunk_id': f'chunk {chunk.pk} covers no transcript words'}
            )
        low, high = chunk_range
        if word_start < low or word_end > high:
            # Named after the end that is out of bounds, so the UI can point at
            # the right handle. ASCII only: the message is echoed straight back
            # into a JSON body that is otherwise Arabic.
            field = 'word_start' if word_start < low else 'word_end'
            raise serializers.ValidationError(
                {
                    field: (
                        f'words {word_start}-{word_end} fall outside chunk '
                        f'{chunk.pk}, which covers words {low}-{high}'
                    )
                }
            )
        return attrs


class CorrectionCreatedSerializer(serializers.ModelSerializer):
    """The 201 body: a receipt, nothing the submitter did not already send."""

    class Meta:
        model = Correction
        fields = ('id', 'status')
