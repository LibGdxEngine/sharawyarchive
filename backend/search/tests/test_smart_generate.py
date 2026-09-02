"""Stage 5: the generator call and its single regeneration."""

from __future__ import annotations

import pytest
import respx

from search.smart import generate, llm, planner
from search.smart.schemas import ContextPassage

from .openrouter_fakes import chat_completion, request_json

PASSAGE = ContextPassage(
    id="p1",
    passage_ids=[1],
    transcript_id=1,
    segment_id=1,
    segment_title="خواطر",
    surah=2,
    ayah_start=1,
    ayah_end=10,
    start_ms=0,
    end_ms=1000,
    chunk_idx_start=0,
    chunk_idx_end=0,
    text="الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى",
)
ANSWER = {
    "status": "answered",
    "answer_md": "قال الشيخ صراحةً إن الصبر عند الصدمة الأولى [p1].",
    "citations": [{"passage_id": "p1", "quote": "الصبر عند الصدمة الأولى"}],
    "ayah_refs": [],
    "followups": [],
}


def test_generate_sends_the_rendered_context(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(
        return_value=chat_completion(ANSWER, model="test/generator")
    )

    answer, usages = generate.generate("سؤال", [PASSAGE], planner.naive_plan("سؤال"))

    assert answer.status == "answered" and [u.model for u in usages] == ["test/generator"]
    body = request_json(route.calls.last.request)
    assert body["model"] == "test/generator"
    assert body["reasoning"] == {"effort": "medium"}
    user = body["messages"][1]["content"]
    assert user.startswith("Question: سؤال\nTopic: سؤال")
    assert '<passage id="p1"' in user and "الصبر عند الصدمة الأولى" in user
    assert "َ" not in user.split("<passage", 1)[1]  # harakat stripped from the context


def test_a_schema_failure_is_retried_once_with_a_note(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(
        side_effect=[
            chat_completion({"status": "answered"}, model="test/generator"),
            chat_completion(ANSWER, model="test/generator"),
        ]
    )

    answer, usages = generate.generate("سؤال", [PASSAGE], planner.naive_plan("سؤال"))

    assert route.call_count == 2 and len(usages) == 1
    assert "rejected" in request_json(route.calls[1].request)["messages"][1]["content"]
    assert "rejected" not in request_json(route.calls[0].request)["messages"][1]["content"]
    assert answer.answer_md == ANSWER["answer_md"]


def test_a_non_arabic_answer_is_retried_once(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(
        side_effect=[
            chat_completion(
                {**ANSWER, "answer_md": "The Sheikh said patience first [p1]."},
                model="test/generator",
            ),
            chat_completion(ANSWER, model="test/generator"),
        ]
    )

    _, usages = generate.generate("سؤال", [PASSAGE], planner.naive_plan("سؤال"))

    assert route.call_count == 2 and len(usages) == 2


def test_two_failures_raise(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion({"status": "answered"}, model="test/generator")
    )

    with pytest.raises(llm.LLMSchemaError):
        generate.generate("سؤال", [PASSAGE], planner.naive_plan("سؤال"))


@pytest.mark.parametrize(
    ("text", "arabic"),
    [("قال الشيخ", True), ("The Sheikh said", False), ("قال الشيخ [p1] 2:255", True), ("", False)],
)
def test_is_arabic(text: str, arabic: bool) -> None:
    assert generate.is_arabic(text) is arabic
