"""Stub engine behaviour: determinism, sidecars, and backend selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.chunking import WordSpan, plan_chunks
from pipeline.engines import (
    WORD_GAP_MS,
    CTCAligner,
    FasterWhisperASR,
    StubAligner,
    StubASR,
    get_aligner,
    get_asr_engine,
)

from .conftest import synthesize_audio

DURATION_MS = 30_000


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    return synthesize_audio(tmp_path / "s002e01.mp3", seconds=30)


def test_stub_words_fill_the_duration_with_even_gaps(audio_file: Path) -> None:
    words = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)

    assert len(words) == DURATION_MS // 600
    assert all(isinstance(word.start_ms, int) and isinstance(word.end_ms, int) for word in words)
    assert words[0].start_ms == 0
    assert words[-1].end_ms <= DURATION_MS
    assert all(
        later.start_ms - earlier.end_ms == WORD_GAP_MS
        for earlier, later in zip(words, words[1:], strict=False)
    )


def test_the_stub_is_deterministic_per_file(audio_file: Path, tmp_path: Path) -> None:
    first = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)
    again = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)
    assert [word.text for word in first] == [word.text for word in again]

    other = synthesize_audio(tmp_path / "s002e02.mp3", seconds=30, frequency=523)
    different = StubASR().transcribe(str(other), duration_ms=DURATION_MS)
    assert [word.text for word in different] != [word.text for word in first]


def test_a_text_sidecar_becomes_the_transcript(audio_file: Path) -> None:
    audio_file.with_suffix(".mp3.txt").write_text("قال الشيخ رحمه الله", encoding="utf-8")

    words = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)

    assert [word.text for word in words] == ["قال", "الشيخ", "رحمه", "الله"]
    assert words[0].start_ms == 0
    assert words[-1].end_ms <= DURATION_MS


def test_a_timing_sidecar_is_honoured_verbatim(audio_file: Path) -> None:
    """This is how a test crafts a pause pattern for the chunker."""
    crafted = [
        {"text": "أ", "start_ms": 0, "end_ms": 21_000},
        {"text": "ب", "start_ms": 23_000, "end_ms": 30_000},  # 2s pause after 21s
    ]
    audio_file.with_suffix(".mp3.timing.json").write_text(
        json.dumps(crafted, ensure_ascii=False), encoding="utf-8"
    )

    words = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)

    assert [(word.text, word.start_ms, word.end_ms) for word in words] == [
        ("أ", 0, 21_000),
        ("ب", 23_000, 30_000),
    ]
    spans = [WordSpan(word.text, word.start_ms, word.end_ms) for word in words]
    assert len(plan_chunks(spans, kind="khawatir", ayah_starts=None)) == 2


def test_the_stub_aligner_passes_timings_through(audio_file: Path) -> None:
    words = StubASR().transcribe(str(audio_file), duration_ms=DURATION_MS)

    aligned = StubAligner().align(str(audio_file), "ignored", words, duration_ms=DURATION_MS)

    assert [(word.text, word.start_ms, word.end_ms) for word in aligned] == [
        (word.text, word.start_ms, word.end_ms) for word in words
    ]


def test_the_stub_aligner_refuses_to_invent_timings(audio_file: Path) -> None:
    with pytest.raises(ValueError, match="needs the ASR words"):
        StubAligner().align(str(audio_file), "text", None, duration_ms=DURATION_MS)


def test_engine_selection_follows_the_asr_backend_setting(settings) -> None:  # noqa: ANN001
    settings.ASR_BACKEND = "stub"
    assert isinstance(get_asr_engine(), StubASR)
    assert isinstance(get_aligner(), StubAligner)

    # Constructing the real engines must not import torch — only calling them does.
    settings.ASR_BACKEND = "faster-whisper"
    assert isinstance(get_asr_engine(), FasterWhisperASR)
    assert isinstance(get_aligner(), CTCAligner)

    settings.ASR_BACKEND = "wav2vec-from-the-attic"
    with pytest.raises(ValueError, match="Unknown ASR_BACKEND"):
        get_asr_engine()
    with pytest.raises(ValueError, match="Unknown ASR_BACKEND"):
        get_aligner()
