"""POST /api/clips/ and GET /api/clips/{id}/ per API_CONTRACT.md."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from api.tests.factories import Archive
from clips.models import Clip, ClipStatus

pytestmark = pytest.mark.django_db

URL = '/api/clips/'


def _body(archive: Archive, **overrides: Any) -> dict[str, Any]:
    return {
        'segment_id': archive.segment.pk,
        'start_ms': 125_000,
        'end_ms': 155_000,
        'preset': 'night',
        **overrides,
    }


# --- POST --------------------------------------------------------------------


def test_a_clip_request_is_queued(api: APIClient, archive: Archive) -> None:
    response = api.post(URL, _body(archive), format='json')

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {'id', 'status'}
    assert body['status'] == 'queued'

    clip = Clip.objects.get(pk=body['id'])
    assert (clip.start_ms, clip.end_ms, clip.preset) == (125_000, 155_000, 'night')
    assert clip.storage_key == ''  # rendering is somebody else's job


@pytest.mark.parametrize('span', [15_000, 60_000])
def test_the_span_bounds_are_inclusive(api: APIClient, archive: Archive, span: int) -> None:
    response = api.post(URL, _body(archive, end_ms=125_000 + span), format='json')

    assert response.status_code == 202


@pytest.mark.parametrize(
    'overrides',
    [
        {'end_ms': 125_000 + 14_999},  # too short
        {'end_ms': 125_000 + 60_001},  # too long
        {'start_ms': 155_000, 'end_ms': 125_000},  # inverted
        {'start_ms': 580_000, 'end_ms': 610_000},  # past the end of the segment
        {'preset': 'neon'},
        {'segment_id': 999999},
    ],
)
def test_invalid_clip_requests_are_rejected(
    api: APIClient, archive: Archive, overrides: dict[str, Any]
) -> None:
    response = api.post(URL, _body(archive, **overrides), format='json')

    assert response.status_code == 400
    assert not Clip.objects.exists()


def test_the_same_request_twice_returns_the_first_job(
    api: APIClient, archive: Archive
) -> None:
    """The job table is the cache: nobody pays for the same render twice."""
    first = api.post(URL, _body(archive), format='json')

    second = api.post(URL, _body(archive), format='json')

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json() == first.json()
    assert Clip.objects.count() == 1


def test_a_repeat_request_reports_the_current_status(
    api: APIClient, archive: Archive
) -> None:
    created = api.post(URL, _body(archive), format='json').json()
    Clip.objects.filter(pk=created['id']).update(status=ClipStatus.RENDERING)

    response = api.post(URL, _body(archive), format='json')

    assert response.status_code == 200
    assert response.json() == {'id': created['id'], 'status': 'rendering'}


def test_a_different_preset_is_a_different_job(api: APIClient, archive: Archive) -> None:
    api.post(URL, _body(archive), format='json')

    response = api.post(URL, _body(archive, preset='light'), format='json')

    assert response.status_code == 202
    assert Clip.objects.count() == 2


# --- GET ---------------------------------------------------------------------


def test_a_queued_clip_has_no_video_url(api: APIClient, archive: Archive) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']

    response = api.get(f'{URL}{clip_id}/')

    assert response.status_code == 200
    assert response.json() == {'id': clip_id, 'status': 'queued', 'video_url': None}


@pytest.mark.parametrize('status', [ClipStatus.RENDERING, ClipStatus.FAILED])
def test_an_unfinished_clip_has_no_video_url(
    api: APIClient, archive: Archive, status: str
) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']
    Clip.objects.filter(pk=clip_id).update(status=status)

    assert api.get(f'{URL}{clip_id}/').json()['video_url'] is None


def test_a_finished_clip_serves_a_presigned_url(api: APIClient, archive: Archive) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']
    Clip.objects.filter(pk=clip_id).update(
        status=ClipStatus.DONE, storage_key='clips/rendered.mp4'
    )

    body = api.get(f'{URL}{clip_id}/').json()

    assert set(body) == {'id', 'status', 'video_url'}
    assert body['status'] == 'done'
    assert 'X-Amz-Signature=' in body['video_url']


def test_an_unknown_clip_is_404(api: APIClient, archive: Archive) -> None:
    assert api.get(f'{URL}00000000-0000-4000-8000-000000000000/').status_code == 404
