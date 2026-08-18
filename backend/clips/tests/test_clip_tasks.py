"""What the API hands to Celery, and what Celery hands back to the renderer.

The cache promise of ``POST /api/clips/`` is only half kept by the unique
constraint: returning the same row is worthless if the second request still
costs a render. These tests count enqueues, not rows.

The broker is never involved — ``delay`` is captured — but the commit boundary
is: a task dispatched before the transaction lands would look up a clip that
does not exist yet.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from rest_framework.test import APIClient

from api.tests.factories import Archive
from clips import rendering, tasks
from clips.models import Clip, ClipStatus

pytestmark = pytest.mark.django_db

URL = '/api/clips/'


class Recorder:
    """Stands in for the Celery task in the view's namespace."""

    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def delay(self, clip_id: str) -> None:
        self.enqueued.append(clip_id)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr('clips.views.render_clip', recorder)
    return recorder


def _body(archive: Archive, **overrides: Any) -> dict[str, Any]:
    return {
        'segment_id': archive.segment.pk,
        'start_ms': 125_000,
        'end_ms': 155_000,
        'preset': 'night',
        **overrides,
    }


# --- enqueue -----------------------------------------------------------------


def test_a_new_clip_is_enqueued_only_once_the_row_is_committed(
    api: APIClient,
    archive: Archive,
    enqueued: Recorder,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    with django_capture_on_commit_callbacks() as callbacks:
        response = api.post(URL, _body(archive), format='json')

    assert response.status_code == 202
    assert enqueued.enqueued == []  # nothing dispatched mid-transaction
    assert len(callbacks) == 1

    callbacks[0]()

    assert enqueued.enqueued == [response.json()['id']]


def test_the_second_request_for_a_clip_does_not_pay_for_it_again(
    api: APIClient,
    archive: Archive,
    enqueued: Recorder,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """The regression that matters: the cache has to survive the task wiring."""
    with django_capture_on_commit_callbacks(execute=True):
        first = api.post(URL, _body(archive), format='json')
    with django_capture_on_commit_callbacks(execute=True):
        second = api.post(URL, _body(archive), format='json')

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json() == first.json()
    assert Clip.objects.count() == 1
    assert enqueued.enqueued == [first.json()['id']]


@pytest.mark.parametrize('status', [ClipStatus.RENDERING, ClipStatus.DONE])
def test_a_job_already_in_flight_is_left_alone(
    api: APIClient,
    archive: Archive,
    enqueued: Recorder,
    django_capture_on_commit_callbacks: Callable[..., Any],
    status: str,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        created = api.post(URL, _body(archive), format='json').json()
    Clip.objects.filter(pk=created['id']).update(status=status)

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(URL, _body(archive), format='json')

    assert response.json() == {'id': created['id'], 'status': status}
    assert enqueued.enqueued == [created['id']]


def test_a_failed_clip_is_queued_again(
    api: APIClient,
    archive: Archive,
    enqueued: Recorder,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """A dead row would otherwise be permanent: the unique constraint hands every
    later request the same failure."""
    with django_capture_on_commit_callbacks(execute=True):
        created = api.post(URL, _body(archive), format='json').json()
    Clip.objects.filter(pk=created['id']).update(
        status=ClipStatus.FAILED, error='worker died'
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(URL, _body(archive), format='json')

    assert response.json() == {'id': created['id'], 'status': 'queued'}
    assert enqueued.enqueued == [created['id'], created['id']]
    clip = Clip.objects.get(pk=created['id'])
    assert (clip.status, clip.error) == (ClipStatus.QUEUED, '')
    assert Clip.objects.count() == 1


# --- the task ----------------------------------------------------------------


def test_the_task_answers_to_the_name_the_worker_dispatches() -> None:
    assert tasks.render_clip.name == 'clips.render_clip'


def test_the_task_hands_the_row_to_the_renderer(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = Clip.objects.create(
        segment=archive.segment, start_ms=125_000, end_ms=155_000, preset='night'
    )
    rendered: list[Clip] = []
    monkeypatch.setattr(rendering, 'render_clip', rendered.append)

    tasks.render_clip(str(clip.pk))

    assert [row.pk for row in rendered] == [clip.pk]


def test_the_task_shrugs_off_a_clip_that_is_gone(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued task can outlive its row; that is not a failure worth retrying."""
    rendered: list[Clip] = []
    monkeypatch.setattr(rendering, 'render_clip', rendered.append)

    tasks.render_clip(str(uuid.uuid4()))

    assert rendered == []
