"""Tests for the Tanzil parsers and the ``import_quran`` management command.

The parser tests run against a small handcrafted slice in ``fixtures/`` (first
three suras, invented division markers) so they stay fast and readable. The
integration test then runs the real command against the committed Tanzil files.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pytest
from django.core.management import call_command

from corpus.arabic import normalize_for_index
from quran import tanzil
from quran.models import Ayah, Surah

FIXTURES = Path(__file__).parent / "fixtures"
SLICE_UTHMANI = (FIXTURES / "tanzil_slice_uthmani.txt").read_text(encoding="utf-8")
SLICE_SIMPLE = (FIXTURES / "tanzil_slice_simple.txt").read_text(encoding="utf-8")
SLICE_METADATA = (FIXTURES / "tanzil_slice_metadata.xml").read_text(encoding="utf-8")

AYAT_AL_KURSI_OPENING = "الله لا اله الا هو"


# --------------------------------------------------------------------------- #
# parse_ayah_lines
# --------------------------------------------------------------------------- #


def test_parse_ayah_lines_reads_every_record_and_skips_comments() -> None:
    lines = tanzil.parse_ayah_lines(SLICE_UTHMANI)
    assert [line.key for line in lines] == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (3, 1), (3, 2)]
    assert all(line.text for line in lines)
    assert not any(line.text.startswith("#") for line in lines)


def test_parse_ayah_lines_keeps_pipes_inside_the_text() -> None:
    (line,) = tanzil.parse_ayah_lines("7|1|a|b")
    assert line.text == "a|b"


@pytest.mark.parametrize(
    "content",
    [
        "1|1",  # too few fields
        "1|x|text",  # non-integer ayah index
        "0|1|text",  # non-positive surah index
        "1|1|   ",  # empty text
        "1|1|first\n1|1|again",  # duplicate key
        "# only comments\n",  # no records at all
    ],
)
def test_parse_ayah_lines_rejects_malformed_input(content: str) -> None:
    with pytest.raises(tanzil.TanzilParseError):
        tanzil.parse_ayah_lines(content)


# --------------------------------------------------------------------------- #
# parse_metadata / StartMarkers
# --------------------------------------------------------------------------- #


def test_parse_metadata_maps_sura_attributes() -> None:
    metadata = tanzil.parse_metadata(SLICE_METADATA)
    assert [s.number for s in metadata.suras] == [1, 2, 3]

    fatiha, baqara, imran = metadata.suras
    assert fatiha.name_ar == "الفاتحة"
    assert fatiha.name_en == "The Opening"
    assert fatiha.ayah_count == 3
    assert fatiha.order_revealed == 5
    assert fatiha.revelation_place == tanzil.MAKKAH
    assert baqara.revelation_place == tanzil.MADINAH
    assert imran.name_ar == "آل عمران"


def test_parse_metadata_collects_division_markers_and_sajdas() -> None:
    metadata = tanzil.parse_metadata(SLICE_METADATA)
    assert (len(metadata.juz), len(metadata.hizb_quarters), len(metadata.pages)) == (2, 4, 3)
    assert metadata.sajdas == frozenset({(2, 2)})


@pytest.mark.parametrize(
    ("surah", "ayah", "juz", "hizb", "page"),
    [
        (1, 1, 1, 1, 1),
        (1, 2, 1, 1, 1),
        (1, 3, 1, 2, 1),
        (2, 1, 1, 2, 2),
        (2, 2, 2, 3, 2),
        (3, 1, 2, 3, 3),
        (3, 2, 2, 4, 3),
    ],
)
def test_start_markers_resolve_the_containing_division(
    surah: int, ayah: int, juz: int, hizb: int, page: int
) -> None:
    metadata = tanzil.parse_metadata(SLICE_METADATA)
    assert metadata.juz.index_for(surah, ayah) == juz
    assert metadata.hizb_quarters.index_for(surah, ayah) == hizb
    assert metadata.pages.index_for(surah, ayah) == page


def test_start_markers_reject_unordered_input() -> None:
    with pytest.raises(tanzil.TanzilParseError):
        tanzil.StartMarkers([(2, 1), (1, 1)])


def test_parse_metadata_rejects_an_unknown_revelation_type() -> None:
    broken = SLICE_METADATA.replace('type="Meccan"', 'type="Martian"')
    with pytest.raises(tanzil.TanzilParseError):
        tanzil.parse_metadata(broken)


def test_parse_metadata_rejects_malformed_xml() -> None:
    with pytest.raises(tanzil.TanzilParseError):
        tanzil.parse_metadata("<quran><suras>")


# --------------------------------------------------------------------------- #
# strip_sura_bismillah / check_ayah_counts
# --------------------------------------------------------------------------- #


def test_strip_sura_bismillah_detaches_only_the_opening_basmala() -> None:
    lines = tanzil.parse_ayah_lines(SLICE_UTHMANI)
    by_key = {line.key: line.text for line in lines}
    basmala = by_key[(1, 1)]
    assert by_key[(2, 1)].startswith(basmala)

    rewritten, stripped = tanzil.strip_sura_bismillah(lines)
    result = {line.key: line.text for line in rewritten}
    assert stripped == 2  # suras 2 and 3; sura 1's basmala is a numbered ayah
    assert result[(1, 1)] == basmala
    assert result[(2, 1)] == "الٓمٓ"
    assert result[(3, 1)] == "الٓمٓ"
    assert result[(2, 2)] == by_key[(2, 2)]


def test_strip_sura_bismillah_is_idempotent() -> None:
    lines = tanzil.parse_ayah_lines(SLICE_UTHMANI)
    once, _ = tanzil.strip_sura_bismillah(lines)
    twice, stripped = tanzil.strip_sura_bismillah(once)
    assert stripped == 0
    assert twice == once


def test_strip_sura_bismillah_tolerates_the_idgham_shadda() -> None:
    """Suras 95 and 97 open with بِّسْمِ, so a literal prefix match would miss them."""
    content = "\n".join(
        [
            "1|1|بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
            "95|1|بِّسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ وَٱلتِّينِ وَٱلزَّيْتُونِ",
        ]
    )
    rewritten, stripped = tanzil.strip_sura_bismillah(tanzil.parse_ayah_lines(content))
    assert stripped == 1
    assert rewritten[1].text == "وَٱلتِّينِ وَٱلزَّيْتُونِ"


def test_strip_sura_bismillah_leaves_at_tawbah_alone() -> None:
    content = "\n".join(
        [
            "1|1|بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
            "9|1|بَرَآءَةٌ مِّنَ ٱللَّهِ وَرَسُولِهِۦٓ إِلَى ٱلَّذِينَ",
        ]
    )
    rewritten, stripped = tanzil.strip_sura_bismillah(tanzil.parse_ayah_lines(content))
    assert stripped == 0
    assert rewritten[1].text.startswith("بَرَآءَةٌ")


def test_check_ayah_counts_accepts_a_consistent_slice() -> None:
    metadata = tanzil.parse_metadata(SLICE_METADATA)
    tanzil.check_ayah_counts(metadata, tanzil.parse_ayah_lines(SLICE_UTHMANI))


def test_check_ayah_counts_rejects_a_short_sura() -> None:
    metadata = tanzil.parse_metadata(SLICE_METADATA)
    lines = [line for line in tanzil.parse_ayah_lines(SLICE_UTHMANI) if line.key != (1, 3)]
    with pytest.raises(tanzil.TanzilParseError, match="sura 1"):
        tanzil.check_ayah_counts(metadata, lines)


def test_uthmani_and_simple_slices_cover_the_same_ayahs() -> None:
    uthmani = {line.key for line in tanzil.parse_ayah_lines(SLICE_UTHMANI)}
    simple = {line.key for line in tanzil.parse_ayah_lines(SLICE_SIMPLE)}
    assert uthmani == simple


# --------------------------------------------------------------------------- #
# the real data files
# --------------------------------------------------------------------------- #


def test_committed_tanzil_files_are_the_whole_quran() -> None:
    metadata = tanzil.parse_metadata(tanzil.METADATA_PATH.read_text(encoding="utf-8"))
    uthmani = tanzil.parse_ayah_lines(tanzil.UTHMANI_PATH.read_text(encoding="utf-8"))
    tanzil.validate_full_quran(metadata, uthmani)
    tanzil.check_ayah_counts(metadata, uthmani)
    _, stripped = tanzil.strip_sura_bismillah(uthmani)
    assert stripped == tanzil.BISMILLAH_PREFIXED_SURAH_COUNT


# --------------------------------------------------------------------------- #
# import_quran
# --------------------------------------------------------------------------- #


def _run_import(*args: str) -> str:
    out = io.StringIO()
    call_command("import_quran", *args, stdout=out)
    return out.getvalue()


def _corpus_digest() -> str:
    digest = hashlib.sha256()
    for row in Ayah.objects.order_by("surah_id", "number").values_list(
        "surah_id",
        "number",
        "text_uthmani",
        "text_imlaei",
        "text_normalized",
        "juz",
        "hizb",
        "page",
        "sajda",
    ):
        digest.update(repr(row).encode("utf-8"))
    for row in Surah.objects.order_by("number").values_list(
        "number",
        "name_ar",
        "name_ar_plain",
        "name_en",
        "ayah_count",
        "revelation_place",
        "order_revealed",
    ):
        digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class ImportRuns:
    """Output and row digests of two consecutive imports of the real corpus."""

    first_output: str
    second_output: str
    first_digest: str
    second_digest: str


@pytest.fixture(scope="session")
def imported_quran(django_db_setup: object, django_db_blocker: object) -> ImportRuns:
    """Import the real Tanzil corpus once, committed, for the whole session.

    A full import is ~6350 ``update_or_create`` calls, so running it per test
    would dominate the suite. Individual tests still get their own transaction
    and roll back anything they change.
    """
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        first_output = _run_import()
        first_digest = _corpus_digest()
        second_output = _run_import()
        second_digest = _corpus_digest()
    return ImportRuns(first_output, second_output, first_digest, second_digest)


@pytest.mark.django_db
def test_import_quran_creates_the_whole_corpus(imported_quran: ImportRuns) -> None:
    assert Surah.objects.count() == tanzil.SURAH_COUNT
    assert Ayah.objects.count() == tanzil.AYAH_COUNT
    assert (
        f"surahs: created {tanzil.SURAH_COUNT}, updated 0, unchanged 0"
        in imported_quran.first_output
    )
    assert (
        f"ayahs: created {tanzil.AYAH_COUNT}, updated 0, unchanged 0"
        in imported_quran.first_output
    )


@pytest.mark.django_db
def test_import_quran_second_run_is_a_no_op(imported_quran: ImportRuns) -> None:
    total = tanzil.SURAH_COUNT + tanzil.AYAH_COUNT
    assert f"created 0, updated 0, unchanged {total}" in imported_quran.second_output
    assert imported_quran.second_digest == imported_quran.first_digest
    assert Surah.objects.count() == tanzil.SURAH_COUNT
    assert Ayah.objects.count() == tanzil.AYAH_COUNT


@pytest.mark.django_db
def test_import_quran_repairs_a_tampered_row(imported_quran: ImportRuns) -> None:
    Ayah.objects.filter(surah_id=2, number=255).update(text_uthmani="tampered", juz=1)

    output = _run_import()

    assert "ayahs: created 0, updated 1," in output
    assert _corpus_digest() == imported_quran.first_digest


@pytest.mark.django_db
def test_import_quran_populates_surah_metadata(imported_quran: ImportRuns) -> None:
    fatiha = Surah.objects.get(number=1)
    assert fatiha.name_ar == "الفاتحة"
    assert fatiha.name_ar_plain == normalize_for_index(fatiha.name_ar)
    assert fatiha.name_en == "The Opening"
    assert fatiha.ayah_count == 7
    assert fatiha.revelation_place == tanzil.MAKKAH
    assert fatiha.order_revealed == 5

    baqara = Surah.objects.get(number=2)
    assert baqara.revelation_place == tanzil.MADINAH
    assert baqara.ayah_count == 286

    assert Surah.objects.get(number=114).ayah_count == 6
    for surah in Surah.objects.all():
        assert surah.ayahs.count() == surah.ayah_count


@pytest.mark.django_db
def test_import_quran_stores_ayat_al_kursi(imported_quran: ImportRuns) -> None:
    kursi = Ayah.objects.get(surah_id=2, number=255)
    assert kursi.text_uthmani.strip()
    assert kursi.text_imlaei.strip()
    assert AYAT_AL_KURSI_OPENING in normalize_for_index(kursi.text_uthmani)
    assert AYAT_AL_KURSI_OPENING in kursi.text_normalized
    assert kursi.text_normalized == normalize_for_index(kursi.text_uthmani)
    assert kursi.juz == 3
    assert kursi.page == 42


@pytest.mark.django_db
def test_import_quran_detaches_the_sura_opening_basmala(imported_quran: ImportRuns) -> None:
    def normalized(surah: int, ayah: int) -> str:
        return normalize_for_index(Ayah.objects.get(surah_id=surah, number=ayah).text_uthmani)

    # In Al-Fatiha the basmala is a numbered ayah and must survive.
    assert normalized(1, 1) == "بسم الله الرحمن الرحيم"
    assert normalized(2, 1) == "الم"
    # Suras 95 and 97 write the opening basmala with an idgham shadda.
    assert normalized(95, 1) == "والتين والزيتون"
    assert normalized(97, 1).startswith("انا انزلنه")
    # At-Tawbah has no basmala at all, so its first ayah must be untouched.
    assert normalized(9, 1).startswith("براءه من الله")


@pytest.mark.django_db
def test_import_quran_marks_sajda_ayahs(imported_quran: ImportRuns) -> None:
    assert Ayah.objects.filter(sajda=True).count() == 15
    assert Ayah.objects.get(surah_id=7, number=206).sajda is True
    assert Ayah.objects.get(surah_id=2, number=255).sajda is False


@pytest.mark.django_db
def test_import_quran_covers_every_juz_hizb_and_page(imported_quran: ImportRuns) -> None:
    assert Ayah.objects.order_by().values_list("juz", flat=True).distinct().count() == 30
    assert Ayah.objects.order_by().values_list("hizb", flat=True).distinct().count() == 240
    assert Ayah.objects.order_by().values_list("page", flat=True).distinct().count() == 604
    assert Ayah.objects.get(surah_id=1, number=1).juz == 1
    assert Ayah.objects.get(surah_id=114, number=6).juz == 30


@pytest.mark.django_db
def test_import_quran_flush_rebuilds_the_corpus(imported_quran: ImportRuns) -> None:
    Ayah.objects.filter(surah_id=1).delete()
    assert Ayah.objects.count() == tanzil.AYAH_COUNT - 7

    output = _run_import("--flush")

    assert f"ayahs: created {tanzil.AYAH_COUNT}, updated 0, unchanged 0" in output
    assert Surah.objects.count() == tanzil.SURAH_COUNT
    assert Ayah.objects.count() == tanzil.AYAH_COUNT
    assert _corpus_digest() == imported_quran.first_digest
