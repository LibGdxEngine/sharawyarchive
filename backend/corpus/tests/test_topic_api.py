"""GET /api/topics/ and /api/topics/{slug}/ per API_CONTRACT.md."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from api.cache import IMMUTABLE
from api.tests.factories import Archive, make_topic

from .test_related_api import RESULT_KEYS

pytestmark = pytest.mark.django_db

TOPIC_KEYS = {'slug', 'name_ar', 'description_ar', 'chunk_count'}


def test_topic_list_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    make_topic(archive.chunks)

    response = api.get('/api/topics/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
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
    assert response.headers['Cache-Control'] == IMMUTABLE
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
