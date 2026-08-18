"""Chunk planning rules: pause boundaries, the hard cap, and ayah integrity."""

from __future__ import annotations

import pytest

from pipeline.chunking import GAP_MS, MAX_MS, MIN_MS, ChunkSpan, WordSpan, plan_chunks

WORD_MS = 500
NORMAL_GAP_MS = 100


def build_words(
    count: int, *, gaps: dict[int, int] | None = None, word_ms: int = WORD_MS
) -> list[WordSpan]:
    """``count`` words of ``word_ms``, separated by 100ms unless ``gaps`` says otherwise.

    ``gaps[i]`` is the silence *after* word ``i``.
    """
    gaps = gaps or {}
    words: list[WordSpan] = []
    cursor = 0
    for index in range(count):
        words.append(WordSpan(text=f"w{index}", start_ms=cursor, end_ms=cursor + word_ms))
        cursor += word_ms + gaps.get(index, NORMAL_GAP_MS)
    return words


def covers_every_word_once(chunks: list[ChunkSpan], words: list[WordSpan]) -> bool:
    if not chunks:
        return not words
    if chunks[0].start_index != 0 or chunks[-1].end_index != len(words):
        return False
    return all(
        left.end_index == right.start_index for left, right in zip(chunks, chunks[1:], strict=False)
    )


def test_no_words_no_chunks() -> None:
    assert plan_chunks([], kind="khawatir", ayah_starts=None) == []


def test_a_short_recording_is_a_single_chunk() -> None:
    words = build_words(10)
    chunks = plan_chunks(words, kind="khawatir", ayah_starts=None)

    assert len(chunks) == 1
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == len(words)
    assert chunks[0].start_ms == words[0].start_ms
    assert chunks[0].end_ms == words[-1].end_ms


def test_splits_on_a_long_pause_once_the_minimum_is_covered() -> None:
    # word i ends at i*600+500, so the chunk covers 20s from word 33 onwards.
    words = build_words(60, gaps={33: 1200})
    chunks = plan_chunks(words, kind="khawatir", ayah_starts=None)

    assert [(chunk.start_index, chunk.end_index) for chunk in chunks] == [(0, 34), (34, 60)]
    assert chunks[0].duration_ms >= MIN_MS
    assert covers_every_word_once(chunks, words)


def test_does_not_split_on_a_long_pause_before_the_minimum() -> None:
    # The pause after word 10 is well past the gap threshold but the chunk is
    # only 6.5s old, so it must be ignored.
    words = build_words(30, gaps={10: 5000})
    chunks = plan_chunks(words, kind="khawatir", ayah_starts=None)

    assert len(chunks) == 1
    assert chunks[0].end_index == 30


def test_a_pause_at_the_threshold_is_not_long_enough() -> None:
    exactly_at_threshold = build_words(60, gaps={33: GAP_MS})
    just_over = build_words(60, gaps={33: GAP_MS + 1})

    assert len(plan_chunks(exactly_at_threshold, kind="khawatir", ayah_starts=None)) == 1
    assert len(plan_chunks(just_over, kind="khawatir", ayah_starts=None)) == 2


def test_hard_cap_splits_a_gapless_recording() -> None:
    words = build_words(200)  # ~2 minutes, never a pause over 100ms
    chunks = plan_chunks(words, kind="khawatir", ayah_starts=None)

    assert len(chunks) > 1
    # word 75 ends at 45500, the first moment the chunk reaches the cap.
    assert chunks[0].end_index == 76
    assert all(chunk.duration_ms <= MAX_MS + WORD_MS for chunk in chunks)
    assert covers_every_word_once(chunks, words)


def test_recitation_only_splits_where_an_ayah_starts() -> None:
    # Pauses land at 33 and 70; the ayat begin at 0, 40 and 80.
    words = build_words(120, gaps={33: 1200, 70: 1200})
    ayah_starts = [0, 40, 80]

    chunks = plan_chunks(words, kind="recitation", ayah_starts=ayah_starts)

    boundaries = {chunk.start_index for chunk in chunks}
    assert boundaries <= set(ayah_starts)
    assert all(chunk.end_index in set(ayah_starts) | {len(words)} for chunk in chunks)
    assert covers_every_word_once(chunks, words)


def test_the_same_words_as_khawatir_do_split_at_the_pause() -> None:
    """Control for the previous test: the restriction is what moved the edge."""
    words = build_words(120, gaps={33: 1200, 70: 1200})

    unrestricted = plan_chunks(words, kind="khawatir", ayah_starts=None)

    assert [chunk.start_index for chunk in unrestricted][:2] == [0, 34]


def test_a_long_ayah_may_exceed_the_hard_cap() -> None:
    # One 100-word ayah (60s) followed by a second one: never cut mid-ayah,
    # even though the cap is 45s.
    words = build_words(140)
    chunks = plan_chunks(words, kind="recitation", ayah_starts=[0, 100])

    assert [(chunk.start_index, chunk.end_index) for chunk in chunks] == [(0, 100), (100, 140)]
    assert chunks[0].duration_ms > MAX_MS


def test_recitation_without_known_ayah_starts_uses_the_normal_rules() -> None:
    words = build_words(60, gaps={33: 1200})

    chunks = plan_chunks(words, kind="recitation", ayah_starts=None)

    assert [(chunk.start_index, chunk.end_index) for chunk in chunks] == [(0, 34), (34, 60)]


@pytest.mark.parametrize("kind", ["khawatir", "recitation"])
def test_spans_are_contiguous_integer_milliseconds(kind: str) -> None:
    words = build_words(300, gaps={40: 900, 120: 700, 260: 5000})
    chunks = plan_chunks(
        words, kind=kind, ayah_starts=[0, 60, 130, 200, 280] if kind == "recitation" else None
    )

    assert covers_every_word_once(chunks, words)
    for chunk in chunks:
        assert isinstance(chunk.start_ms, int)
        assert isinstance(chunk.end_ms, int)
        assert isinstance(chunk.start_index, int)
        assert isinstance(chunk.end_index, int)
        assert chunk.end_ms > chunk.start_ms
        assert chunk.start_ms == words[chunk.start_index].start_ms
        assert chunk.end_ms == words[chunk.end_index - 1].end_ms


def test_thresholds_are_configurable() -> None:
    words = build_words(20, gaps={5: 1000})

    chunks = plan_chunks(words, kind="khawatir", ayah_starts=None, min_ms=1_000, max_ms=10_000)

    assert len(chunks) > 1
