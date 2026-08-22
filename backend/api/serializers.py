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
