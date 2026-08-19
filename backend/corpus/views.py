"""Corpus endpoints: segments, transcripts, related passages, topics and the
correction inbox."""

from __future__ import annotations

from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from api.cache import PRIVATE_SHORT, PUBLIC_SHORT, CacheControlMixin, ImmutableCacheMixin
from api.ip import client_ip

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

TOPIC_CHUNK_LIMIT = 100
"""Cap on the passages ``/api/topics/{slug}/`` serves in one response.

A clustered topic can hold thousands of chunks and the endpoint has no
pagination, so without a cap one slug is an unauthenticated request for the
whole corpus. ``chunk_count`` still reports the real total."""

CONFIDENCE_DIGITS = 3
"""ASR confidence past the third decimal is noise, and it is per-word payload."""


class SegmentDetailView(CacheControlMixin, RetrieveAPIView):
    """``GET /api/segments/{id}/`` — metadata plus presigned media URLs.

    Not immutable, despite the rest of the segment being append-only: the body
    embeds presigned audio and waveform URLs that expire in six hours, so it is
    ``private`` (a shared cache must not hand one reader's signed URL to
    another) and short-lived (API_CONTRACT.md amendment 4).
    """

    cache_control = PRIVATE_SHORT
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


class SegmentChunksView(CacheControlMixin, APIView):
    """``GET /api/segments/{id}/chunks/`` — passage spans and their word ranges.

    The client already has the word array from ``/transcript/``; this says
    which passage each word belongs to, which is what a correction has to name
    when it is submitted. Short-lived cache, NOT immutable: the URL carries no
    transcript version, and an approved correction can renumber word indices —
    a year-old chunk map would target the wrong words.

    Assembled from two ``values_list`` queries rather than through the
    serializer, for the reason ``SegmentTranscriptView`` gives — the payload is
    mechanical and a transcript can carry thousands of words.
    """

    cache_control = PUBLIC_SHORT

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


class SegmentRelatedView(CacheControlMixin, APIView):
    """``GET /api/segments/{id}/related/`` — nearest passages elsewhere.

    Short-lived public cache, never immutable: every newly embedded segment
    changes this corpus-wide result.

    The segment is reduced to the centroid of its chunk embeddings, and the
    corpus is searched by cosine distance to that centroid with the segment's
    own chunks excluded. Cosine distance ignores magnitude, so the mean needs
    no renormalization. A segment that has not been embedded yet returns ``[]``
    rather than an error — embedding lags ingestion.
    """

    cache_control = PUBLIC_SHORT

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

        from search.services import nearest_chunks

        centroid = np.mean(np.asarray(vectors, dtype=float), axis=0).tolist()
        # Through search.services, not a queryset of its own: the "not this
        # segment" filter is applied after the approximate index scan, so this
        # is exactly the query that silently underfetches without the scan
        # depth that helper sets.
        neighbours = nearest_chunks(
            Chunk.objects.filter(embedding__isnull=False)
            .exclude(transcript__segment_id=pk)
            .select_related('transcript__segment'),
            centroid,
            limit=RELATED_LIMIT,
        )
        return Response(ChunkResultSerializer(neighbours, many=True).data)


class TopicListView(CacheControlMixin, ListAPIView):
    """``GET /api/topics/`` — the published topics only.

    An unpublished topic is an unreviewed cluster label, so it is invisible
    rather than merely unlinked: nothing about it leaves the backend. Which is
    also why this is not immutable: publishing is an editorial decision, and an
    immutable response would mean unpublishing never reaches anyone who already
    looked (API_CONTRACT.md amendment 4).
    """

    cache_control = PUBLIC_SHORT
    serializer_class = TopicListSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[Topic]:
        # Explicit order_by: Meta.ordering is dropped from a GROUP BY query.
        return (
            Topic.objects.filter(is_published=True)
            .annotate(chunk_count=Count('chunk_links'))
            .order_by('slug')
        )


class TopicDetailView(CacheControlMixin, APIView):
    """``GET /api/topics/{slug}/`` — the topic and its best passages.

    Cached like the list for the same reason: the publish gate has to be able
    to close again.
    """

    cache_control = PUBLIC_SHORT

    @extend_schema(operation_id='topic_retrieve', responses=TopicDetailSerializer)
    def get(self, request: Request, slug: str) -> Response:
        topic = get_object_or_404(Topic, slug=slug, is_published=True)
        links = ChunkTopic.objects.filter(topic=topic)
        # Count separately from the slice: chunk_count is the topic's real
        # size, `chunks` is the first TOPIC_CHUNK_LIMIT of them by score.
        topic.chunk_count = links.count()  # type: ignore[attr-defined]
        topic.chunks = [  # type: ignore[attr-defined]
            link.chunk
            for link in links.select_related('chunk__transcript__segment').order_by('-score')[
                :TOPIC_CHUNK_LIMIT
            ]
        ]
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
        # REMOTE_ADDR is Caddy in a deployed setup; api.ip resolves the hop.
        correction = serializer.save(submitted_ip=client_ip(request))
        return Response(
            CorrectionCreatedSerializer(correction).data, status=status.HTTP_201_CREATED
        )
