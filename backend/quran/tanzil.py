"""Pure-python parsers for the Tanzil Quran data files.

Deliberately free of Django imports so the parsing logic can be unit-tested
against a small handcrafted fixture slice. See ``data/ATTRIBUTION.md`` for the
provenance and licence of the files these parsers read.

Two shapes are handled:

``quran-uthmani.txt`` / ``quran-simple.txt``
    Tanzil ``txt-2`` output: one ``surah|ayah|text`` line per ayah, with a
    licence header/footer of ``#``-prefixed comment lines and blank lines.

``quran-data.xml``
    Tanzil metadata: 114 ``<sura>`` elements plus ``<juz>``, ``<quarter>``
    (hizb quarters), ``<page>`` and ``<sajda>`` start markers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from corpus.arabic import normalize_for_index

DATA_DIR = Path(__file__).resolve().parent / "data"

UTHMANI_PATH = DATA_DIR / "quran-uthmani.txt"
SIMPLE_PATH = DATA_DIR / "quran-simple.txt"
METADATA_PATH = DATA_DIR / "quran-data.xml"

_TEXT_OPTIONS = "outType=txt-2&marks=true&sajdah=true&tatweel=true&agree=true"

TANZIL_URLS: dict[Path, str] = {
    UTHMANI_PATH: (
        f"https://tanzil.net/pub/download/index.php?quranType=uthmani&{_TEXT_OPTIONS}"
    ),
    SIMPLE_PATH: f"https://tanzil.net/pub/download/index.php?quranType=simple&{_TEXT_OPTIONS}",
    METADATA_PATH: "https://tanzil.net/res/text/metadata/quran-data.xml",
}

SURAH_COUNT = 114
AYAH_COUNT = 6236
JUZ_COUNT = 30
HIZB_QUARTER_COUNT = 240
PAGE_COUNT = 604

BISMILLAH_PREFIXED_SURAH_COUNT = 112
"""Suras whose ayah 1 carries an inlined opening basmala: 2-114 except 9."""

BASMALA_WORD_COUNT = 4
"""بسم / الله / الرحمن / الرحيم."""

MAKKAH = "makkah"
MADINAH = "madinah"

_REVELATION_PLACES = {"Meccan": MAKKAH, "Medinan": MADINAH}


class TanzilParseError(ValueError):
    """Raised when a Tanzil source file does not have the expected shape."""


@dataclass(frozen=True, slots=True)
class AyahLine:
    """One ``surah|ayah|text`` record."""

    surah: int
    ayah: int
    text: str

    @property
    def key(self) -> tuple[int, int]:
        return (self.surah, self.ayah)


@dataclass(frozen=True, slots=True)
class SuraMeta:
    """One ``<sura>`` element, mapped onto the fields ``quran.Surah`` needs."""

    number: int
    ayah_count: int
    name_ar: str
    name_en: str
    revelation_place: str
    order_revealed: int


class StartMarkers:
    """Ordered division start points, answering "which division is this ayah in?".

    Tanzil records juz/hizb/page as the ``(sura, aya)`` where each division
    *begins*. The division containing an ayah is therefore the last marker that
    is not after it, which is what :meth:`index_for` returns (1-based).
    """

    __slots__ = ("_starts",)

    def __init__(self, starts: Sequence[tuple[int, int]]) -> None:
        ordered = list(starts)
        if ordered != sorted(ordered):
            raise TanzilParseError("division start markers are not in ascending order")
        if not ordered:
            raise TanzilParseError("no division start markers found")
        self._starts = ordered

    def __len__(self) -> int:
        return len(self._starts)

    def index_for(self, surah: int, ayah: int) -> int:
        position = bisect_right(self._starts, (surah, ayah))
        if position == 0:
            raise TanzilParseError(f"{surah}:{ayah} precedes the first division marker")
        return position


@dataclass(frozen=True, slots=True)
class QuranMetadata:
    """Everything ``quran-data.xml`` gives us, in a usable shape."""

    suras: tuple[SuraMeta, ...]
    juz: StartMarkers
    hizb_quarters: StartMarkers
    pages: StartMarkers
    sajdas: frozenset[tuple[int, int]]


def parse_ayah_lines(content: str) -> list[AyahLine]:
    """Parse the body of a Tanzil ``txt-2`` file.

    Comment lines (``#``) and blank lines are ignored. Raises
    :class:`TanzilParseError` on a malformed record, a non-positive index, or a
    duplicated ``(surah, ayah)`` key.
    """
    lines: list[AyahLine] = []
    seen: set[tuple[int, int]] = set()
    for lineno, raw in enumerate(content.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("|", 2)
        if len(parts) != 3:
            raise TanzilParseError(f"line {lineno}: expected 'surah|ayah|text', got {raw!r}")
        surah_raw, ayah_raw, text = parts
        try:
            surah, ayah = int(surah_raw), int(ayah_raw)
        except ValueError as exc:
            raise TanzilParseError(f"line {lineno}: non-integer index in {raw!r}") from exc
        if surah < 1 or ayah < 1:
            raise TanzilParseError(f"line {lineno}: indices must be positive, got {surah}:{ayah}")
        text = text.strip()
        if not text:
            raise TanzilParseError(f"line {lineno}: empty ayah text for {surah}:{ayah}")
        if (surah, ayah) in seen:
            raise TanzilParseError(f"line {lineno}: duplicate ayah {surah}:{ayah}")
        seen.add((surah, ayah))
        lines.append(AyahLine(surah=surah, ayah=ayah, text=text))
    if not lines:
        raise TanzilParseError("no ayah records found")
    return lines


def strip_sura_bismillah(lines: Sequence[AyahLine]) -> tuple[list[AyahLine], int]:
    """Detach the sura-opening basmala that Tanzil's txt export inlines.

    Tanzil's XML export keeps the opening basmala in a separate ``bismillah``
    attribute — ``<aya index="1" text="الٓمٓ" bismillah="بِسْمِ ٱللَّهِ …"/>`` —
    but the txt export prepends it to the text of ayah 1, which would otherwise
    put four words of Al-Fatiha into 112 other ayahs.

    Ayah 1:1 *is* the basmala, so it supplies the reference form: the first
    :data:`BASMALA_WORD_COUNT` words of a sura-opening ayah are dropped when
    they normalize to the same thing. Matching on the normalized form rather
    than the literal prefix matters — suras 95 and 97 write ``بِّسْمِ`` with a
    shadda, carried over from the preceding sura by idgham — and it keeps this
    free of hard-coded Arabic and independent of the diacritic options the
    files were downloaded with.

    Sura 1 is left alone (there the basmala is a numbered ayah) and so is
    At-Tawbah (9), which has no basmala at all.

    Returns the rewritten lines and how many were actually shortened.
    """
    reference = next((line.text for line in lines if line.key == (1, 1)), None)
    if reference is None:
        raise TanzilParseError("cannot locate ayah 1:1, needed to identify the basmala")
    basmala = normalize_for_index(reference)

    rewritten: list[AyahLine] = []
    stripped = 0
    for line in lines:
        if line.surah == 1 or line.ayah != 1:
            rewritten.append(line)
            continue
        words = line.text.split(maxsplit=BASMALA_WORD_COUNT)
        if len(words) <= BASMALA_WORD_COUNT:
            rewritten.append(line)
            continue
        head, tail = words[:BASMALA_WORD_COUNT], words[BASMALA_WORD_COUNT]
        if normalize_for_index(" ".join(head)) != basmala:
            rewritten.append(line)
            continue
        stripped += 1
        rewritten.append(AyahLine(surah=line.surah, ayah=line.ayah, text=tail))
    return rewritten, stripped


def _marker_starts(elements: Iterable[ET.Element], label: str) -> StartMarkers:
    starts: list[tuple[int, int]] = []
    for element in elements:
        try:
            starts.append((int(element.attrib["sura"]), int(element.attrib["aya"])))
        except (KeyError, ValueError) as exc:
            raise TanzilParseError(f"malformed <{label}> marker: {element.attrib}") from exc
    return StartMarkers(starts)


def parse_metadata(content: str) -> QuranMetadata:
    """Parse ``quran-data.xml`` into :class:`QuranMetadata`."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise TanzilParseError(f"quran-data.xml is not well-formed: {exc}") from exc

    suras: list[SuraMeta] = []
    for element in root.iter("sura"):
        attrib = element.attrib
        try:
            place = _REVELATION_PLACES[attrib["type"]]
        except KeyError as exc:
            raise TanzilParseError(f"unknown sura type {attrib.get('type')!r}") from exc
        try:
            suras.append(
                SuraMeta(
                    number=int(attrib["index"]),
                    ayah_count=int(attrib["ayas"]),
                    name_ar=attrib["name"],
                    name_en=attrib["ename"],
                    revelation_place=place,
                    order_revealed=int(attrib["order"]),
                )
            )
        except (KeyError, ValueError) as exc:
            raise TanzilParseError(f"malformed <sura> element: {attrib}") from exc
    if not suras:
        raise TanzilParseError("no <sura> elements found")
    suras.sort(key=lambda s: s.number)

    sajdas: set[tuple[int, int]] = set()
    for element in root.iter("sajda"):
        try:
            sajdas.add((int(element.attrib["sura"]), int(element.attrib["aya"])))
        except (KeyError, ValueError) as exc:
            raise TanzilParseError(f"malformed <sajda> element: {element.attrib}") from exc

    return QuranMetadata(
        suras=tuple(suras),
        juz=_marker_starts(root.iter("juz"), "juz"),
        hizb_quarters=_marker_starts(root.iter("quarter"), "quarter"),
        pages=_marker_starts(root.iter("page"), "page"),
        sajdas=frozenset(sajdas),
    )


def validate_full_quran(metadata: QuranMetadata, ayah_lines: Sequence[AyahLine]) -> None:
    """Assert that a parsed corpus really is the whole Quran.

    Guards against a truncated or corrupted download silently becoming the
    canonical text (project rule 1).
    """
    if len(metadata.suras) != SURAH_COUNT:
        raise TanzilParseError(f"expected {SURAH_COUNT} suras, got {len(metadata.suras)}")
    if len(ayah_lines) != AYAH_COUNT:
        raise TanzilParseError(f"expected {AYAH_COUNT} ayahs, got {len(ayah_lines)}")
    if len(metadata.juz) != JUZ_COUNT:
        raise TanzilParseError(f"expected {JUZ_COUNT} juz markers, got {len(metadata.juz)}")
    if len(metadata.hizb_quarters) != HIZB_QUARTER_COUNT:
        raise TanzilParseError(
            f"expected {HIZB_QUARTER_COUNT} hizb quarters, got {len(metadata.hizb_quarters)}"
        )
    if len(metadata.pages) != PAGE_COUNT:
        raise TanzilParseError(f"expected {PAGE_COUNT} page markers, got {len(metadata.pages)}")


def check_ayah_counts(metadata: QuranMetadata, ayah_lines: Sequence[AyahLine]) -> None:
    """Assert each sura has exactly the number of ayahs its metadata claims."""
    counted: dict[int, int] = {}
    for line in ayah_lines:
        counted[line.surah] = counted.get(line.surah, 0) + 1
    for sura in metadata.suras:
        actual = counted.get(sura.number, 0)
        if actual != sura.ayah_count:
            raise TanzilParseError(
                f"sura {sura.number}: metadata says {sura.ayah_count} ayahs, text has {actual}"
            )
    unknown = set(counted) - {s.number for s in metadata.suras}
    if unknown:
        raise TanzilParseError(f"text contains suras absent from metadata: {sorted(unknown)}")
