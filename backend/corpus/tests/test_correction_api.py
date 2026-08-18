"""POST /api/corrections/ per API_CONTRACT.md."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from api.tests.factories import Archive
from corpus.models import Correction

pytestmark = pytest.mark.django_db

URL = '/api/corrections/'


def _body(archive: Archive, **overrides: Any) -> dict[str, Any]:
    return {
        'chunk_id': archive.chunks[0].pk,
        'word_start': 4,
        'word_end': 6,
        'suggested_text': 'الصبر عند الصدمة الأولى',
        **overrides,
    }


def test_a_correction_is_accepted_and_queued(api: APIClient, archive: Archive) -> None:
    response = api.post(URL, _body(archive), format='json')

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {'id', 'status'}
    assert body['status'] == 'pending'

    correction = Correction.objects.get(pk=body['id'])
    assert correction.chunk_id == archive.chunks[0].pk
    assert (correction.word_start, correction.word_end) == (4, 6)
    assert correction.submitted_ip == '127.0.0.1'


def test_a_single_word_correction_is_valid(api: APIClient, archive: Archive) -> None:
    response = api.post(URL, _body(archive, word_start=0, word_end=0), format='json')

    assert response.status_code == 201


def test_a_correction_never_touches_the_transcript(api: APIClient, archive: Archive) -> None:
    """Rule 1 territory: review is a human step, not a side effect of POSTing."""
    before = list(archive.transcript.words.values_list('text', flat=True))

    api.post(URL, _body(archive), format='json')

    archive.transcript.refresh_from_db()
    assert list(archive.transcript.words.values_list('text', flat=True)) == before
    assert archive.transcript.version == 2


@pytest.mark.parametrize(
    ('overrides', 'field'),
    [
        ({'word_end': 3}, 'word_end'),  # before word_start
        ({'word_start': -1}, 'word_start'),
        ({'suggested_text': ''}, 'suggested_text'),
        ({'suggested_text': '   '}, 'suggested_text'),
        ({'suggested_text': 'ا' * 1001}, 'suggested_text'),
        ({'chunk_id': 999999}, 'chunk_id'),
    ],
)
def test_invalid_corrections_are_rejected(
    api: APIClient, archive: Archive, overrides: dict[str, Any], field: str
) -> None:
    response = api.post(URL, _body(archive, **overrides), format='json')

    assert response.status_code == 400
    assert field in response.json()
    assert not Correction.objects.exists()


def test_the_longest_allowed_suggestion_is_accepted(api: APIClient, archive: Archive) -> None:
    response = api.post(URL, _body(archive, suggested_text='ا' * 1000), format='json')

    assert response.status_code == 201


@pytest.mark.parametrize('missing', ['chunk_id', 'word_start', 'word_end', 'suggested_text'])
def test_every_field_is_required(api: APIClient, archive: Archive, missing: str) -> None:
    body = _body(archive)
    del body[missing]

    response = api.post(URL, body, format='json')

    assert response.status_code == 400
    assert missing in response.json()


def test_corrections_are_write_only(api: APIClient, archive: Archive) -> None:
    """The queue is not readable — a submitter cannot enumerate it."""
    assert api.get(URL).status_code == 405
