"""Tests for :mod:`corpus.arabic`.

The bulk of the coverage is data-driven: ``fixtures/normalization_pairs.json``
holds input/expected pairs derived by hand from the spec in
``SHAARAWY_PROJECT_PLAN.md``. Never regenerate that file from the
implementation — the whole point is that it is an independent statement of what
the spec says.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from corpus.arabic import normalize_for_index, normalize_light

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "normalization_pairs.json"


def _load_pairs() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        pairs: list[dict[str, Any]] = json.load(fh)
    return pairs


PAIRS = _load_pairs()
PAIR_IDS = [f"{i:02d}-{pair.get('note', '')[:60]}" for i, pair in enumerate(PAIRS)]


def test_fixture_has_enough_pairs() -> None:
    assert len(PAIRS) >= 50, f"expected at least 50 fixture pairs, got {len(PAIRS)}"


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_normalize_light_matches_fixture(pair: dict[str, Any]) -> None:
    assert normalize_light(pair["input"]) == pair["light"]


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_normalize_for_index_matches_fixture(pair: dict[str, Any]) -> None:
    assert normalize_for_index(pair["input"]) == pair["index"]


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_normalize_light_is_idempotent(pair: dict[str, Any]) -> None:
    once = normalize_light(pair["input"])
    assert normalize_light(once) == once


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_normalize_for_index_is_idempotent(pair: dict[str, Any]) -> None:
    once = normalize_for_index(pair["input"])
    assert normalize_for_index(once) == once


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_index_absorbs_light(pair: dict[str, Any]) -> None:
    """normalize_for_index subsumes normalize_light, so composing them is a no-op."""
    assert normalize_for_index(normalize_light(pair["input"])) == normalize_for_index(
        pair["input"]
    )


def test_index_output_has_no_double_spaces() -> None:
    for pair in PAIRS:
        out = normalize_for_index(pair["input"])
        assert "  " not in out
        assert out == out.strip()


def test_light_preserves_letter_identity() -> None:
    """normalize_light must not fold letters — that is index-only behaviour."""
    for letter in "آأإٱٲٳةىؤئ":
        assert normalize_light(letter) == letter


def test_light_preserves_whitespace_layout() -> None:
    assert normalize_light("  a\t\nb  ") == "  a\t\nb  "
