"""Stage 1: the planner, and its fallback when the model cannot be asked."""

from __future__ import annotations

import httpx
import pytest
import respx

from quran.models import Surah
from search.smart import llm, planner
from search.smart.schemas import AyahRef, QueryPlan

from .openrouter_fakes import chat_completion, error_response, request_json

pytestmark = pytest.mark.django_db

QUESTION = "ما رأي الشيخ في نجاة والدي النبي"

RAW_PLAN = {
    "intent": "opinion",
    "language": "ar",
    "topic_ar": "  مصير والدي النبي  ",
    "rewrites": [
        "والدا النبي من أهل الفترة",
        "وَالِدَا النَّبِيِّ مِنْ أَهْلِ الْفَتْرَةِ",  # the first again, vowelled
        QUESTION,  # the question itself is not a rewrite
        "",
        "حديث إن أبي وأباك في النار",
        "عبد الله وآمنة",
        "أهل الفترة",
        "من لم تبلغه الدعوة",
        "حكم أهل الفترة عند الشعراوي",  # sixth distinct rewrite: over the cap
    ],
    "keywords": ["أهل الفترة", "اهل الفتره", "والدي النبي"],
    "ayah_refs": [
        {"surah": 2, "ayah": 255},
        {"surah": 2, "ayah": 255},
        {"surah": 2, "ayah": 9999},  # no such ayah
        {"surah": 0, "ayah": 1},
        {"surah": 24, "ayah": 35},
    ],
    "surah_hint": 200,
    "answerable_from_corpus": "maybe",
}


def test_the_plan_is_tidied_before_use(
    quran_slice: dict[int, Surah], openrouter: respx.MockRouter
) -> None:
    route = openrouter.post("/chat/completions").mock(
        return_value=chat_completion(RAW_PLAN, model="test/planner")
    )

    result = planner.plan(QUESTION)

    assert not result.naive and result.warning is None
    body = request_json(route.calls.last.request)
    assert body["model"] == "test/planner"
    assert body["messages"][1]["content"] == QUESTION
    assert body["reasoning"] == {"effort": "minimal"}
    plan = result.plan
    assert plan.topic_ar == "مصير والدي النبي"
    assert plan.rewrites == [
        "والدا النبي من أهل الفترة",
        "حديث إن أبي وأباك في النار",
        "عبد الله وآمنة",
        "أهل الفترة",
        "من لم تبلغه الدعوة",
    ]
    assert plan.keywords == ["أهل الفترة", "والدي النبي"]
    assert plan.ayah_refs == [AyahRef(surah=2, ayah=255), AyahRef(surah=24, ayah=35)]
    assert plan.surah_hint is None
    assert result.usage is not None and result.usage.model == "test/planner"


def test_a_provider_failure_yields_the_naive_plan(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(return_value=error_response(500, "down"))

    result = planner.plan(QUESTION)

    assert result.naive and result.warning is not None and result.warning.startswith("planner:")
    assert result.plan == planner.naive_plan(QUESTION)
    assert result.plan.rewrites == [] and result.plan.topic_ar == QUESTION
    assert result.usage is None


def test_a_malformed_answer_yields_the_naive_plan(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion({"intent": "opinion"}, model="test/planner")
    )

    assert planner.plan(QUESTION).naive


def test_an_expired_deadline_skips_the_planner(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))

    result = planner.plan(QUESTION, deadline=llm.Deadline(budget_s=0.0))

    assert result.naive and route.call_count == 0


def test_tidy_plan_keeps_a_valid_surah_hint(quran_slice: dict[int, Surah]) -> None:
    raw = QueryPlan.model_validate({**RAW_PLAN, "surah_hint": 2, "rewrites": ["x"]})

    assert planner.tidy_plan(QUESTION, raw).surah_hint == 2
    assert planner.tidy_plan(QUESTION, raw).rewrites == ["x"]
