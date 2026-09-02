"""``POST /api/search/smart/`` end to end, against a faked provider.

One fixture corpus with transcript words, passages and stub embeddings; one
respx dispatcher that answers the planner, the reranker and the generator by
the model named in each request. The generator stub cites whichever context
passage carries the fixture's الصبر chunk, so the assertions can check that a
quote comes back as the milliseconds of the words it spans.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from dataclasses import dataclass

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.core.management import call_command
from pytest_django.fixtures import Settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from search.models import EMBEDDING_DIMENSIONS, Passage, SmartQuery
from search.smart import budget, embedding_model_tag, passages

from .conftest import CHUNK_MS, CorpusFixture, add_words
from .openrouter_fakes import (
    chat_completion,
    embedding_response,
    error_response,
    request_json,
    stub_vector,
)

pytestmark = pytest.mark.django_db

URL = "/api/search/smart/"
QUESTION = "ماذا قال الشيخ عن الصبر عند الصدمة"
PLAN = {
    "intent": "opinion",
    "language": "ar",
    "topic_ar": "الصبر عند الصدمة الأولى",
    "rewrites": ["الصبر عند الصدمة الأولى", "فضل الصبر"],
    "keywords": ["الصبر"],
    "ayah_refs": [{"surah": 2, "ayah": 255}],
    "surah_hint": None,
    "answerable_from_corpus": "likely",
}


@dataclass
class Provider:
    router: respx.MockRouter
    chat: respx.Route
    embeddings: respx.Route
    generator_fails: bool = False

    def calls(self, model: str) -> int:
        return sum(
            1 for call in self.chat.calls if request_json(call.request)["model"] == model
        )


@pytest.fixture
def provider(
    corpus: CorpusFixture, smart_settings: Settings, openrouter: respx.MockRouter
) -> Provider:
    smart_settings.SMART_EMBEDDING_DIMENSIONS = EMBEDDING_DIMENSIONS
    for segment in (corpus.khawatir, corpus.recitation):
        add_words(segment)
        transcript = passages.transcripts_with_chunks().get(pk=segment.transcript.pk)
        passages.build_for_transcript(transcript, min_words=6, max_words=12)
    for row in Passage.objects.all():
        row.embedding = stub_vector(row.text_normalized, EMBEDDING_DIMENSIONS)
        row.embedding_model = embedding_model_tag()
        row.embedded_hash = row.content_hash
        row.save()

    state = Provider(router=openrouter, chat=None, embeddings=None)  # type: ignore[arg-type]

    def embed(request: httpx.Request) -> httpx.Response:
        texts = request_json(request)["input"]
        return embedding_response([stub_vector(t, EMBEDDING_DIMENSIONS) for t in texts])

    def chat(request: httpx.Request) -> httpx.Response:
        body = request_json(request)
        model = body["model"]
        user = body["messages"][1]["content"]
        if model == "test/planner":
            return chat_completion(PLAN, model=model)
        if model == "test/rerank":
            ids = [int(part.split('"')[0]) for part in user.split('<c id="')[1:]]
            return chat_completion(
                {"scores": [{"id": pid, "score": 3} for pid in ids]}, model=model
            )
        if state.generator_fails:
            return error_response(500, "generator down")
        target = next(
            block.split('"')[0]
            for block in user.split('<passage id="')[1:]
            if "الصبر عند الصدمة" in block
        )
        return chat_completion(
            {
                "status": "answered",
                "answer_md": (
                    f"قال الشيخ الشعراوي رحمه الله صراحةً إن الصبر عند الصدمة الأولى [{target}]. "
                    f"واستشهد بقوله تعالى [[ayah:2:255]] [{target}]. جملة بلا مرجع."
                ),
                "citations": [{"passage_id": target, "quote": "الصبر عند الصدمة"}],
                "ayah_refs": [{"surah": 2, "ayah": 255}],
                "followups": ["ما فضل الصبر؟"],
            },
            model=model,
        )

    state.embeddings = openrouter.post("/embeddings").mock(side_effect=embed)
    state.chat = openrouter.post("/chat/completions").mock(side_effect=chat)
    return state


@pytest.fixture
def tight_smart_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        SimpleRateThrottle, "THROTTLE_RATES", {"smart": "2/min", "smart_feedback": "2/min"}
    )


def test_an_answer_carries_verified_citations_with_milliseconds(
    api: APIClient, provider: Provider, corpus: CorpusFixture
) -> None:
    response = api.post(URL, {"question": QUESTION}, format="json")

    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["status"] == "answered" and body["mode"] == "smart"
    assert body["cache_hit"] is False and body["debug"] is None
    assert uuid.UUID(body["query_id"])
    assert body["answer_md"] == (
        "قال الشيخ الشعراوي رحمه الله صراحةً إن الصبر عند الصدمة الأولى [1].\n"
        "واستشهد بقوله تعالى [[ayah:2:255]] [1]."
    )
    (citation,) = body["citations"]
    assert citation["n"] == 1
    assert citation["segment_id"] == corpus.khawatir.pk
    assert citation["start_ms"] == CHUNK_MS and citation["end_ms"] == CHUNK_MS + 2900
    assert citation["quote_display"] == "الصَّبْرُ عِنْدَ الصَّدْمَةِ"
    assert citation["listen_url"] == f"/listen/{corpus.khawatir.pk}?t={CHUNK_MS}"
    assert citation["chunk_id"] == corpus.chunks[1].pk
    assert body["ayah_refs"][0]["surah_name_ar"] == "البقرة"
    assert "ٱللَّهُ" in body["ayah_refs"][0]["text_uthmani"]
    assert body["followups"] == ["ما فضل الصبر؟"]
    assert body["passages"] and all("excerpt_display" in p for p in body["passages"])
    assert provider.calls("test/planner") == provider.calls("test/generator") == 1
    assert provider.calls("test/rerank") >= 1 and provider.embeddings.call_count == 1

    row = SmartQuery.objects.get(pk=body["query_id"])
    assert row.status == "answered" and row.cache_hit is False
    assert row.question == QUESTION and row.ip_hash and len(row.ip_hash) == 32
    assert set(row.models_used) == {"planner", "embedding", "rerank", "generator"}
    assert row.cost_usd > 0 and row.usage["calls"] >= 4
    assert row.plan["topic_ar"] == PLAN["topic_ar"] and row.candidate_ids
    assert set(row.latency_ms) >= {"plan", "retrieve", "rerank", "context", "generate", "total"}
    assert row.answer["citations"][0]["start_ms"] == CHUNK_MS


def test_the_same_question_is_answered_from_the_cache(api: APIClient, provider: Provider) -> None:
    first = api.post(URL, {"question": QUESTION}, format="json").json()
    chat_calls = provider.chat.call_count

    second = api.post(URL, {"question": "  " + QUESTION + " "}, format="json").json()

    assert provider.chat.call_count == chat_calls and provider.embeddings.call_count == 1
    assert second["cache_hit"] is True and second["query_id"] != first["query_id"]
    assert second["answer_md"] == first["answer_md"]
    assert second["citations"] == first["citations"]
    assert SmartQuery.objects.get(pk=second["query_id"]).cache_hit is True


def test_debug_is_for_staff_only(api: APIClient, provider: Provider) -> None:
    anonymous = api.post(URL, {"question": QUESTION, "debug": True}, format="json").json()
    assert anonymous["debug"] is None

    staff = get_user_model().objects.create_user("staff", "s@example.com", "x", is_staff=True)
    api.force_authenticate(staff)
    response = api.post(URL, {"question": QUESTION + "؟", "debug": True}, format="json")

    debug = response.json()["debug"]
    assert debug["plan"]["topic_ar"] == PLAN["topic_ar"]
    assert [t["stage"] for t in debug["timings"]][:3] == ["plan", "retrieve", "rerank"]
    assert debug["warnings"] == [] and debug["verify"]
    assert SmartQuery.objects.get(pk=response.json()["query_id"]).user == staff


def test_a_generator_failure_degrades_but_keeps_the_passages(
    api: APIClient, provider: Provider
) -> None:
    provider.generator_fails = True

    response = api.post(URL, {"question": QUESTION}, format="json")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "degraded" and body["answer_md"] is None
    assert body["citations"] == [] and body["passages"]
    assert SmartQuery.objects.get(pk=body["query_id"]).status == "degraded"

    # Not cached: the next request tries again.
    provider.generator_fails = False
    again = api.post(URL, {"question": QUESTION}, format="json").json()
    assert again["status"] == "answered" and again["cache_hit"] is False


def test_nothing_retrieved_is_not_found(api: APIClient, provider: Provider) -> None:
    provider.router.post("/chat/completions").mock(
        return_value=chat_completion(
            {**PLAN, "rewrites": [], "keywords": [], "ayah_refs": []}, model="test/planner"
        )
    )
    provider.router.post("/embeddings").mock(return_value=error_response(500, "down"))

    body = api.post(URL, {"question": "xyzzy"}, format="json").json()

    assert body["status"] == "not_found" and body["passages"] == []
    assert "لم أجد" in body["answer_md"]


def test_the_flag_off_answers_503(api: APIClient, smart_settings: Settings) -> None:
    smart_settings.SMART_ENABLED = False

    response = api.post(URL, {"question": QUESTION}, format="json")

    assert response.status_code == 503 and "detail" in response.json()


@pytest.mark.parametrize(
    "body", [{}, {"question": ""}, {"question": "   "}, {"question": "س" * 501}]
)
def test_bad_questions_answer_400(api: APIClient, provider: Provider, body: dict[str, str]) -> None:
    response = api.post(URL, body, format="json")

    assert response.status_code == 400
    assert response.json()["detail"].startswith("question")
    assert provider.chat.call_count == 0


def test_bad_filters_answer_400(api: APIClient, provider: Provider) -> None:
    response = api.post(URL, {"question": QUESTION, "filters": {"surah": 0}}, format="json")

    assert response.status_code == 400 and response.json()["detail"].startswith("filters")


def test_filters_narrow_every_channel(
    api: APIClient, provider: Provider, corpus: CorpusFixture
) -> None:
    body = api.post(URL, {"question": QUESTION, "filters": {"surah": 3}}, format="json").json()

    assert body["status"] in {"not_found", "degraded", "partial", "answered"}
    assert {p["segment_id"] for p in body["passages"]} <= {corpus.recitation.pk}
    row = SmartQuery.objects.get(pk=body["query_id"])
    assert row.filters == {"surah": 3}


def test_the_hourly_rate_is_enforced_per_client(
    api: APIClient, provider: Provider, tight_smart_rate: None
) -> None:
    for _ in range(2):
        assert api.post(URL, {"question": QUESTION}, format="json").status_code == 200

    response = api.post(URL, {"question": QUESTION}, format="json")

    assert response.status_code == 429 and response["Retry-After"]


def test_the_concurrency_cap_answers_429_with_retry_after(
    api: APIClient, provider: Provider, smart_settings: Settings
) -> None:
    now = time.time()
    budget.redis_client().zadd(
        budget.INFLIGHT_KEY, {f"busy-{n}": now for n in range(smart_settings.SMART_MAX_INFLIGHT)}
    )

    response = api.post(URL, {"question": QUESTION}, format="json")

    assert response.status_code == 429
    assert response["Retry-After"] == "10"
    assert provider.chat.call_count == 0


def test_feedback_is_recorded_once_per_query(api: APIClient, provider: Provider) -> None:
    query_id = api.post(URL, {"question": QUESTION}, format="json").json()["query_id"]

    response = api.post(
        f"{URL}{query_id}/feedback/", {"vote": "down", "note": "غير دقيق"}, format="json"
    )

    assert response.status_code == 201 and response.json() == {"status": "recorded"}
    row = SmartQuery.objects.get(pk=query_id)
    assert row.feedback == "down" and row.feedback_note == "غير دقيق" and row.feedback_at

    unknown = f"{URL}{uuid.uuid4()}/feedback/"
    assert api.post(unknown, {"vote": "up"}, format="json").status_code == 404
    assert api.post(f"{URL}{query_id}/feedback/", {"vote": "meh"}, format="json").status_code == 400
    assert api.post(f"{URL}not-a-uuid/feedback/", {"vote": "up"}, format="json").status_code == 404


def test_smart_answer_command_without_a_provider(provider: Provider) -> None:
    out = io.StringIO()
    call_command("smart_answer", "الصبر عند الصدمة", "--no-llm", "--debug", stdout=out)

    body = json.loads(out.getvalue())
    assert body["status"] == "degraded" and body["answer_md"] is None
    assert body["passages"] and body["debug"]["plan"]["rewrites"] == []
    assert provider.chat.call_count == 0
