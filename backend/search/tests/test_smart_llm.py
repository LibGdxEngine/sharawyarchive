"""The OpenRouter client (``search.smart.llm``) against a faked provider.

Every test runs through the real ``openai`` SDK and a respx-mocked HTTP
layer, so what is asserted is the wire format OpenRouter will see: strict
JSON-schema output, provider routing, usage accounting, retries and timeouts.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from search.smart import budget, llm
from search.smart.schemas import QueryPlan, strict_json_schema
from search.tests.openrouter_fakes import (
    chat_completion,
    embedding_response,
    error_response,
    request_json,
)

PLAN = {
    "intent": "opinion",
    "language": "ar",
    "topic_ar": "مصير والدي النبي صلى الله عليه وسلم",
    "rewrites": ["والدا النبي من أهل الفترة", "حديث إن أبي وأباك في النار"],
    "keywords": ["أهل الفترة", "والدي النبي"],
    "ayah_refs": [{"surah": 17, "ayah": 15}],
    "surah_hint": None,
    "answerable_from_corpus": "maybe",
}


def _plan(router: respx.MockRouter, **kwargs: object) -> respx.Route:
    return router.post("/chat/completions").mock(
        return_value=chat_completion(PLAN, model="test/planner", **kwargs)  # type: ignore[arg-type]
    )


def _call_planner(**overrides: object) -> tuple[QueryPlan, llm.Usage]:
    params: dict[str, object] = {
        "role": "planner",
        "model": "test/planner",
        "system": "system prompt",
        "user": "ما رأي الشيخ في نجاة والدي النبي",
        "schema": QueryPlan,
        "timeout_s": 8.0,
    }
    params.update(overrides)
    return llm.chat_json(**params)  # type: ignore[arg-type]


# --- chat_json ----------------------------------------------------------------


def test_chat_json_sends_strict_schema_headers_and_routing(openrouter: respx.MockRouter) -> None:
    route = _plan(openrouter)

    plan, usage = _call_planner()

    assert plan.intent == "opinion"
    assert plan.ayah_refs[0].surah == 17
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["http-referer"] == "https://archive.test"
    assert request.headers["x-title"] == "Sha'rawy Archive"
    body = request_json(request)
    assert body["model"] == "test/planner"
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == strict_json_schema(QueryPlan)
    assert body["provider"] == {"require_parameters": True}
    assert body["usage"] == {"include": True}
    assert "reasoning" not in body
    assert body["temperature"] == 0.0
    assert usage.model == "test/planner"
    assert usage.prompt_tokens == 100 and usage.completion_tokens == 50
    assert usage.cost_usd == Decimal("0.001")
    assert budget.spend_today() == Decimal("0.001")


def test_chat_json_passes_reasoning_effort(openrouter: respx.MockRouter) -> None:
    route = _plan(openrouter)

    _call_planner(reasoning_effort="low")

    assert request_json(route.calls.last.request)["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("status", [429, 500, 503])
def test_chat_json_retries_transient_failures_once_then_succeeds(
    openrouter: respx.MockRouter, status: int
) -> None:
    route = openrouter.post("/chat/completions").mock(
        side_effect=[error_response(status), chat_completion(PLAN)]
    )

    plan, _ = _call_planner()

    assert plan.topic_ar.startswith("مصير")
    assert route.call_count == 2


def test_chat_json_does_not_retry_client_errors(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(return_value=error_response(400, "bad"))

    with pytest.raises(llm.LLMError) as excinfo:
        _call_planner()

    assert not isinstance(excinfo.value, llm.LLMTimeout | llm.LLMSchemaError)
    assert route.call_count == 1


def test_chat_json_gives_up_after_three_timeouts(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(llm.LLMTimeout):
        _call_planner()

    assert route.call_count == llm.ATTEMPTS
    assert budget.spend_today() == Decimal("0")


def test_chat_json_rejects_an_answer_of_the_wrong_shape(openrouter: respx.MockRouter) -> None:
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion({"intent": "opinion", "extra": 1})
    )

    with pytest.raises(llm.LLMSchemaError):
        _call_planner()


def test_chat_json_tolerates_fenced_json(openrouter: respx.MockRouter) -> None:
    import json

    fenced = "```json\n" + json.dumps(PLAN, ensure_ascii=False) + "\n```"
    openrouter.post("/chat/completions").mock(return_value=chat_completion(fenced))

    plan, _ = _call_planner()

    assert plan.language == "ar"


def test_chat_json_prices_from_the_table_when_cost_is_absent(
    openrouter: respx.MockRouter,
) -> None:
    _plan(openrouter, cost=None, prompt_tokens=100, completion_tokens=50)

    _, usage = _call_planner()

    # test/planner is priced 1.0 / 2.0 USD per million tokens in smart_settings.
    assert usage.cost_usd == Decimal("0.0002")
    assert budget.spend_today() == Decimal("0.0002")


def test_chat_json_refuses_to_call_once_the_daily_budget_is_spent(
    openrouter: respx.MockRouter,
) -> None:
    route = _plan(openrouter)
    budget.add_spend(Decimal("5"))

    with pytest.raises(llm.BudgetExhausted):
        _call_planner()

    assert route.call_count == 0


def test_an_exhausted_deadline_skips_the_call(openrouter: respx.MockRouter) -> None:
    route = _plan(openrouter)

    with pytest.raises(llm.LLMTimeout):
        _call_planner(deadline=llm.Deadline(budget_s=0.5))

    assert route.call_count == 0


def test_deadline_counts_down() -> None:
    deadline = llm.Deadline(budget_s=40.0)

    assert 39.0 < deadline.remaining() <= 40.0
    assert not deadline.expired()
    assert llm.Deadline(budget_s=0.0).expired()


# --- embed --------------------------------------------------------------------


def _unit(vector: list[float]) -> float:
    return sum(component * component for component in vector) ** 0.5


def test_embed_requests_dimensions_and_normalises_the_result(
    openrouter: respx.MockRouter,
) -> None:
    long_vectors = [[float(i + 1) for i in range(16)], [1.0] + [0.0] * 15]
    route = openrouter.post("/embeddings").mock(return_value=embedding_response(long_vectors))

    vectors, usage = llm.embed(["الصبر", "الشكر"])

    body = request_json(route.calls.last.request)
    assert body["model"] == "test/embed"
    assert body["input"] == ["الصبر", "الشكر"]
    assert body["dimensions"] == 8
    assert body["encoding_format"] == "float"
    assert body["usage"] == {"include": True}
    assert [len(vector) for vector in vectors] == [8, 8]
    assert all(abs(_unit(vector) - 1.0) < 1e-6 for vector in vectors)
    assert vectors[1][0] == 1.0
    assert usage.cost_usd == Decimal("0.00001")
    assert budget.spend_today() == Decimal("0.00001")


def test_embed_truncates_client_side_when_dimensions_are_rejected(
    openrouter: respx.MockRouter,
) -> None:
    route = openrouter.post("/embeddings").mock(
        side_effect=[
            error_response(400, "dimensions unsupported"),
            embedding_response([[2.0] * 16]),
        ]
    )

    vectors, _ = llm.embed(["الصبر"])

    assert route.call_count == 2
    assert "dimensions" in request_json(route.calls[0].request)
    assert "dimensions" not in request_json(route.calls[1].request)
    assert len(vectors[0]) == 8 and abs(_unit(vectors[0]) - 1.0) < 1e-6


def test_embed_rejects_vectors_that_are_too_short(openrouter: respx.MockRouter) -> None:
    openrouter.post("/embeddings").mock(return_value=embedding_response([[1.0] * 4]))

    with pytest.raises(llm.LLMSchemaError):
        llm.embed(["الصبر"])


def test_embed_rejects_a_vector_count_mismatch(openrouter: respx.MockRouter) -> None:
    openrouter.post("/embeddings").mock(return_value=embedding_response([[1.0] * 8]))

    with pytest.raises(llm.LLMSchemaError):
        llm.embed(["a", "b"])


def test_embed_with_no_texts_makes_no_call(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/embeddings").mock(return_value=embedding_response([]))

    vectors, usage = llm.embed([])

    assert vectors == [] and usage.model == "test/embed"
    assert route.call_count == 0


def test_embed_honours_the_budget_unless_told_otherwise(openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/embeddings").mock(return_value=embedding_response([[1.0] * 8]))
    budget.add_spend(Decimal("5"))

    with pytest.raises(llm.BudgetExhausted):
        llm.embed(["الصبر"])
    assert route.call_count == 0

    vectors, _ = llm.embed(["الصبر"], check_budget=False)
    assert len(vectors) == 1


def test_fit_vector_and_query_format() -> None:
    fitted = llm.fit_vector([3.0, 4.0, 100.0], 2)

    assert fitted == pytest.approx([0.6, 0.8])
    with pytest.raises(llm.LLMSchemaError):
        llm.fit_vector([1.0], 2)
    assert llm.format_query("الصبر").startswith("Instruct: ")
    assert llm.format_query("الصبر").endswith("Query: الصبر")


# --- truncation and failover ----------------------------------------------------


def test_a_truncated_answer_is_reported_as_such(openrouter: respx.MockRouter) -> None:
    """The JSON stops mid-string; the useful fact is the token cap, not the parse error."""
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion(
            '{"intent": "opinion", "topic_ar": "الصب',
            model="test/planner",
            completion_tokens=799,
            finish_reason="length",
        )
    )

    with pytest.raises(llm.LLMTruncated) as caught:
        _call_planner(max_tokens=800)

    message = str(caught.value)
    assert "max_tokens" in message and "799/800" in message
    # Callers that catch the general schema error still catch this.
    assert isinstance(caught.value, llm.LLMSchemaError)


def test_a_truncated_answer_with_no_content_is_still_a_truncation(
    openrouter: respx.MockRouter,
) -> None:
    """Reasoning can eat the whole budget, leaving nothing — not "no content"."""
    openrouter.post("/chat/completions").mock(
        return_value=chat_completion("", model="test/planner", finish_reason="length")
    )

    with pytest.raises(llm.LLMTruncated):
        _call_planner()


def test_fallback_models_are_offered_to_the_router(openrouter: respx.MockRouter) -> None:
    route = _plan(openrouter)

    _call_planner(fallback_models=["test/second", "test/third"])

    body = request_json(route.calls.last.request)
    assert body["models"] == ["test/planner", "test/second", "test/third"]


def test_no_fallback_models_means_no_models_key(openrouter: respx.MockRouter) -> None:
    route = _plan(openrouter)

    _call_planner()

    assert "models" not in request_json(route.calls.last.request)

