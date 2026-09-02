"""Offline evaluation of smart search against a hand-labelled golden set.

``golden.jsonl`` holds one object per line::

    {"id": "g001", "question": "…", "expected_segment_ids": [123, 456],
     "expected_status": "answered", "tags": ["opinion"], "notes": "…"}

An item with no ``expected_segment_ids`` must expect ``not_found`` (an
abstention case) and is skipped by the retrieval stage. Reports are written
as JSON with ids and numbers only, so they diff cleanly under
``docs/smart-search/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["GOLDEN_PATH", "STATUSES", "GoldenItem", "load_golden"]

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"
STATUSES = frozenset({"answered", "partial", "not_found"})


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    expected_segment_ids: tuple[int, ...]
    expected_status: str
    tags: tuple[str, ...] = ()
    notes: str = ""

    @property
    def labelled(self) -> bool:
        return bool(self.expected_segment_ids)


class GoldenError(ValueError):
    """The golden file is malformed."""


def load_golden(path: Path | str = GOLDEN_PATH) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            raise GoldenError(f"line {line_number}: not JSON ({error})") from error
        item_id = str(data.get("id", "")).strip()
        question = str(data.get("question", "")).strip()
        status = str(data.get("expected_status", "")).strip()
        ids = tuple(int(value) for value in data.get("expected_segment_ids", []))
        if not item_id or item_id in seen:
            raise GoldenError(f"line {line_number}: missing or duplicate id {item_id!r}")
        if not question:
            raise GoldenError(f"line {line_number}: {item_id} has no question")
        if status not in STATUSES:
            raise GoldenError(f"line {line_number}: {item_id} has status {status!r}")
        if not ids and status != "not_found":
            raise GoldenError(
                f"line {line_number}: {item_id} expects {status} but names no segments"
            )
        seen.add(item_id)
        items.append(
            GoldenItem(
                id=item_id,
                question=question,
                expected_segment_ids=ids,
                expected_status=status,
                tags=tuple(str(tag) for tag in data.get("tags", [])),
                notes=str(data.get("notes", "")),
            )
        )
    return items


__all__ += ["GoldenError"]


@dataclass
class RetrievalResult:
    """One golden item through the retrieval stage."""

    id: str
    ranked_segment_ids: list[int] = field(default_factory=list)
    hit_rank: int | None = None
    retrieval_hit_rank: int | None = None
    """Where retrieval alone placed the segment (equals ``hit_rank`` for that stage)."""
    weak_evidence: bool = False
    latency_ms: int = 0
    cost_usd: str = "0"
    error: str = ""


__all__ += ["RetrievalResult"]
