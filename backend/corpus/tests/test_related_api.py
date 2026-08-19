"""GET /api/segments/{id}/related/ — embedding nearest neighbours."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from api.cache import PUBLIC_SHORT
from api.tests.factories import Archive, embed, make_audio_asset, make_segment, make_transcript
from corpus.models import Chunk
from corpus.views import RELATED_LIMIT

from .test_segment_api import _keys

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


def test_related_returns_the_search_result_shape(
    api: APIClient, embedded_archive: Archive
) -> None:
    response = api.get(f'/api/segments/{embedded_archive.segment.pk}/related/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == PUBLIC_SHORT
    body = response.json()
    assert len(body) == len(embedded_archive.other_chunks)
    (first, *_) = body
    assert set(first) == RESULT_KEYS
    assert first['segment_id'] == embedded_archive.other.pk
    assert first['segment_title'] == 'خواطر البقرة ١'
    assert (first['surah'], first['ayah_start'], first['ayah_end']) == (2, 1, 1)
    assert first['kind'] == 'khawatir'
    assert isinstance(first['start_ms'], int)


def test_related_excludes_the_segment_itself(api: APIClient, embedded_archive: Archive) -> None:
    body = api.get(f'/api/segments/{embedded_archive.segment.pk}/related/').json()

    own = {chunk.pk for chunk in embedded_archive.chunks}
    assert own.isdisjoint({result['chunk_id'] for result in body})


def test_related_never_leaks_storage_internals(
    api: APIClient, embedded_archive: Archive
) -> None:
    body = api.get(f'/api/segments/{embedded_archive.segment.pk}/related/').json()

    assert _keys(body).isdisjoint({'sha256', 'storage_key', 'embedding'})


def test_related_is_capped(api: APIClient, embedded_archive: Archive) -> None:
    neighbour = make_segment(
        embedded_archive.source,
        make_audio_asset(),
        surah=embedded_archive.surah,
        ayah_start=3,
        ayah_end=3,
        title='خواطر البقرة ٣',
    )
    transcript, _ = make_transcript(neighbour)
    extra = Chunk.objects.bulk_create(
        Chunk(
            transcript=transcript,
            idx=index,
            text=f'مقطع رقم {index}',
            text_normalized=f'مقطع رقم {index}',
            start_ms=index * 30_000,
            end_ms=(index + 1) * 30_000,
        )
        for index in range(12)
    )
    embed(extra)

    body = api.get(f'/api/segments/{embedded_archive.segment.pk}/related/').json()

    assert len(body) == RELATED_LIMIT


def test_related_is_empty_without_embeddings(api: APIClient, archive: Archive) -> None:
    """Embedding lags ingestion; an un-embedded segment is not an error."""
    response = api.get(f'/api/segments/{archive.segment.pk}/related/')

    assert response.status_code == 200
    assert response.json() == []


def test_related_of_an_unknown_segment_is_404(api: APIClient, archive: Archive) -> None:
    assert api.get('/api/segments/999999/related/').status_code == 404
