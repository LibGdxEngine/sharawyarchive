"""GET /api/segments/{id}/ and .../transcript/ per API_CONTRACT.md."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from api.cache import IMMUTABLE, PRIVATE_SHORT
from api.tests.factories import WORD_TEXTS, Archive

pytestmark = pytest.mark.django_db

SEGMENT_KEYS = {
    'id',
    'kind',
    'title',
    'surah',
    'ayah_start',
    'ayah_end',
    'duration_ms',
    'ordinal',
    'audio_url',
    'waveform_url',
    'source',
    'transcript_version',
    'is_human_reviewed',
}
TRANSCRIPT_KEYS = {'version', 'engine', 'is_human_reviewed', 'words'}
WORD_KEYS = {'i', 't', 's', 'e', 'c'}


def _keys(payload: Any) -> set[str]:
    """Every key name anywhere in a JSON payload."""
    if isinstance(payload, dict):
        return set(payload) | {key for value in payload.values() for key in _keys(value)}
    if isinstance(payload, list):
        return {key for item in payload for key in _keys(item)}
    return set()


def _values(payload: Any) -> set[str]:
    """Every string *value* anywhere in a JSON payload."""
    if isinstance(payload, dict):
        return {value for item in payload.values() for value in _values(item)}
    if isinstance(payload, list):
        return {value for item in payload for value in _values(item)}
    return {payload} if isinstance(payload, str) else set()


# --- GET /api/segments/{id}/ -------------------------------------------------


def test_segment_detail_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    response = api.get(f'/api/segments/{archive.segment.pk}/')

    assert response.status_code == 200
    # Not immutable: the body carries six-hour presigned URLs, so it is
    # private and short-lived (API_CONTRACT.md amendment 4).
    assert response.headers['Cache-Control'] == PRIVATE_SHORT
    body = response.json()
    assert set(body) == SEGMENT_KEYS
    assert body['id'] == archive.segment.pk
    assert body['kind'] == 'khawatir'
    assert body['title'] == 'خواطر البقرة ١-٢'
    assert (body['surah'], body['ayah_start'], body['ayah_end']) == (2, 1, 2)
    assert (body['duration_ms'], body['ordinal']) == (600_000, 3)
    assert body['source'] == {'title': 'التلفزيون المصري', 'kind': 'tv'}
    assert body['transcript_version'] == 2
    assert body['is_human_reviewed'] is False


def test_segment_detail_serves_presigned_media_urls(api: APIClient, archive: Archive) -> None:
    body = api.get(f'/api/segments/{archive.segment.pk}/').json()

    for url in (body['audio_url'], body['waveform_url']):
        assert url.startswith('http')
        assert 'X-Amz-Signature=' in url
        assert 'X-Amz-Expires=21600' in url  # six hours, per the contract
    assert body['audio_url'] != body['waveform_url']


def test_segment_detail_never_leaks_storage_internals(api: APIClient, archive: Archive) -> None:
    """CLAUDE.md rule 4: no raw bucket paths, no content hashes as data.

    What the contract forbids is a *field* a client can read a key or a hash
    out of — something to store, to derive another key from, or to rebuild a
    bucket path with. A presigned URL is not that: it necessarily contains the
    path of the one object it signs, which is what makes it a signature, and it
    expires. So the assertion is that no key or hash appears as a field name or
    as a value, and the URL is checked for what it is instead.
    """
    body = api.get(f'/api/segments/{archive.segment.pk}/').json()

    assert _keys(body).isdisjoint({'sha256', 'storage_key', 'audio', 'audio_key'})
    assert _values(body).isdisjoint({archive.audio.storage_key, archive.audio.sha256})
    # The factory's storage_key is the key the API really serves, so the
    # assertion above had a genuine candidate to find.
    assert archive.audio.storage_key == f'audio/{archive.audio.sha256}.opus'
    assert archive.audio.storage_key in body['audio_url']  # inside the signature
    assert 'X-Amz-Signature=' in body['audio_url']
    for field in ('duration_ms', 'ordinal', 'id'):
        assert field in body  # sanity: we are inspecting the real payload


def test_segment_without_a_transcript_reports_no_version(
    api: APIClient, archive: Archive
) -> None:
    archive.transcript.delete()

    body = api.get(f'/api/segments/{archive.segment.pk}/').json()

    assert body['transcript_version'] is None
    assert body['is_human_reviewed'] is False


def test_reviewed_transcript_surfaces_on_the_segment(api: APIClient, archive: Archive) -> None:
    archive.transcript.is_human_reviewed = True
    archive.transcript.save(update_fields=['is_human_reviewed'])

    assert api.get(f'/api/segments/{archive.segment.pk}/').json()['is_human_reviewed'] is True


def test_unknown_segment_is_404(api: APIClient, archive: Archive) -> None:
    response = api.get('/api/segments/999999/')
    assert response.status_code == 404
    assert 'Cache-Control' not in response.headers


# --- GET /api/segments/{id}/transcript/ --------------------------------------


def test_transcript_returns_compact_words(api: APIClient, archive: Archive) -> None:
    response = api.get(f'/api/segments/{archive.segment.pk}/transcript/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    body = response.json()
    assert set(body) == TRANSCRIPT_KEYS
    assert (body['version'], body['engine']) == (2, 'whisper-large-v3')
    assert body['is_human_reviewed'] is False
    assert len(body['words']) == len(WORD_TEXTS)

    (first, second, *_) = body['words']
    assert set(first) == WORD_KEYS
    assert first == {'i': 0, 't': 'الحمد', 's': 0, 'e': 400, 'c': None}
    assert second == {'i': 1, 't': 'لله', 's': 400, 'e': 800, 'c': 0.988}


def test_transcript_offsets_are_integers_in_order(api: APIClient, archive: Archive) -> None:
    words = api.get(f'/api/segments/{archive.segment.pk}/transcript/').json()['words']

    assert [word['i'] for word in words] == list(range(len(WORD_TEXTS)))
    for word in words:
        assert isinstance(word['s'], int) and isinstance(word['e'], int)
        assert word['s'] < word['e']


def test_transcript_confidence_is_rounded_or_null(api: APIClient, archive: Archive) -> None:
    words = api.get(f'/api/segments/{archive.segment.pk}/transcript/').json()['words']

    confidences = {word['c'] for word in words}
    assert confidences == {None, 0.988}  # 0.9876543 rounded to three decimals


def test_segment_without_a_transcript_is_404(api: APIClient, archive: Archive) -> None:
    archive.transcript.delete()

    assert api.get(f'/api/segments/{archive.segment.pk}/transcript/').status_code == 404


def test_transcript_of_an_unknown_segment_is_404(api: APIClient, archive: Archive) -> None:
    assert api.get('/api/segments/999999/transcript/').status_code == 404
