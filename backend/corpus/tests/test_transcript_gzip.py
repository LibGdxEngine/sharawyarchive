"""A full-length transcript is the API's largest payload — it must compress.

Six thousand words is a realistic khawatir episode. Uncompressed that is a few
hundred kilobytes even with the one-letter keys, so gzip is what makes the
endpoint usable on a phone.
"""

from __future__ import annotations

import gzip
import json

import pytest
from rest_framework.test import APIClient

from api.tests.factories import Archive
from corpus.models import TranscriptWord

pytestmark = pytest.mark.django_db

WORD_COUNT = 6_000
MAX_COMPRESSED_BYTES = 250_000


@pytest.fixture
def long_transcript(archive: Archive) -> Archive:
    archive.transcript.words.all().delete()
    TranscriptWord.objects.bulk_create(
        TranscriptWord(
            transcript=archive.transcript,
            idx=index,
            text='الْمُسْتَقِيمَ',
            start_ms=index * 350,
            end_ms=index * 350 + 340,
            confidence=0.9123456,
        )
        for index in range(WORD_COUNT)
    )
    return archive


def test_transcript_is_gzipped_when_the_client_asks(
    api: APIClient, long_transcript: Archive
) -> None:
    response = api.get(
        f'/api/segments/{long_transcript.segment.pk}/transcript/',
        headers={'accept-encoding': 'gzip'},
    )

    assert response.status_code == 200
    assert response.headers['Content-Encoding'] == 'gzip'
    assert len(response.content) < MAX_COMPRESSED_BYTES
    body = json.loads(gzip.decompress(response.content))
    assert len(body['words']) == WORD_COUNT
    assert body['words'][0] == {'i': 0, 't': 'الْمُسْتَقِيمَ', 's': 0, 'e': 340, 'c': 0.912}


def test_transcript_keys_stay_compact_uncompressed(
    api: APIClient, long_transcript: Archive
) -> None:
    response = api.get(f'/api/segments/{long_transcript.segment.pk}/transcript/')

    assert 'Content-Encoding' not in response.headers
    raw = response.content
    assert b'"i":0' in raw
    for verbose in (b'"idx"', b'"start_ms"', b'"end_ms"', b'"confidence"', b'"text"'):
        assert verbose not in raw
    # Compression is doing real work, not shaving a few percent.
    assert len(raw) > MAX_COMPRESSED_BYTES
