"""GET /api/segments/{id}/chunks/ — the word→passage map the correction UI needs."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from api.cache import PUBLIC_SHORT
from api.tests.factories import make_audio_asset
from corpus.models import Chunk, Segment, SegmentKind, Source

from .conftest import WORD_LENGTH_MS, WORD_STEP_MS, WORDS_PER_CHUNK, Passages

pytestmark = pytest.mark.django_db

CHUNK_KEYS = {'chunk_id', 'start_ms', 'end_ms', 'word_start', 'word_end'}


def _url(segment_id: int) -> str:
    return f'/api/segments/{segment_id}/chunks/'


def test_chunks_return_the_contract_shape(api: APIClient, passages: Passages) -> None:
    response = api.get(_url(passages.segment.pk))

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == PUBLIC_SHORT
    body = response.json()
    assert len(body) == len(passages.chunks)
    (first, *_) = body
    assert set(first) == CHUNK_KEYS
    assert first['chunk_id'] == passages.chunks[0].pk
    assert (first['start_ms'], first['end_ms']) == (0, WORD_LENGTH_MS + 9 * WORD_STEP_MS)


def test_chunks_come_in_transcript_order(api: APIClient, passages: Passages) -> None:
    body = api.get(_url(passages.segment.pk)).json()

    assert [row['chunk_id'] for row in body] == [chunk.pk for chunk in passages.chunks]
    assert [row['start_ms'] for row in body] == sorted(row['start_ms'] for row in body)


def test_word_ranges_cover_every_word_exactly_once(
    api: APIClient, passages: Passages
) -> None:
    body = api.get(_url(passages.segment.pk)).json()

    assert [(row['word_start'], row['word_end']) for row in body] == [
        (0, 9),
        (10, 19),
        (20, 29),
    ]
    covered = [index for row in body for index in range(row['word_start'], row['word_end'] + 1)]
    assert covered == list(range(len(passages.words())))


def test_a_word_range_is_inclusive_of_its_last_word(
    api: APIClient, passages: Passages
) -> None:
    """The frontend maps a selected word index to a chunk with these bounds, so
    the boundary word has to belong to exactly one of them."""
    body = api.get(_url(passages.segment.pk)).json()

    boundary = WORDS_PER_CHUNK - 1
    holders = [row for row in body if row['word_start'] <= boundary <= row['word_end']]
    assert [row['chunk_id'] for row in holders] == [passages.chunks[0].pk]


def test_a_segment_without_chunks_returns_an_empty_list(
    api: APIClient, passages: Passages
) -> None:
    Chunk.objects.filter(transcript=passages.transcript).delete()

    response = api.get(_url(passages.segment.pk))

    assert (response.status_code, response.json()) == (200, [])


def test_a_segment_without_a_transcript_is_404(api: APIClient, passages: Passages) -> None:
    bare = Segment.objects.create(
        source=Source.objects.create(title='مصدر', kind='tv'),
        kind=SegmentKind.KHAWATIR,
        audio=make_audio_asset(),
        duration_ms=1_000,
        title='بلا تفريغ',
    )

    assert api.get(_url(bare.pk)).status_code == 404


def test_an_unknown_segment_is_404(api: APIClient, passages: Passages) -> None:
    assert api.get(_url(999999)).status_code == 404
