"""The ASS karaoke file: timing arithmetic, line breaks, presets, attribution.

No database and no ffmpeg here — :mod:`clips.subtitles` is a pure function, and
the properties that matter (a line's ``\\k`` values add up to the line, a word
owns its trailing gap, the words are written in the order libass will lay out
right-to-left) are exactly the kind that a rendered mp4 cannot prove.

Word order deserves its own warning: a line is written **last word first**, so
every assertion about position below is intentional, not a mistake. The module
docstring of :mod:`clips.subtitles` explains why.
"""

from __future__ import annotations

import re

import pytest

from clips.subtitles import (
    ATTRIBUTION_STYLE,
    KARAOKE_STYLE,
    MAX_LINE_CHARS,
    PRESETS,
    ass_colour,
    build_ass,
)

ATTRIBUTION = 'أرشيف الشعراوي · shaarawy.archive'

# One word per second, spoken for 800ms of it.
WORDS = [(f'w{index}', index * 1000, index * 1000 + 800) for index in range(10)]


def _timestamp_cs(value: str) -> int:
    hours, minutes, seconds = value.split(':')
    whole, hundredths = seconds.split('.')
    return ((int(hours) * 60 + int(minutes)) * 60 + int(whole)) * 100 + int(hundredths)


def _dialogues(ass: str, style: str) -> list[tuple[int, int, str]]:
    """``(start_cs, end_cs, text)`` of every Dialogue in ``style``, in file order."""
    found = []
    for line in ass.splitlines():
        if not line.startswith('Dialogue:'):
            continue
        fields = line[len('Dialogue:') :].split(',', 9)
        if fields[3].strip() != style:
            continue
        found.append(
            (_timestamp_cs(fields[1].strip()), _timestamp_cs(fields[2].strip()), fields[9])
        )
    return found


def _karaoke(text: str) -> list[tuple[int, int]]:
    """``(start_cs, duration_cs)`` per word, in reading order (the file is reversed)."""
    found = [
        (int(start), int(duration))
        for start, duration in re.findall(r'\{\\kt(\d+)\\k(\d+)\}', text)
    ]
    return found[::-1]


def _durations(text: str) -> list[int]:
    return [duration for _, duration in _karaoke(text)]


def _words(text: str) -> list[str]:
    """The word texts of a karaoke line, in reading order."""
    return re.findall(r'\{[^}]*\}([^{ ]*)', text)[::-1]


def _build(words: list[tuple[str, int, int]] = WORDS, **overrides: object) -> str:
    kwargs: dict = {
        'clip_start_ms': 0,
        'clip_end_ms': 20_000,
        'preset': 'night',
        'attribution': ATTRIBUTION,
    }
    kwargs.update(overrides)
    return build_ass(words, **kwargs)  # type: ignore[arg-type]


# --- header ------------------------------------------------------------------


def test_the_header_declares_a_1080x1920_v4_script() -> None:
    ass = _build()

    assert ass.startswith('[Script Info]')
    assert 'ScriptType: v4.00+' in ass
    assert 'PlayResX: 1080' in ass
    assert 'PlayResY: 1920' in ass
    assert '[V4+ Styles]' in ass and '[Events]' in ass
    # Every section that carries rows declares its column order first.
    assert ass.count('Format: ') == 2


def test_every_dialogue_uses_a_style_the_file_defines() -> None:
    ass = _build()

    defined = {
        line.split(',')[0][len('Style: ') :]
        for line in ass.splitlines()
        if line.startswith('Style: ')
    }
    used = {
        line[len('Dialogue:') :].split(',', 9)[3].strip()
        for line in ass.splitlines()
        if line.startswith('Dialogue:')
    }

    assert defined == {KARAOKE_STYLE, ATTRIBUTION_STYLE}
    assert used <= defined


# --- karaoke timing ----------------------------------------------------------


def test_a_lines_karaoke_values_sum_to_its_span() -> None:
    """The invariant the whole module is built around: no drift from rounding."""
    ass = _build()

    lines = _dialogues(ass, KARAOKE_STYLE)
    assert lines
    for start_cs, end_cs, text in lines:
        assert sum(_durations(text)) == end_cs - start_cs


def test_a_word_carries_the_silence_that_follows_it() -> None:
    """800ms spoken + 200ms of rest is one 100cs highlight, not 80 and a gap."""
    ass = _build()

    first_line = _dialogues(ass, KARAOKE_STYLE)[0]

    assert _durations(first_line[2])[:5] == [100, 100, 100, 100, 100]


def test_the_last_word_of_a_line_stops_when_it_stops() -> None:
    ass = _build(WORDS[:3])

    (start_cs, end_cs, text), *rest = _dialogues(ass, KARAOKE_STYLE)

    assert not rest
    assert (start_cs, end_cs) == (0, 280)  # 0s .. 2.8s
    assert _durations(text) == [100, 100, 80]


def test_each_word_carries_its_own_offset_into_the_line() -> None:
    """``\\kt`` is what survives writing the words backwards."""
    ass = _build(WORDS[:3])

    assert _karaoke(_dialogues(ass, KARAOKE_STYLE)[0][2]) == [(0, 100), (100, 100), (200, 80)]


def test_a_line_is_written_last_word_first() -> None:
    """Reversed on purpose: libass lays karaoke runs out left-to-right, so this
    is the order that reads right-to-left on screen."""
    ass = _build(WORDS[:3])

    assert (
        _dialogues(ass, KARAOKE_STYLE)[0][2]
        == r'{\kt200\k80}w2 {\kt100\k100}w1 {\kt0\k100}w0'
    )


# --- line grouping -----------------------------------------------------------


def test_lines_hold_at_most_six_words() -> None:
    ass = _build()

    lengths = [len(_karaoke(text)) for _, _, text in _dialogues(ass, KARAOKE_STYLE)]

    assert lengths == [6, 4]


def test_a_line_breaks_before_it_grows_too_wide_to_fit_a_row() -> None:
    """Six long words would wrap, and a wrapped line loses its word order."""
    words = [(f'المستقيم{index}', index * 1_000, index * 1_000 + 800) for index in range(6)]

    lines = _dialogues(_build(words), KARAOKE_STYLE)

    # Nine characters a word: three per line would already overflow the row.
    assert [len(_karaoke(text)) for _, _, text in lines] == [2, 2, 2]
    for _, _, text in lines:
        assert len(' '.join(_words(text))) <= MAX_LINE_CHARS


def test_a_long_pause_starts_a_new_line() -> None:
    words = [('a', 0, 500), ('b', 600, 1_000), ('c', 3_000, 3_500)]

    ass = _build(words)

    lines = _dialogues(ass, KARAOKE_STYLE)
    assert [len(_karaoke(text)) for _, _, text in lines] == [2, 1]
    assert (lines[1][0], lines[1][1]) == (300, 350)


def test_a_short_pause_does_not() -> None:
    words = [('a', 0, 500), ('b', 1_200, 1_600)]

    assert len(_dialogues(_build(words), KARAOKE_STYLE)) == 1


# --- clip window -------------------------------------------------------------


def test_words_are_shifted_onto_the_clips_own_timeline() -> None:
    words = [('a', 12_000, 12_800), ('b', 13_000, 13_800)]

    ass = _build(words, clip_start_ms=12_000, clip_end_ms=32_000)

    assert _dialogues(ass, KARAOKE_STYLE)[0][:2] == (0, 180)


def test_words_outside_the_window_are_dropped_and_the_edges_clamped() -> None:
    words = [('before', 0, 4_000), ('edge', 4_500, 5_500), ('inside', 6_000, 6_800)]

    ass = _build(words, clip_start_ms=5_000, clip_end_ms=25_000)

    line = _dialogues(ass, KARAOKE_STYLE)[0]
    assert _words(line[2]) == ['edge', 'inside']
    # The straddling word keeps only the half that is in the clip.
    assert line[0] == 0
    assert _durations(line[2]) == [100, 80]


def test_a_clip_with_no_words_is_still_a_valid_card() -> None:
    ass = _build([])

    assert not _dialogues(ass, KARAOKE_STYLE)
    assert len(_dialogues(ass, ATTRIBUTION_STYLE)) == 1


# --- attribution -------------------------------------------------------------


def test_the_attribution_holds_for_the_whole_clip() -> None:
    ass = _build(clip_start_ms=5_000, clip_end_ms=25_000)

    (start_cs, end_cs, text), *rest = _dialogues(ass, ATTRIBUTION_STYLE)

    assert not rest
    assert (start_cs, end_cs) == (0, 2_000)
    assert text == ATTRIBUTION


def test_braces_and_backslashes_cannot_smuggle_in_ass_tags() -> None:
    ass = _build([(r'{\fs200}boom', 0, 800)])

    assert r'{\fs200}' not in ass
    assert '(fs200)boom' in ass


# --- presets -----------------------------------------------------------------


def test_ass_colours_are_byte_reversed_with_alpha_first() -> None:
    assert ass_colour('#1a6b4a') == '&H004A6B1A'
    assert ass_colour('#ffffff') == '&H00FFFFFF'


def test_a_bad_colour_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        ass_colour('#fff')


@pytest.mark.parametrize('preset', sorted(PRESETS))
def test_every_preset_paints_the_spoken_word_differently_from_the_rest(preset: str) -> None:
    ass = _build(preset=preset)

    style = next(
        line for line in ass.splitlines() if line.startswith(f'Style: {KARAOKE_STYLE},')
    )
    primary, secondary = style.split(',')[3:5]

    assert primary == ass_colour(PRESETS[preset].spoken)
    assert secondary == ass_colour(PRESETS[preset].pending)
    assert primary != secondary


def test_the_three_presets_are_three_different_looks() -> None:
    palettes = {
        preset: (
            PRESETS[preset].background,
            PRESETS[preset].spoken,
            PRESETS[preset].pending,
        )
        for preset in PRESETS
    }

    assert sorted(palettes) == ['classic', 'light', 'night']
    assert len(set(palettes.values())) == 3


def test_an_unknown_preset_is_rejected() -> None:
    with pytest.raises(ValueError, match='unknown preset'):
        _build(preset='neon')


def test_a_clip_must_have_length() -> None:
    with pytest.raises(ValueError, match='positive length'):
        _build(clip_start_ms=5_000, clip_end_ms=5_000)
