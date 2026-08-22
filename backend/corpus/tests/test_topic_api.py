"""GET /api/topics/ and /api/topics/{slug}/ per API_CONTRACT.md."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from api.cache import PUBLIC_SHORT
from api.tests.factories import Archive, make_topic
from corpus.models import Chunk
from corpus.views import TOPIC_CHUNK_LIMIT

pytestmark = pytest.mark.django_db

RESULT_KEYS = {
    'chunk_id',
    'segment_id',
    'segment_title',
    'surah',
    'ayah_start',
    'ayah_end',
    'kind',
    'text',
    'start_ms',
    'end_ms',
}
"""The search-result shape (``ChunkResultSerializer``)."""

TOPIC_KEYS = {'slug', 'name_ar', 'description_ar', 'chunk_count'}

OFFSET_IDX = 100
"""Clear of the archive fixture's own chunk indices — ``(transcript, idx)`` is
unique."""


def test_topic_list_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    make_topic(archive.chunks)

    response = api.get('/api/topics/')

    assert response.status_code == 200
    # Publishing is an editorial decision that has to be able to reverse, so
    # topics are cacheable but never immutable (API_CONTRACT.md amendment 4).
    assert response.headers['Cache-Control'] == PUBLIC_SHORT
    (row,) = response.json()
    assert set(row) == TOPIC_KEYS
    assert row['slug'] == 'sabr'
    assert row['name_ar'] == 'الصبر'
    assert row['chunk_count'] == len(archive.chunks)


def test_unpublished_topics_are_invisible(api: APIClient, archive: Archive) -> None:
    make_topic(archive.chunks, slug='published')
    make_topic(archive.other_chunks, slug='draft', is_published=False)

    assert [row['slug'] for row in api.get('/api/topics/').json()] == ['published']


def test_topic_detail_carries_its_passages(api: APIClient, archive: Archive) -> None:
    make_topic(archive.chunks)

    response = api.get('/api/topics/sabr/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == PUBLIC_SHORT
    body = response.json()
    assert set(body) == TOPIC_KEYS | {'chunks'}
    assert body['chunk_count'] == len(archive.chunks)
    (first, *_) = body['chunks']
    assert set(first) == RESULT_KEYS
    assert first['chunk_id'] == archive.chunks[0].pk  # highest score first
    assert first['segment_id'] == archive.segment.pk
    assert first['text'] == archive.chunks[0].text


def test_topic_detail_orders_passages_by_score(api: APIClient, archive: Archive) -> None:
    make_topic(list(reversed(archive.chunks)))

    body = api.get('/api/topics/sabr/').json()

    assert [chunk['chunk_id'] for chunk in body['chunks']] == [
        chunk.pk for chunk in reversed(archive.chunks)
    ]


def test_an_unpublished_topic_detail_is_404(api: APIClient, archive: Archive) -> None:
    make_topic(archive.chunks, slug='draft', is_published=False)

    assert api.get('/api/topics/draft/').status_code == 404


def test_an_unknown_topic_is_404(api: APIClient, archive: Archive) -> None:
    assert api.get('/api/topics/nope/').status_code == 404


def test_a_topic_without_passages_is_still_served(api: APIClient, archive: Archive) -> None:
    make_topic([])

    body = api.get('/api/topics/sabr/').json()

    assert (body['chunk_count'], body['chunks']) == (0, [])


def test_a_large_topic_is_capped_but_still_counts_honestly(
    api: APIClient, archive: Archive
) -> None:
    """The endpoint has no pagination, so an unbounded topic would make one
    slug a request for the whole corpus. ``chunk_count`` still tells the truth
    about how big the topic is."""
    oversized = TOPIC_CHUNK_LIMIT + 5
    passages = Chunk.objects.bulk_create(
        Chunk(
            transcript=archive.transcript,
            idx=OFFSET_IDX + index,
            text=f'مقطع رقم {index}',
            text_normalized=f'مقطع رقم {index}',
            start_ms=index * 30_000,
            end_ms=(index + 1) * 30_000,
        )
        for index in range(oversized)
    )
    make_topic(passages)

    body = api.get('/api/topics/sabr/').json()

    assert len(body['chunks']) == TOPIC_CHUNK_LIMIT
    assert body['chunk_count'] == oversized
    # Best-scoring first, and it is the *top* of the list that survives the cap.
    assert [chunk['chunk_id'] for chunk in body['chunks']] == [
        chunk.pk for chunk in passages[:TOPIC_CHUNK_LIMIT]
    ]
