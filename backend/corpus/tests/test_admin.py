"""The review screens (``corpus.admin``).

No browser involved: the admin is thin enough that calling its display methods
and actions directly is the whole of it, which is the point of keeping the work
in ``corpus.corrections`` and ``corpus.topics``.
"""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import constants
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest
from django.test import RequestFactory

from corpus.admin import CorrectionAdmin, TopicAdmin
from corpus.models import Correction, CorrectionStatus, Topic
from corpus.topics import build_topics

from .conftest import Passages, make_correction
from .test_topics import build_clusters

pytestmark = pytest.mark.django_db

TARGET = (12, 14)


def _request() -> HttpRequest:
    request = RequestFactory().post("/admin/corpus/correction/")
    request.user = AnonymousUser()
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _messages(request: HttpRequest) -> list[tuple[int, str]]:
    return [(message.level, message.message) for message in request._messages]


@pytest.fixture
def correction_admin() -> CorrectionAdmin:
    return CorrectionAdmin(Correction, AdminSite())


@pytest.fixture
def topic_admin() -> TopicAdmin:
    return TopicAdmin(Topic, AdminSite())


def test_the_queue_shows_both_versions(
    correction_admin: CorrectionAdmin, passages: Passages
) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    rendered = correction_admin.comparison(correction)

    assert "قلوب المؤمنين نور" in rendered  # the machine transcript as it stands
    assert "قلوب مؤمنة" in rendered
    assert 'dir="rtl"' in rendered


def test_the_play_link_points_at_the_corrected_seconds(
    correction_admin: CorrectionAdmin, passages: Passages
) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    rendered = correction_admin.play_range(correction)

    assert "#t=12.000" in rendered  # media fragment, seconds
    assert "12000" in rendered and "14900" in rendered  # the exact ms
    assert "X-Amz-Signature" in rendered  # presigned, never a bucket path
    assert correction_admin.word_range(correction) == "12–14"


def test_the_approve_action_applies_and_reports(
    correction_admin: CorrectionAdmin, passages: Passages
) -> None:
    make_correction(passages, *TARGET, "قلوب مؤمنة")
    request = _request()

    correction_admin.approve_selected(request, Correction.objects.all())

    passages.transcript.refresh_from_db()
    assert passages.transcript.version == 2
    assert Correction.objects.get().status == CorrectionStatus.APPROVED
    assert [level for level, _ in _messages(request)] == [constants.SUCCESS]


def test_the_approve_action_reports_a_refusal_instead_of_raising(
    correction_admin: CorrectionAdmin, passages: Passages
) -> None:
    correction = make_correction(passages, 9, 12, "نص", chunk=passages.chunks[1])
    request = _request()

    correction_admin.approve_selected(request, Correction.objects.all())

    correction.refresh_from_db()
    assert correction.status == CorrectionStatus.PENDING
    assert [level for level, _ in _messages(request)] == [constants.ERROR]


def test_the_reject_action_closes_the_correction(
    correction_admin: CorrectionAdmin, passages: Passages
) -> None:
    make_correction(passages, *TARGET, "قلوب مؤمنة")
    request = _request()

    correction_admin.reject_selected(request, Correction.objects.all())

    assert Correction.objects.get().status == CorrectionStatus.REJECTED
    assert passages.transcript.version == 1


def test_a_topic_previews_its_most_central_passages(
    topic_admin: TopicAdmin, db: None
) -> None:
    build_clusters()
    (topic, *_) = build_topics().topics

    rendered = topic_admin.central_chunks(topic)

    best = topic.chunk_links.order_by("-score").first()
    assert best is not None
    assert best.chunk.text in rendered
    assert f"{best.score:.3f}" in rendered  # the score, not a raw float


def test_a_topic_without_passages_previews_a_dash(topic_admin: TopicAdmin, db: None) -> None:
    topic = Topic.objects.create(slug="empty", name_ar="فارغ")

    assert topic_admin.central_chunks(topic) == "—"


def test_publishing_is_the_gate(topic_admin: TopicAdmin, db: None) -> None:
    build_clusters()
    build_topics()
    request = _request()

    topic_admin.publish_selected(request, Topic.objects.all())

    assert not Topic.objects.filter(is_published=False).exists()

    topic_admin.unpublish_selected(request, Topic.objects.all())

    assert not Topic.objects.filter(is_published=True).exists()


def test_the_topic_list_counts_its_passages(topic_admin: TopicAdmin, db: None) -> None:
    build_clusters()
    (topic, *_) = build_topics().topics

    listed = topic_admin.get_queryset(_request()).get(pk=topic.pk)

    assert topic_admin.chunk_count(listed) == topic.chunk_links.count()


def test_a_reviewer_cannot_forge_a_correction(correction_admin: CorrectionAdmin) -> None:
    """Corrections come from readers; the queue is not an editing surface."""
    assert correction_admin.has_add_permission(_request()) is False
    assert set(correction_admin.readonly_fields) == set(correction_admin.fields)
