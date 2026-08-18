"""Response shapes for the Quran endpoints (``API_CONTRACT.md``).

``segment_count`` is never a model field: on a surah it is the number of
segments attached to that surah, on an ayah it is the number of segments whose
``ayah_start..ayah_end`` range covers that verse. Both are computed by the view
and attached to the instance before serialization.
"""

from __future__ import annotations

from rest_framework import serializers

from corpus.models import Segment, SegmentKind

from .models import Ayah, RevelationPlace, Surah


class SurahListSerializer(serializers.ModelSerializer):
    """One row of ``GET /api/surahs/``."""

    segment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Surah
        fields = (
            'number',
            'name_ar',
            'name_ar_plain',
            'name_en',
            'ayah_count',
            'revelation_place',
            'segment_count',
        )


class AyahSegmentRefSerializer(serializers.Serializer):
    """A covering segment as listed on a surah page — just enough to link to it.

    Serialized from the ``.values()`` dicts the view fans out, not from model
    instances, so the whole page costs one segment query.
    """

    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=SegmentKind.choices, read_only=True)
    title = serializers.CharField(read_only=True)


class SurahAyahSerializer(serializers.ModelSerializer):
    """One ayah inside a paginated surah page.

    ``segments`` is capped at ``views.MAX_AYAH_SEGMENTS``; ``segment_count`` is
    the uncapped total.
    """

    segment_count = serializers.IntegerField(read_only=True)
    segments = AyahSegmentRefSerializer(many=True, read_only=True)

    class Meta:
        model = Ayah
        fields = (
            'number',
            'text_uthmani',
            'juz',
            'page',
            'sajda',
            'segment_count',
            'segments',
        )


class AyahPageSerializer(serializers.Serializer):
    """The ``ayahs`` envelope: a fixed-size page, not a DRF paginator shape."""

    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    results = SurahAyahSerializer(many=True)


class SurahDetailSerializer(serializers.Serializer):
    """``GET /api/surahs/{n}/`` — surah head plus one page of its ayahs."""

    number = serializers.IntegerField()
    name_ar = serializers.CharField()
    name_en = serializers.CharField()
    ayah_count = serializers.IntegerField()
    revelation_place = serializers.ChoiceField(choices=RevelationPlace.choices)
    ayahs = AyahPageSerializer()


class CoveringSegmentSerializer(serializers.ModelSerializer):
    """A segment listed under an ayah it covers."""

    class Meta:
        model = Segment
        fields = ('id', 'kind', 'title', 'ayah_start', 'ayah_end', 'duration_ms')


class AyahDetailSerializer(serializers.ModelSerializer):
    """``GET /api/ayahs/{surah}/{ayah}/`` — the verse and what covers it."""

    surah = serializers.IntegerField(source='surah_id')
    segments = CoveringSegmentSerializer(many=True, read_only=True)

    class Meta:
        model = Ayah
        fields = (
            'surah',
            'number',
            'text_uthmani',
            'text_imlaei',
            'juz',
            'page',
            'segments',
        )
