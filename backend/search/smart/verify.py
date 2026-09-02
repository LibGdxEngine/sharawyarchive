"""Stage 6 — check the generator's answer against the transcript and the mushaf.

Nothing the model wrote reaches a reader unverified:

* every ``citations[].quote`` must be found (fuzzily, at
  ``SMART_QUOTE_MIN_SCORE``) in the words of the passage it names, and is
  resolved to the **milliseconds of those words** from ``TranscriptWord`` —
  the same rows and the same membership rule (word start inside the span) the
  chunk API uses, so a citation plays exactly what it quotes;
* every ``[pN]`` marker must point at a passage with an accepted quote, or it
  is stripped; a sentence left without a marker is dropped (except the one
  sentence of a ``not_found`` answer);
* every ``[[ayah:S:A]]`` placeholder must name a real ayah, whose text is then
  taken from the ``quran`` app — never from the model (CLAUDE.md rule 1).

The status is downgraded to match what survived.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

from django.conf import settings
from rapidfuzz import fuzz

from corpus.arabic import normalize_for_index
from corpus.models import Chunk, TranscriptWord
from quran.models import Ayah

from .generate import is_arabic
from .schemas import AyahOut, AyahRef, Citation, ContextPassage, GeneratedAnswer, ResponseStatus

__all__ = [
    "MAX_ANSWER_CHARS",
    "MAX_QUOTE_WORDS",
    "MAX_SPAN_MS",
    "MIN_QUOTE_WORDS",
    "NOT_FOUND_COPY",
    "Verified",
    "VerifyError",
    "find_span",
    "listen_url",
    "offset_map",
    "verify",
]

MIN_QUOTE_WORDS = 3
MAX_QUOTE_WORDS = 60
MAX_SPAN_MS = 5 * 60 * 1000
MAX_ANSWER_CHARS = 2500
NOT_FOUND_COPY = "لم أجد في الأرشيف حديثًا صريحًا للشيخ الشعراوي رحمه الله عن هذه المسألة."

_MARKER = re.compile(r"\[(p\d+)\]")
_NUMBER = re.compile(r"\[(\d+)\]")
_AYAH = re.compile(r"\[\[ayah:(\d{1,3}):(\d{1,4})\]\]")
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+|\n+")


class VerifyError(ValueError):
    """The answer cannot be shown at all (empty, not Arabic, …)."""


@dataclass
class Verified:
    status: ResponseStatus
    answer_md: str
    citations: list[Citation] = field(default_factory=list)
    ayah_refs: list[AyahOut] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """What was dropped and why — for ``debug`` and the ``SmartQuery`` row."""


@dataclass(frozen=True)
class _Word:
    idx: int
    text: str
    start_ms: int
    end_ms: int
    char_start: int
    char_end: int


@dataclass
class OffsetMap:
    """A passage's words, their normalized text joined by single spaces, and
    where each word sits in that text."""

    words: list[_Word]
    text: str

    @property
    def starts(self) -> list[int]:
        return [word.char_start for word in self.words]


def offset_map(passage: ContextPassage) -> OffsetMap:
    rows = TranscriptWord.objects.filter(
        transcript_id=passage.transcript_id,
        start_ms__gte=passage.start_ms,
        start_ms__lt=passage.end_ms,
    ).order_by("idx")
    words: list[_Word] = []
    parts: list[str] = []
    cursor = 0
    for row in rows:
        normalized = normalize_for_index(row.text)
        if not normalized:
            continue
        if parts:
            cursor += 1  # the joining space
        words.append(
            _Word(
                idx=row.idx,
                text=row.text,
                start_ms=int(row.start_ms),
                end_ms=int(row.end_ms),
                char_start=cursor,
                char_end=cursor + len(normalized),
            )
        )
        parts.append(normalized)
        cursor += len(normalized)
    return OffsetMap(words=words, text=" ".join(parts))


@dataclass(frozen=True)
class Span:
    first: _Word
    last: _Word
    score: float

    @property
    def start_ms(self) -> int:
        return self.first.start_ms

    @property
    def end_ms(self) -> int:
        return self.last.end_ms


def find_span(quote: str, offsets: OffsetMap, *, min_score: float | None = None) -> Span | None:
    """Where ``quote`` sits in the passage's words, or ``None`` when it does not."""
    if not offsets.words:
        return None
    needle = normalize_for_index(quote)
    if not needle:
        return None
    threshold = settings.SMART_QUOTE_MIN_SCORE if min_score is None else min_score
    alignment = fuzz.partial_ratio_alignment(needle, offsets.text, score_cutoff=threshold)
    if alignment is None or alignment.dest_end <= alignment.dest_start:
        return None
    starts = offsets.starts
    first = offsets.words[max(0, bisect_right(starts, alignment.dest_start) - 1)]
    last = offsets.words[max(0, bisect_right(starts, alignment.dest_end - 1) - 1)]
    if last.idx < first.idx:
        return None
    return Span(first=first, last=last, score=float(alignment.score))


def listen_url(segment_id: int, start_ms: int) -> str:
    return f"/listen/{segment_id}?t={int(start_ms)}"


def _chunk_id(transcript_id: int, start_ms: int) -> int | None:
    return (
        Chunk.objects.filter(
            transcript_id=transcript_id, start_ms__lte=start_ms, end_ms__gt=start_ms
        )
        .values_list("pk", flat=True)
        .first()
    )


def _split_sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(text) if part and part.strip()]


def _hydrate_ayahs(refs: Sequence[tuple[int, int]]) -> dict[tuple[int, int], AyahOut]:
    if not refs:
        return {}
    from django.db.models import Q

    condition = Q()
    for surah, ayah in set(refs):
        condition |= Q(surah_id=surah, number=ayah)
    found = Ayah.objects.filter(condition).select_related("surah")
    return {
        (row.surah_id, row.number): AyahOut(
            surah=row.surah_id,
            ayah=row.number,
            surah_name_ar=row.surah.name_ar,
            text_uthmani=row.text_uthmani,
        )
        for row in found
    }


def verify(answer: GeneratedAnswer, passages: Sequence[ContextPassage]) -> Verified:
    """The answer as it may be shown, with citations resolved to milliseconds."""
    by_id = {passage.id: passage for passage in passages}
    notes: list[str] = []
    citations: list[Citation] = []
    numbers_of: dict[str, list[int]] = {}
    offsets: dict[str, OffsetMap] = {}

    for draft in answer.citations:
        passage = by_id.get(draft.passage_id)
        if passage is None:
            notes.append(f"citation: unknown passage {draft.passage_id!r}")
            continue
        words = normalize_for_index(draft.quote).split()
        if not MIN_QUOTE_WORDS <= len(words) <= MAX_QUOTE_WORDS:
            notes.append(f"citation: quote of {len(words)} words in {passage.id}")
            continue
        if passage.id not in offsets:
            offsets[passage.id] = offset_map(passage)
        span = find_span(draft.quote, offsets[passage.id])
        if span is None:
            notes.append(f"citation: quote not found in {passage.id}")
            continue
        if span.end_ms - span.start_ms > MAX_SPAN_MS or span.end_ms <= span.start_ms:
            notes.append(f"citation: span of {span.end_ms - span.start_ms} ms in {passage.id}")
            continue
        number = len(citations) + 1
        chosen = offsets[passage.id].words
        display = " ".join(
            word.text for word in chosen if span.first.idx <= word.idx <= span.last.idx
        )
        citations.append(
            Citation(
                n=number,
                passage_id=passage.passage_ids[0],
                chunk_id=_chunk_id(passage.transcript_id, span.start_ms),
                segment_id=passage.segment_id,
                segment_title=passage.segment_title,
                surah=passage.surah,
                ayah_start=passage.ayah_start,
                ayah_end=passage.ayah_end,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                quote_display=display,
                listen_url=listen_url(passage.segment_id, span.start_ms),
            )
        )
        numbers_of.setdefault(passage.id, []).append(number)

    # Markers: [pN] → the numbers of that passage's accepted citations, or nothing.
    def replace_marker(match: re.Match[str]) -> str:
        numbers = numbers_of.get(match.group(1))
        if not numbers:
            notes.append(f"marker: orphan [{match.group(1)}]")
            return ""
        return "".join(f"[{n}]" for n in numbers)

    text = _MARKER.sub(replace_marker, answer.answer_md)
    text = re.sub(r"(\[\d+\])\1+", r"\1", text)  # a marker repeated by the merge

    # Sentences without a marker are unsupported and go — except the single
    # sentence a not_found answer is allowed to say.
    kept: list[str] = []
    for sentence in _split_sentences(text):
        if _NUMBER.search(sentence) or (answer.status == "not_found" and not kept):
            kept.append(sentence.strip())
        else:
            notes.append(f"sentence: unmarked: {sentence.strip()[:40]}")
    text = "\n".join(kept).strip()

    # Ayah placeholders: only real ayahs stay, and their text is the mushaf's.
    wanted = [(int(s), int(a)) for s, a in _AYAH.findall(text)]
    wanted += [(ref.surah, ref.ayah) for ref in answer.ayah_refs]
    hydrated = _hydrate_ayahs(wanted)

    def replace_ayah(match: re.Match[str]) -> str:
        key = (int(match.group(1)), int(match.group(2)))
        if key in hydrated:
            return match.group(0)
        notes.append(f"ayah: no such ayah {key[0]}:{key[1]}")
        return ""

    text = _AYAH.sub(replace_ayah, text)
    ayah_refs: list[AyahOut] = []
    seen: set[tuple[int, int]] = set()
    for key in wanted:
        if key in hydrated and key not in seen:
            seen.add(key)
            ayah_refs.append(hydrated[key])

    # Status follows what survived.
    status: ResponseStatus = answer.status
    if not citations:
        status = "not_found"
        if not text or not is_arabic(text):
            text = NOT_FOUND_COPY
        notes.append("status: no citation survived")
    elif status == "answered" and len(citations) * 2 < len(answer.citations):
        status = "partial"
        notes.append("status: most citations were dropped")

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+\n", "\n", text).strip()
    if len(text) > MAX_ANSWER_CHARS:
        cut = text.rfind(".", 0, MAX_ANSWER_CHARS)
        text = text[: cut + 1 if cut > 0 else MAX_ANSWER_CHARS].rstrip()
        notes.append("answer: truncated")
    if not text or not is_arabic(text):
        raise VerifyError("answer is empty or not Arabic")

    followups = [item.strip() for item in answer.followups if item.strip() and is_arabic(item)][:3]
    return Verified(
        status=status,
        answer_md=text,
        citations=citations,
        ayah_refs=ayah_refs,
        followups=followups,
        notes=notes,
    )


def refs_of(ayah_refs: Sequence[AyahOut]) -> list[AyahRef]:
    return [AyahRef(surah=item.surah, ayah=item.ayah) for item in ayah_refs]
