"""Quran read endpoints. Reference data, so every 200 is cached immutably."""

from __future__ import annotations

import math

from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.cache import ImmutableCacheMixin
from corpus.models import Segment

from .models import Ayah, Surah
from .serializers import (
    AyahDetailSerializer,
    SurahDetailSerializer,
    SurahListSerializer,
)

AYAH_PAGE_SIZE = 20
"""Fixed by API_CONTRACT.md; not client-tunable."""


class SurahListView(ImmutableCacheMixin, ListAPIView):
    """``GET /api/surahs/`` — all 114, unpaginated, with segment counts."""

    serializer_class = SurahListSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[Surah]:
        # order_by is explicit because Meta.ordering is dropped from a GROUP BY
        # query, which is what annotate() turns this into.
        return Surah.objects.annotate(segment_count=Count('segments')).order_by('number')


def _page_number(request: Request) -> int:
    raw = request.query_params.get('page')
    if raw is None or raw == '':
        return 1
    try:
        page = int(raw)
    except ValueError as error:
        raise ValidationError({'page': 'must be an integer'}) from error
    if page < 1:
        raise ValidationError({'page': 'must be 1 or greater'})
    return page


def _covering_counts(surah_number: int, ayah_numbers: list[int]) -> dict[int, int]:
    """How many segments cover each ayah in ``ayah_numbers``.

    One query for the whole page: fetch the segment ranges that overlap it and
    fan them out in Python, rather than a correlated subquery per verse.
    """
    if not ayah_numbers:
        return {}
    ranges = Segment.objects.filter(
        surah_id=surah_number,
        ayah_start__lte=ayah_numbers[-1],
        ayah_end__gte=ayah_numbers[0],
    ).values_list('ayah_start', 'ayah_end')
    counts = dict.fromkeys(ayah_numbers, 0)
    for start, end in ranges:
        for number in ayah_numbers:
            if start <= number <= end:
                counts[number] += 1
    return counts


class SurahDetailView(ImmutableCacheMixin, APIView):
    """``GET /api/surahs/{n}/?page=`` — the surah plus one page of ayahs."""

    @extend_schema(
        operation_id='surah_retrieve',
        parameters=[OpenApiParameter('page', int, description='1-based, 20 ayahs per page.')],
        responses=SurahDetailSerializer,
    )
    def get(self, request: Request, number: int) -> Response:
        surah = get_object_or_404(Surah, pk=number)
        page = _page_number(request)
        count = surah.ayah_count
        if page > 1 and (page - 1) * AYAH_PAGE_SIZE >= count:
            raise NotFound(f'page {page} is past the end ({math.ceil(count / AYAH_PAGE_SIZE)})')

        start = (page - 1) * AYAH_PAGE_SIZE
        ayahs = list(surah.ayahs.all()[start : start + AYAH_PAGE_SIZE])
        counts = _covering_counts(surah.number, [ayah.number for ayah in ayahs])
        for ayah in ayahs:
            ayah.segment_count = counts[ayah.number]  # type: ignore[attr-defined]

        payload = {
            'number': surah.number,
            'name_ar': surah.name_ar,
            'name_en': surah.name_en,
            'ayah_count': surah.ayah_count,
            'revelation_place': surah.revelation_place,
            'ayahs': {
                'count': count,
                'page': page,
                'page_size': AYAH_PAGE_SIZE,
                'results': ayahs,
            },
        }
        return Response(SurahDetailSerializer(payload).data)


class AyahDetailView(ImmutableCacheMixin, APIView):
    """``GET /api/ayahs/{surah}/{ayah}/`` — the verse and the segments whose
    declared ayah range covers it. A segment with no range covers nothing."""

    @extend_schema(operation_id='ayah_retrieve', responses=AyahDetailSerializer)
    def get(self, request: Request, surah: int, ayah: int) -> Response:
        verse = get_object_or_404(Ayah, surah_id=surah, number=ayah)
        verse.segments = list(  # type: ignore[attr-defined]
            Segment.objects.filter(
                surah_id=surah, ayah_start__lte=ayah, ayah_end__gte=ayah
            )
        )
        return Response(AyahDetailSerializer(verse).data)
