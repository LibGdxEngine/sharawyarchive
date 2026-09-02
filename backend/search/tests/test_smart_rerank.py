"""Stage 3: listwise reranking, batching and its fallbacks (no database needed)."""

from __future__ import annotations

import httpx
import pytest
import respx

from search.smart import llm, rerank
from search.smart.schemas import Candidate

from .openrouter_fakes import chat_completion, error_response, request_json


def _candidates(count: int) -> list[Candidate]:
    return [
        Candidate(
            passage_id=index + 1,
            header=f"مقطع {index + 1}",
            text_normalized=" ".join(["كلمه"] * (index + 1)),
            rrf=1.0 / (index + 1),
            channel_ranks={"lexical:0": index + 1},
        )
        for index in range(count)
    ]


def _scores(**scores: int) -> dict[str, list[dict[str, int]]]:
    return {"scores": [{"id": int(key[1:]), "score": value} for key, value in scores.items()]}


def _by_request(mapping: dict[int, int]) -> object:
    """A responder scoring whichever candidate ids the request rendered."""

    def respond(request: httpx.Request) -> httpx.Response:
        user = request_json(request)["messages"][1]["content"]
        ids = [int(part.split('"')[0]) for part in user.split('<c id="')[1:]]
        return chat_completion(
            {"scores": [{"id": pid, "score": mapping.get(pid, 0)} for pid in ids]},
            model="test/rerank",
        )

    return respond


def test_render_candidates_caps_the_text(openrouter: respx.MockRouter) -> None:
    long = Candidate(passage_id=7, header="h", text_normalized=" ".join(["w"] * 300), rrf=0.1)
    rendered = rerank.render_candidates([long])

    assert rendered.startswith('<c id="7">h\n')
    assert rendered.endswith(" …</c>")
    assert rendered.count("w ") == rerank.TEXT_WORDS


def test_keeps_well_scored_candidates_ordered_by_score_then_fusion(
    openrouter: respx.MockRouter,
) -> None:
    route = openrouter.post("/chat/completions").mock(
        side_effect=_by_request({1: 1, 2: 3, 3: 2, 4: 2, 5: 0, 6: 3})
    )

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(6))

    assert route.call_count == 1
    body = request_json(route.calls.last.request)
    assert body["model"] == "test/rerank"
    assert body["messages"][1]["content"].startswith("Question: سؤال")
    assert [(p.passage_id, p.score) for p in outcome.passages] == [
        (2, 3),
        (6, 3),
        (3, 2),
        (4, 2),
    ]
    assert outcome.scored and not outcome.weak_evidence
    assert [usage.model for usage in outcome.usage] == ["test/rerank"]


def test_batches_of_twenty_and_the_top_eight(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(
        side_effect=_by_request({pid: 3 if pid % 4 == 0 else 2 for pid in range(1, 41)})
    )

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(40))

    assert route.call_count == 2
    sizes = sorted(
        request_json(call.request)["messages"][1]["content"].count("<c id=")
        for call in route.calls
    )
    assert sizes == [20, 20]
    assert len(outcome.passages) == rerank.TOP_N
    assert [p.passage_id for p in outcome.passages] == [4, 8, 12, 16, 20, 24, 28, 32]


def test_weak_evidence_passes_the_fused_top_three(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(side_effect=_by_request({3: 2}))

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(6))

    assert outcome.weak_evidence
    assert [(p.passage_id, p.score) for p in outcome.passages] == [(3, 2), (1, 0), (2, 0)]

    openrouter.post("/chat/completions").mock(side_effect=_by_request({}))
    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(6))
    assert outcome.weak_evidence
    assert [p.passage_id for p in outcome.passages] == [1, 2, 3]


def test_unknown_and_out_of_range_scores_are_ignored(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion(
            {"scores": [{"id": 99, "score": 3}, {"id": 2, "score": 7}, {"id": 1, "score": -4}]},
            model="test/rerank",
        )
    )

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(3))

    assert [(p.passage_id, p.score) for p in outcome.passages] == [(2, 3), (1, 0), (3, 0)]
    assert outcome.weak_evidence


def test_a_failed_batch_falls_back_to_the_fused_order(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(return_value=error_response(500, "down"))

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(12))

    assert route.called
    assert outcome.warning is not None and outcome.warning.startswith("rerank:")
    assert not outcome.scored
    assert [p.passage_id for p in outcome.passages] == list(range(1, 9))
    assert all(p.score == 0 for p in outcome.passages)


def test_a_tight_deadline_skips_the_stage(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(side_effect=_by_request({1: 3}))

    outcome = rerank.LLMListwiseReranker().rerank(
        "سؤال", _candidates(5), deadline=llm.Deadline(budget_s=rerank.MIN_DEADLINE_S - 1)
    )

    assert outcome.skipped and route.call_count == 0
    assert [p.passage_id for p in outcome.passages] == [1, 2, 3, 4, 5]


def test_no_candidates_means_no_call(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(side_effect=_by_request({}))

    assert rerank.LLMListwiseReranker().rerank("سؤال", []).passages == []
    assert route.call_count == 0


def test_the_noop_reranker_is_the_fused_order() -> None:
    outcome = rerank.NoopReranker().rerank("سؤال", _candidates(10))

    assert outcome.skipped
    assert [p.passage_id for p in outcome.passages] == list(range(1, 9))
    assert [p.rrf for p in outcome.passages] == [1.0 / n for n in range(1, 9)]


@pytest.mark.parametrize("count", [1, 2])
def test_fewer_than_two_survivors_is_weak(openrouter: respx.MockRouter, count: int) -> None:
    openrouter.post("/chat/completions").mock(
        side_effect=_by_request({pid: 3 for pid in range(1, count + 1)})
    )

    outcome = rerank.LLMListwiseReranker().rerank("سؤال", _candidates(4))

    assert outcome.weak_evidence is (count < 2)
