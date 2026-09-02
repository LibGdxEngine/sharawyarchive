"""Canned OpenRouter responses for respx-mocked tests — never a real call."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel

__all__ = [
    "chat_completion",
    "embedding_response",
    "error_response",
    "request_json",
    "stub_vector",
]


def chat_completion(
    payload: BaseModel | dict[str, Any] | str,
    *,
    model: str = "test/model",
    cost: float | None = 0.001,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> httpx.Response:
    """A ``chat.completion`` whose assistant message is ``payload`` as JSON text."""
    if isinstance(payload, BaseModel):
        content = payload.model_dump_json()
    elif isinstance(payload, str):
        content = payload
    else:
        content = json.dumps(payload, ensure_ascii=False)
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cost is not None:
        usage["cost"] = cost
    return httpx.Response(
        200,
        json={
            "id": "gen-test",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        },
    )


def embedding_response(
    vectors: Sequence[Sequence[float]],
    *,
    model: str = "test/embed",
    cost: float | None = 0.00001,
    prompt_tokens: int = 10,
) -> httpx.Response:
    usage: dict[str, Any] = {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens}
    if cost is not None:
        usage["cost"] = cost
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": model,
            "data": [
                {"object": "embedding", "index": index, "embedding": [float(x) for x in vector]}
                for index, vector in enumerate(vectors)
            ],
            "usage": usage,
        },
    )


def error_response(status: int, message: str = "error") -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "code": status}})


def stub_vector(text: str, dimensions: int) -> list[float]:
    """A deterministic unit vector seeded by ``text`` (the old StubEmbedder idea)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(digest[index % len(digest)] / 255.0) * 2.0 - 1.0 for index in range(dimensions)]
    norm = math.sqrt(sum(component * component for component in raw)) or 1.0
    return [component / norm for component in raw]


def request_json(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)
