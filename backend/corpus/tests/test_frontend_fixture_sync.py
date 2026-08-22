"""The frontend's copy of the normalization fixture must never drift.

``frontend/src/lib/arabic.ts`` is a TS port of ``corpus.arabic`` (the verse
page matches ayah text against ASR words client-side, and rule 2 forbids raw
Arabic comparison). Its test suite runs the same ``normalization_pairs.json``
this suite runs — but only if the two copies are actually the same file. This
test pins that invariant at the byte level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_BACKEND_FIXTURE = Path(__file__).parent / "fixtures" / "normalization_pairs.json"
_FRONTEND_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "__fixtures__"
    / "normalization_pairs.json"
)


def test_frontend_fixture_is_byte_identical() -> None:
    if not _FRONTEND_FIXTURE.exists():
        # The backend image ships without the frontend tree; the check only
        # means something in a full checkout.
        pytest.skip("frontend tree not present")
    assert _FRONTEND_FIXTURE.read_bytes() == _BACKEND_FIXTURE.read_bytes(), (
        "frontend/src/lib/__fixtures__/normalization_pairs.json has drifted "
        "from backend/corpus/tests/fixtures/normalization_pairs.json — "
        "re-copy the backend fixture and re-run the frontend arabic.test.ts"
    )
