"""POST /api/clips/ and GET /api/clips/{id}/ per API_CONTRACT.md."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from rest_framework.test import APIClient

from api.tests.factories import Archive
from clips.models import MIN_SPAN_MS, Clip, ClipStatus

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
    assert (clip.start_ms, clip.end_ms, clip.preset, clip.output) == (
        125_000, 155_000, 'night', 'video'
    )
    assert clip.storage_key == ''  # rendering is somebody else's job


@pytest.mark.parametrize('span', [MIN_SPAN_MS, 60_000])
def test_the_span_bounds_are_inclusive(api: APIClient, archive: Archive, span: int) -> None:
    response = api.post(URL, _body(archive, end_ms=125_000 + span), format='json')

    assert response.status_code == 202


def test_a_span_may_run_to_the_end_of_the_segment(
    api: APIClient, archive: Archive
) -> None:
    """The 60s cap is gone: any span up to the segment length is legal."""
    response = api.post(
        URL, _body(archive, start_ms=0, end_ms=archive.segment.duration_ms), format='json'
    )

    assert response.status_code == 202


@pytest.mark.parametrize(
    'overrides',
    [
        {'end_ms': 125_000 + (MIN_SPAN_MS - 1)},  # too short
        {'start_ms': 155_000, 'end_ms': 125_000},  # inverted
        {'start_ms': 580_000, 'end_ms': 610_000},  # past the end of the segment
        {'preset': 'neon'},
        {'output': 'gif'},
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


def test_a_failed_clip_is_queued_again_exactly_once(
    api: APIClient,
    archive: Archive,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """A failure is usually transient, so asking again retries — but the retry
    reads and writes the same row, so it happens under ``select_for_update``.
    Without the lock, two requests both see ``failed``, both flip it to
    ``queued`` and both enqueue, and two workers render the same clip over the
    same object key."""
    enqueued: list[str] = []
    monkeypatch.setattr(
        'clips.views.render_clip', SimpleNamespace(delay=enqueued.append)
    )
    created = api.post(URL, _body(archive), format='json').json()
    Clip.objects.filter(pk=created['id']).update(status=ClipStatus.FAILED, error='boom')

    responses = []
    for _ in range(2):
        # The enqueue is deferred to commit, which never happens inside a test
        # transaction unless it is captured.
        with django_capture_on_commit_callbacks(execute=True):
            responses.append(api.post(URL, _body(archive), format='json'))

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.json()['status'] for response in responses] == ['queued', 'queued']
    assert len(enqueued) == 1  # the second request found it already re-queued
    assert enqueued == [created['id']]
    clip = Clip.objects.get(pk=created['id'])
    assert (clip.status, clip.error) == (ClipStatus.QUEUED, '')


def test_a_different_preset_is_a_different_job(api: APIClient, archive: Archive) -> None:
    api.post(URL, _body(archive), format='json')

    response = api.post(URL, _body(archive, preset='light'), format='json')

    assert response.status_code == 202
    assert Clip.objects.count() == 2


def test_a_different_output_is_a_different_job(api: APIClient, archive: Archive) -> None:
    api.post(URL, _body(archive), format='json')

    response = api.post(URL, _body(archive, output='audio'), format='json')

    assert response.status_code == 202
    assert Clip.objects.count() == 2


# --- GET ---------------------------------------------------------------------


def test_a_queued_clip_has_no_urls(api: APIClient, archive: Archive) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']

    response = api.get(f'{URL}{clip_id}/')

    assert response.status_code == 200
    assert response.json() == {
        'id': clip_id,
        'status': 'queued',
        'output': 'video',
        'video_url': None,
        'audio_url': None,
    }


@pytest.mark.parametrize('status', [ClipStatus.RENDERING, ClipStatus.FAILED])
def test_an_unfinished_clip_has_no_urls(
    api: APIClient, archive: Archive, status: str
) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']
    Clip.objects.filter(pk=clip_id).update(status=status)

    body = api.get(f'{URL}{clip_id}/').json()
    assert body['video_url'] is None
    assert body['audio_url'] is None


def test_a_finished_video_serves_a_presigned_url(
    api: APIClient, archive: Archive
) -> None:
    clip_id = api.post(URL, _body(archive), format='json').json()['id']
    Clip.objects.filter(pk=clip_id).update(
        status=ClipStatus.DONE, storage_key='clips/rendered.mp4'
    )

    body = api.get(f'{URL}{clip_id}/').json()

    assert set(body) == {'id', 'status', 'output', 'video_url', 'audio_url'}
    assert body['status'] == 'done'
    assert body['output'] == 'video'
    assert 'X-Amz-Signature=' in body['video_url']
    assert body['audio_url'] is None


def test_a_finished_audio_serves_a_presigned_audio_url(
    api: APIClient, archive: Archive
) -> None:
    clip_id = api.post(URL, _body(archive, output='audio'), format='json').json()['id']
    Clip.objects.filter(pk=clip_id).update(
        status=ClipStatus.DONE, storage_key='clips/rendered.m4a'
    )

    body = api.get(f'{URL}{clip_id}/').json()

    assert body['output'] == 'audio'
    assert body['video_url'] is None
    assert 'X-Amz-Signature=' in body['audio_url']


def test_an_unknown_clip_is_404(api: APIClient, archive: Archive) -> None:
    assert api.get(f'{URL}00000000-0000-4000-8000-000000000000/').status_code == 404
