"""ASS subtitle generation for clip cards: per-word karaoke over a 1080x1920 card.

A clip is a still colour field with the segment's audio and its machine
transcript sweeping across the middle of the frame, one word lighting up as it
is spoken. That sweep is ASS karaoke: every word carries a ``{\\k<cs>}`` tag
holding its duration in **centiseconds**, and libass repaints it from
``SecondaryColour`` (not yet spoken) to ``PrimaryColour`` (spoken) as the tag
elapses. (Arabic needs one twist on top of that — see the RTL note below.)

Two properties are load-bearing and both fall out of quantising every timestamp
to centiseconds exactly once (:func:`_cs`):

* the ``\\k`` values of a line sum to the line's own on-screen span, because both
  are differences of the same absolute centisecond positions;
* a word's ``\\k`` covers its trailing silence up to the next word, so the
  highlight never sits on empty air mid-line.

Nothing here touches ffmpeg, the database or the network — it is a pure
function, which is why the interesting cases are unit-tested rather than
ffprobed.

**RTL, and why the words come out backwards.** libass runs the bidi algorithm
over a *run* of text, and an override block starts a new run — so a line of
plain Arabic reorders correctly, but the moment every word carries its own
``{\\k}`` tag each word becomes its own run and the runs are laid out
left-to-right. The words are individually shaped and joined in exactly the
wrong order, which for Arabic is not a cosmetic problem: it is the sentence
read backwards. Verified frame by frame against ffmpeg 6.1 / libass 0.17;
neither ``Encoding: 178`` nor RLE/RLM control characters change it.

So the file emits each line's words **in reverse**, which puts the first word
on the right where a reader starts, and detaches the karaoke clock from that
order with ``\\kt`` (absolute karaoke start, in centiseconds) so the highlight
still sweeps right-to-left in reading order. The consequence to respect when
touching this file: a line that wraps would place its later half above its
earlier half, which is why :data:`MAX_LINE_CHARS` keeps a line inside one row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

PLAY_RES_X = 1080
PLAY_RES_Y = 1920
"""Vertical social video. Everything else in this module is sized against it."""

MAX_WORDS_PER_LINE = 6
LINE_BREAK_GAP_MS = 800
"""A line holds at most six words, and a pause longer than this starts a new
one — the pause is where the speaker breathes, so it is where the reader does."""

FONT_SIZE = 96
MAX_LINE_CHARS = 28
"""Measured, not guessed: at :data:`FONT_SIZE` inside the style's margins,
28 characters of Naskh is the widest line libass renders without wrapping, and
a wrapped line loses the word order (see the module docstring)."""

FONT_NAME = 'Noto Naskh Arabic'
"""Requested, never required: fontconfig substitutes another Arabic face (Noto
Sans/Kufi Arabic on a stock Ubuntu) when Naskh is absent. A missing font must
never fail a render."""

KARAOKE_STYLE = 'Karaoke'
ATTRIBUTION_STYLE = 'Attribution'


@dataclass(frozen=True)
class Preset:
    """One visual treatment of a clip card.

    Colours are ``#rrggbb`` here and converted to ASS's ``&HAABBGGRR`` on the
    way out. ``background`` never reaches the subtitle file: it is the colour
    ffmpeg paints the canvas with (:mod:`clips.rendering`).
    """

    name: str
    background: str
    """Canvas colour, handed to ffmpeg's ``color=`` source."""
    spoken: str
    """``PrimaryColour`` — a word the karaoke sweep has reached."""
    pending: str
    """``SecondaryColour`` — a word it has not reached yet."""
    outline: str
    shadow: str
    attribution: str


PRESETS: dict[str, Preset] = {
    # Warm dark ground, amber highlight: the "lantern" reading of the archive.
    'classic': Preset(
        name='classic',
        background='#1a1714',
        spoken='#e0a458',
        pending='#f0e6d6',
        outline='#0d0b09',
        shadow='#000000',
        attribution='#b3a99a',
    ),
    # Near-black ground with the project accent. DESIGN.md carries the accent in
    # two forms — #1a6b4a on light, #3aad7a on dark — and this card is dark, so
    # the highlight is the dark form of the same green.
    'night': Preset(
        name='night',
        background='#101312',
        spoken='#3aad7a',
        pending='#f0ede8',
        outline='#05100b',
        shadow='#000000',
        attribution='#a8a49d',
    ),
    # Paper white and ink, with the light-mode accent for the sweep.
    'light': Preset(
        name='light',
        background='#fafaf9',
        spoken='#1a6b4a',
        pending='#141412',
        outline='#ffffff',
        shadow='#e4e3de',
        attribution='#5c5b57',
    ),
}


class _Word(NamedTuple):
    text: str
    start_cs: int
    end_cs: int


def ass_colour(hex_rgb: str) -> str:
    """``#rrggbb`` -> ``&HAABBGGRR``: ASS stores colours byte-reversed, alpha first.

    Alpha is inverted from the usual sense as well (``00`` is opaque), and
    everything on a clip card is opaque.
    """
    value = hex_rgb.lstrip('#')
    if len(value) != 6:
        raise ValueError(f'expected #rrggbb, got {hex_rgb!r}')
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f'&H00{blue}{green}{red}'.upper()


def _cs(ms: int) -> int:
    """Milliseconds to centiseconds — the only place rounding happens."""
    return (ms + 5) // 10


def _timestamp(centiseconds: int) -> str:
    """ASS wants ``h:mm:ss.cc``, single-digit hour, no padding beyond that."""
    hundredths = centiseconds % 100
    seconds = centiseconds // 100
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}.{hundredths:02d}'


def _escape(text: str) -> str:
    """Neutralise the three characters that would otherwise be ASS syntax."""
    return (
        text.replace('\\', '')
        .replace('{', '(')
        .replace('}', ')')
        .replace('\n', ' ')
        .replace('\r', ' ')
        .strip()
    )


def _clip_words(
    words: list[tuple[str, int, int]], *, clip_start_ms: int, span_ms: int
) -> list[_Word]:
    """Shift absolute word timings onto the clip's own timeline and clamp them.

    Words are only ever *partly* inside a clip at its two edges; those keep the
    part that is inside. Anything that survives with no duration, or with no
    text, is dropped — an empty ``\\k`` group would be a lie about the audio.
    """
    kept: list[_Word] = []
    for text, start_ms, end_ms in words:
        cleaned = _escape(text)
        if not cleaned:
            continue
        start = max(0, min(span_ms, start_ms - clip_start_ms))
        end = max(0, min(span_ms, end_ms - clip_start_ms))
        start_cs, end_cs = _cs(start), _cs(end)
        if end_cs <= start_cs:
            continue
        kept.append(_Word(cleaned, start_cs, end_cs))
    kept.sort(key=lambda word: (word.start_cs, word.end_cs))
    return kept


def _group_lines(words: list[_Word]) -> list[list[_Word]]:
    """Break the word stream into subtitle lines.

    Three reasons to break, in the order they are cheap to check: the line is
    six words long, the line is about to get too wide to fit one row, or the
    speaker paused.
    """
    lines: list[list[_Word]] = []
    current: list[_Word] = []
    width = 0
    gap_cs = _cs(LINE_BREAK_GAP_MS)
    for word in words:
        grown = width + len(word.text) + (1 if current else 0)
        too_many = len(current) >= MAX_WORDS_PER_LINE
        too_wide = bool(current) and grown > MAX_LINE_CHARS
        after_pause = bool(current) and word.start_cs - current[-1].end_cs > gap_cs
        if too_many or too_wide or after_pause:
            lines.append(current)
            current = []
            grown = len(word.text)
        current.append(word)
        width = grown
    if current:
        lines.append(current)
    return lines


def _karaoke_text(line: list[_Word]) -> str:
    """``{\\kt100\\k48}word {\\kt0\\k37}word`` — last word first, each on its own clock.

    ``\\k`` is the word's span *plus* its trailing gap, as differences between
    absolute centisecond positions, so the values sum to exactly the Dialogue
    line's duration however the milliseconds rounded. ``\\kt`` is that word's
    start offset within the line, which is what lets the words be written in
    reverse (the only way libass lays Arabic karaoke out right-to-left) without
    the highlight running backwards with them.
    """
    boundaries = [word.start_cs for word in line] + [line[-1].end_cs]
    parts = [
        f'{{\\kt{boundaries[index] - boundaries[0]}'
        f'\\k{boundaries[index + 1] - boundaries[index]}}}{word.text}'
        for index, word in reversed(list(enumerate(line)))
    ]
    return ' '.join(parts)


def _header(preset: Preset) -> str:
    karaoke = ','.join(
        [
            KARAOKE_STYLE,
            FONT_NAME,
            str(FONT_SIZE),
            ass_colour(preset.spoken),
            ass_colour(preset.pending),
            ass_colour(preset.outline),
            ass_colour(preset.shadow),
            '-1',  # bold
            '0,0,0',  # italic, underline, strikeout
            '100,100',  # scale x, y
            '0',  # spacing
            '0',  # angle
            '1',  # border style: outline + drop shadow
            '4',  # outline width
            '0',  # shadow depth
            '5',  # alignment: middle centre
            '140,140',  # margin l, r
            '160',  # margin v
            '1',  # encoding: default, libass shapes Arabic regardless
        ]
    )
    attribution = ','.join(
        [
            ATTRIBUTION_STYLE,
            FONT_NAME,
            '44',
            ass_colour(preset.attribution),
            ass_colour(preset.attribution),
            ass_colour(preset.outline),
            ass_colour(preset.shadow),
            '0,0,0,0',
            '100,100',
            '0',
            '0',
            '1',
            '2',
            '0',
            '2',  # alignment: bottom centre
            '100,100',
            '90',
            '1',
        ]
    )
    return '\n'.join(
        [
            '[Script Info]',
            f'; Sha\'rawy Archive clip card ({preset.name})',
            'ScriptType: v4.00+',
            'WrapStyle: 0',
            'ScaledBorderAndShadow: yes',
            'YCbCr Matrix: TV.709',
            f'PlayResX: {PLAY_RES_X}',
            f'PlayResY: {PLAY_RES_Y}',
            '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
            'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
            'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
            'Alignment, MarginL, MarginR, MarginV, Encoding',
            f'Style: {karaoke}',
            f'Style: {attribution}',
            '',
            '[Events]',
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, '
            'Effect, Text',
        ]
    )


def build_ass(
    words: list[tuple[str, int, int]],
    *,
    clip_start_ms: int,
    clip_end_ms: int,
    preset: str,
    attribution: str,
) -> str:
    """Render the ASS file for one clip.

    ``words`` are ``(text, start_ms, end_ms)`` on the *segment's* timeline, as
    stored on ``corpus.TranscriptWord``; they are shifted onto the clip's
    timeline here. A clip with no words is still a valid card: the attribution
    line always renders, so the caller never has to special-case a silent or
    untranscribed passage.
    """
    if preset not in PRESETS:
        raise ValueError(f'unknown preset {preset!r}; expected one of {sorted(PRESETS)}')
    span_ms = clip_end_ms - clip_start_ms
    if span_ms <= 0:
        raise ValueError(f'clip must have positive length, got {span_ms} ms')

    chosen = PRESETS[preset]
    events = []
    for line in _group_lines(
        _clip_words(words, clip_start_ms=clip_start_ms, span_ms=span_ms)
    ):
        start = _timestamp(line[0].start_cs)
        end = _timestamp(line[-1].end_cs)
        events.append(
            f'Dialogue: 0,{start},{end},{KARAOKE_STYLE},,0,0,0,,{_karaoke_text(line)}'
        )

    mark = _escape(attribution)
    if mark:
        events.append(
            f'Dialogue: 0,{_timestamp(0)},{_timestamp(_cs(span_ms))},'
            f'{ATTRIBUTION_STYLE},,0,0,0,,{mark}'
        )

    return '\n'.join([_header(chosen), *events]) + '\n'
