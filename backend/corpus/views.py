"""Corpus endpoints: segments, transcripts, related passages, topics and the
correction inbox."""

from __future__ import annotations

from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from pgvector.django import CosineDistance
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from api.cache import ImmutableCacheMixin

from .corrections import word_range_in_span
from .models import Chunk, ChunkTopic, Segment, Topic
from .serializers import (
    ChunkResultSerializer,
    ChunkSpanSerializer,
    CorrectionCreatedSerializer,
    CorrectionCreateSerializer,
    SegmentDetailSerializer,
    TopicDetailSerializer,
    TopicListSerializer,
    TranscriptSerializer,
)

RELATED_LIMIT = 10
"""How many neighbouring passages ``/related/`` returns."""

CONFIDENCE_DIGITS = 3
"""ASR confidence past the third decimal is noise, and it is per-word payload."""


class SegmentDetailView(ImmutableCacheMixin, RetrieveAPIView):
    """``GET /api/segments/{id}/`` — metadata plus presigned media URLs."""

    serializer_class = SegmentDetailSerializer

    def get_queryset(self) -> QuerySet[Segment]:
        return Segment.objects.select_related('audio', 'source', 'transcript')


class SegmentTranscriptView(ImmutableCacheMixin, APIView):
    """``GET /api/segments/{id}/transcript/`` — the whole word array.

    Content-addressed by ``Transcript.version``: an approved correction bumps
    the version, so the client asks for a new ``?v=`` rather than revalidating.
    """

    @extend_schema(operation_id='segment_transcript_retrieve', responses=TranscriptSerializer)
    def get(self, request: Request, pk: int) -> Response:
        segment = get_object_or_404(Segment.objects.select_related('transcript'), pk=pk)
        transcript = getattr(segment, 'transcript', None)
        if transcript is None:
            raise NotFound(f'segment {pk} has no transcript yet')
        rows = transcript.words.order_by('idx').values_list(
            'idx', 'text', 'start_ms', 'end_ms', 'confidence'
        )
        return Response(
            {
                'version': transcript.version,
                'engine': transcript.engine,
                'is_human_reviewed': transcript.is_human_reviewed,
                'words': [
                    {
                        'i': idx,
                        't': text,
                        's': start_ms,
                        'e': end_ms,
                        'c': None if confidence is None else round(confidence, CONFIDENCE_DIGITS),
                    }
                    for idx, text, start_ms, end_ms, confidence in rows
                ],
            }
        )


class SegmentChunksView(ImmutableCacheMixin, APIView):
    """``GET /api/segments/{id}/chunks/`` — passage spans and their word ranges.

    The client already has the word array from ``/transcript/``; this says
    which passage each word belongs to, which is what a correction has to name
    when it is submitted. Content-addressed like the transcript itself: the
    spans only move when an approved correction bumps ``Transcript.version``.

    Assembled from two ``values_list`` queries rather than through the
    serializer, for the reason ``SegmentTranscriptView`` gives — the payload is
    mechanical and a transcript can carry thousands of words.
    """

    @extend_schema(
        operation_id='segment_chunks_list', responses=ChunkSpanSerializer(many=True)
    )
    def get(self, request: Request, pk: int) -> Response:
        segment = get_object_or_404(Segment.objects.select_related('transcript'), pk=pk)
        transcript = getattr(segment, 'transcript', None)
        if transcript is None:
            raise NotFound(f'segment {pk} has no transcript yet')
        words = list(transcript.words.values_list('idx', 'start_ms'))
        rows = []
        for chunk_id, start_ms, end_ms in transcript.chunks.order_by('idx').values_list(
            'id', 'start_ms', 'end_ms'
        ):
            word_range = word_range_in_span(words, start_ms, end_ms)
            rows.append(
                {
                    'chunk_id': chunk_id,
                    'start_ms': start_ms,
                    'end_ms': end_ms,
                    'word_start': None if word_range is None else word_range[0],
                    'word_end': None if word_range is None else word_range[1],
                }
            )
        return Response(rows)


class SegmentRelatedView(ImmutableCacheMixin, APIView):
    """``GET /api/segments/{id}/related/`` — nearest passages elsewhere.

    The segment is reduced to the centroid of its chunk embeddings, and the
    corpus is searched by cosine distance to that centroid with the segment's
    own chunks excluded. Cosine distance ignores magnitude, so the mean needs
    no renormalization. A segment that has not been embedded yet returns ``[]``
    rather than an error — embedding lags ingestion.
    """

    @extend_schema(
        operation_id='segment_related_list', responses=ChunkResultSerializer(many=True)
    )
    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Segment.objects.only('pk'), pk=pk)
        vectors = list(
            Chunk.objects.filter(
                transcript__segment_id=pk, embedding__isnull=False
            ).values_list('embedding', flat=True)
        )
        if not vectors:
            return Response([])

        import numpy as np

        centroid = np.mean(np.asarray(vectors, dtype=float), axis=0).tolist()
        neighbours = (
            Chunk.objects.filter(embedding__isnull=False)
            .exclude(transcript__segment_id=pk)
            .annotate(distance=CosineDistance('embedding', centroid))
            .order_by('distance')
            .select_related('transcript__segment')[:RELATED_LIMIT]
        )
        return Response(ChunkResultSerializer(neighbours, many=True).data)


class TopicListView(ImmutableCacheMixin, ListAPIView):
    """``GET /api/topics/`` — the published topics only.

    An unpublished topic is an unreviewed cluster label, so it is invisible
    rather than merely unlinked: nothing about it leaves the backend.
    """

    serializer_class = TopicListSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[Topic]:
        # Explicit order_by: Meta.ordering is dropped from a GROUP BY query.
        return (
            Topic.objects.filter(is_published=True)
            .annotate(chunk_count=Count('chunk_links'))
            .order_by('slug')
        )


class TopicDetailView(ImmutableCacheMixin, APIView):
    """``GET /api/topics/{slug}/`` — the topic and its passages, best first."""

    @extend_schema(operation_id='topic_retrieve', responses=TopicDetailSerializer)
    def get(self, request: Request, slug: str) -> Response:
        topic = get_object_or_404(Topic, slug=slug, is_published=True)
        links = (
            ChunkTopic.objects.filter(topic=topic)
            .select_related('chunk__transcript__segment')
            .order_by('-score')
        )
        chunks = [link.chunk for link in links]
        topic.chunk_count = len(chunks)  # type: ignore[attr-defined]
        topic.chunks = chunks  # type: ignore[attr-defined]
        return Response(TopicDetailSerializer(topic).data)


class CorrectionCreateView(APIView):
    """``POST /api/corrections/`` — anonymous, IP-throttled suggestion inbox.

    Nothing here touches the transcript: a correction is reviewed and applied
    by a human later (Phase 6). The response is a bare receipt so a submitter
    cannot use the endpoint to enumerate the queue.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'corrections'

    @extend_schema(
        operation_id='correction_create',
        request=CorrectionCreateSerializer,
        responses={201: CorrectionCreatedSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = CorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = serializer.save(submitted_ip=request.META.get('REMOTE_ADDR'))
        return Response(
            CorrectionCreatedSerializer(correction).data, status=status.HTTP_201_CREATED
        )
