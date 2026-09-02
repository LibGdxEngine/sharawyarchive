"""Schema types that belong to no single domain app.

The search endpoint answers with plain dictionaries assembled in
:mod:`search.services`; these serializers exist so drf-spectacular — and
therefore the generated frontend types — describe that answer exactly. The
result rows reuse :class:`corpus.serializers.ChunkResultSerializer`, which is
the one place the search-result shape is declared.
"""

from __future__ import annotations

from rest_framework import serializers

from corpus.serializers import ChunkResultSerializer


class AyahMatchSerializer(serializers.Serializer):
    """An exact verse resolved from the query itself, shown above the hits."""

    surah = serializers.IntegerField()
    number = serializers.IntegerField()
    text_uthmani = serializers.CharField()
    surah_name_ar = serializers.CharField()


class VerseMatchSerializer(serializers.Serializer):
    """A mushaf verse found by full-text search over the canonical text."""

    surah = serializers.IntegerField()
    number = serializers.IntegerField()
    text_uthmani = serializers.CharField()
    surah_name_ar = serializers.CharField()
    juz = serializers.IntegerField()
    page = serializers.IntegerField()


class SearchResponseSerializer(serializers.Serializer):
    """``GET /api/search/`` — mirrors :class:`search.services.SearchResponse`."""

    query = serializers.CharField()
    ayah_matches = AyahMatchSerializer(many=True)
    verse_matches = VerseMatchSerializer(many=True)
    results = ChunkResultSerializer(many=True)
    page = serializers.IntegerField()
    total = serializers.IntegerField()


class ErrorSerializer(serializers.Serializer):
    """The shape every 4xx in this API uses."""

    detail = serializers.CharField()


# --- Smart search (POST /api/search/smart/) -----------------------------------


class SmartFiltersSerializer(serializers.Serializer):
    surah = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=114)
    source_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class SmartRequestSerializer(serializers.Serializer):
    """The body of ``POST /api/search/smart/``."""

    question = serializers.CharField(max_length=500, trim_whitespace=True)
    filters = SmartFiltersSerializer(required=False)
    debug = serializers.BooleanField(required=False, default=False)


class SmartCitationSerializer(serializers.Serializer):
    n = serializers.IntegerField()
    passage_id = serializers.IntegerField()
    chunk_id = serializers.IntegerField(allow_null=True)
    segment_id = serializers.IntegerField()
    segment_title = serializers.CharField()
    surah = serializers.IntegerField(allow_null=True)
    ayah_start = serializers.IntegerField(allow_null=True)
    ayah_end = serializers.IntegerField(allow_null=True)
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()
    quote_display = serializers.CharField()
    listen_url = serializers.CharField()


class SmartPassageSerializer(serializers.Serializer):
    passage_id = serializers.IntegerField()
    chunk_id = serializers.IntegerField(allow_null=True)
    segment_id = serializers.IntegerField()
    segment_title = serializers.CharField()
    surah = serializers.IntegerField(allow_null=True)
    ayah_start = serializers.IntegerField(allow_null=True)
    ayah_end = serializers.IntegerField(allow_null=True)
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()
    excerpt_display = serializers.CharField()
    score = serializers.FloatField()


class SmartAyahSerializer(serializers.Serializer):
    """Canonical text from the quran app, never from a model."""

    surah = serializers.IntegerField()
    ayah = serializers.IntegerField()
    surah_name_ar = serializers.CharField()
    text_uthmani = serializers.CharField()


class SmartResponseSerializer(serializers.Serializer):
    """Mirrors :class:`search.smart.schemas.SmartResponse`."""

    query_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["smart"])
    status = serializers.ChoiceField(choices=["answered", "partial", "not_found", "degraded"])
    answer_md = serializers.CharField(allow_null=True)
    citations = SmartCitationSerializer(many=True)
    passages = SmartPassageSerializer(many=True)
    ayah_refs = SmartAyahSerializer(many=True)
    followups = serializers.ListField(child=serializers.CharField())
    cache_hit = serializers.BooleanField()
    debug = serializers.DictField(required=False, allow_null=True)


class SmartFeedbackSerializer(serializers.Serializer):
    vote = serializers.ChoiceField(choices=["up", "down"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")


class SmartFeedbackResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["recorded"])
