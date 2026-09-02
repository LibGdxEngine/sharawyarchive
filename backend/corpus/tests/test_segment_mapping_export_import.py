"""Moving a segment mapping between databases (``export_segments`` /
``import_segments``).

The fixture is the shared archive (``api.tests.factories.build_archive``): two
khawatir segments over one surah, each with its own audio asset. Most tests
here export it, wipe the corpus rows the export describes — the surah stays,
since a mapping never carries Quran text (rule 1) — and import the file back,
which is the whole point of the pair. A record already in the database is
reconciled rather than skipped, so re-importing a corrected file repairs drift.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from api.tests.factories import Archive, make_audio_asset
from corpus import storage
from corpus.models import AudioAsset, Segment, SegmentKind, Source
from quran.models import Surah

pytestmark = pytest.mark.django_db

ABSENT_SURAH = 999
"""Outside the 1-114 range, so no fixture can ever make this one resolve."""

RECORD_KEYS = {
    "source",
    "kind",
    "surah",
    "ayah_start",
    "ayah_end",
    "ordinal",
    "duration_ms",
    "title",
    "status",
    "audio",
}


def _export(path: Path, *args: str) -> list[dict[str, Any]]:
    call_command("export_segments", str(path), *args, stdout=io.StringIO())
    return json.loads(path.read_text(encoding="utf-8"))


def _import(path: Path, *args: str) -> str:
    out = io.StringIO()
    call_command("import_segments", str(path), *args, stdout=out)
    return out.getvalue()


def _rewrite(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _snapshot() -> list[tuple[Any, ...]]:
    """Every field the mapping claims to carry, keyed on the content hash."""
    return list(
        Segment.objects.order_by("audio__sha256").values_list(
            "source__title",
            "source__kind",
            "source__description",
            "source__rights_note",
            "kind",
            "surah_id",
            "ayah_start",
            "ayah_end",
            "ordinal",
            "duration_ms",
            "title",
            "status",
            "audio__sha256",
            "audio__storage_key",
            "audio__duration_ms",
            "audio__mime",
            "audio__bitrate",
            "audio__sample_rate",
            "audio__size_bytes",
        )
    )


def _counts() -> tuple[int, int, int]:
    return Segment.objects.count(), AudioAsset.objects.count(), Source.objects.count()


def _clear_corpus() -> None:
    """Drop everything the mapping describes. Segments first: audio is PROTECTed."""
    Segment.objects.all().delete()
    AudioAsset.objects.all().delete()
    Source.objects.all().delete()


def test_export_writes_the_documented_record_shape(archive: Archive, tmp_path: Path) -> None:
    records = _export(tmp_path / "segments.json")

    assert len(records) == 2
    assert set(records[0]) == RECORD_KEYS
    assert records[0]["surah"] == archive.surah.number
    assert records[0]["audio"]["sha256"] == archive.audio.sha256
    assert records[0]["audio"]["storage_key"] == archive.audio.storage_key


def test_export_import_round_trip_restores_every_field(archive: Archive, tmp_path: Path) -> None:
    path = tmp_path / "segments.json"
    before = _snapshot()
    _export(path)
    _clear_corpus()
    assert _counts() == (0, 0, 0)

    output = _import(path)

    assert _snapshot() == before
    assert _counts() == (2, 2, 1)
    assert "created 2, updated 0, failed 0" in output


def test_a_second_import_of_the_same_file_creates_nothing(
    archive: Archive, tmp_path: Path
) -> None:
    path = tmp_path / "segments.json"
    _export(path)
    _clear_corpus()
    _import(path)
    counts = _counts()

    output = _import(path)

    assert _counts() == counts
    assert "created 0, updated 2, failed 0" in output


def test_a_surah_missing_from_this_database_aborts_the_import(
    archive: Archive, tmp_path: Path
) -> None:
    path = tmp_path / "segments.json"
    records = _export(path)
    records[0]["surah"] = ABSENT_SURAH
    _rewrite(path, records)
    _clear_corpus()
    assert not Surah.objects.filter(pk=ABSENT_SURAH).exists()

    with pytest.raises(CommandError, match=f"{ABSENT_SURAH}"):
        _import(path)

    assert _counts() == (0, 0, 0)


def test_verify_r2_reports_a_missing_key_without_refusing_the_row(
    archive: Archive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "segments.json"
    records = _export(path)
    absent = records[0]["audio"]["storage_key"]
    _clear_corpus()
    monkeypatch.setattr(storage, "object_exists", lambda key: key != absent)

    output = _import(path, "--verify-r2")

    assert f"missing in object storage: {absent}" in output
    assert "created 2, updated 0, failed 0" in output
    assert AudioAsset.objects.filter(storage_key=absent).exists()
    assert _counts() == (2, 2, 1)


def test_a_dry_run_tallies_without_writing(archive: Archive, tmp_path: Path) -> None:
    path = tmp_path / "segments.json"
    _export(path)
    _clear_corpus()

    output = _import(path, "--dry-run")

    assert _counts() == (0, 0, 0)
    assert "created 2, updated 0, failed 0" in output
    assert "nothing written" in output


def test_a_malformed_record_fails_alone(archive: Archive, tmp_path: Path) -> None:
    """The rest of the file must still land, and the run must not look failed."""
    path = tmp_path / "segments.json"
    records = _export(path)
    del records[0]["duration_ms"]
    _rewrite(path, records)
    _clear_corpus()

    output = _import(path)

    assert _counts() == (1, 1, 1)
    assert "created 1, updated 0, failed 1" in output
    assert records[1]["audio"]["sha256"] == AudioAsset.objects.get().sha256


def test_one_audio_asset_can_back_two_segments_of_one_source(
    archive: Archive, tmp_path: Path
) -> None:
    """``Segment.audio`` is a plain FK, so the ordinal is part of the natural key."""
    path = tmp_path / "segments.json"
    records = _export(path)
    records[1]["audio"] = records[0]["audio"]
    records[1]["ordinal"] = records[0]["ordinal"] + 1
    _rewrite(path, records)
    _clear_corpus()

    output = _import(path)

    assert _counts() == (2, 1, 1)
    assert "created 2, updated 0, failed 0" in output
    assert sorted(Segment.objects.values_list("ordinal", flat=True)) == sorted(
        [records[0]["ordinal"], records[1]["ordinal"]]
    )


def test_one_audio_asset_can_back_two_segments_of_different_sources(
    archive: Archive, tmp_path: Path
) -> None:
    """Same asset, same ordinal: only the source tells the two segments apart."""
    path = tmp_path / "segments.json"
    records = _export(path)
    records[1]["audio"] = records[0]["audio"]
    records[1]["ordinal"] = records[0]["ordinal"]
    records[1]["source"] = dict(records[0]["source"], title="إذاعة القرآن الكريم")
    _rewrite(path, records)
    _clear_corpus()

    output = _import(path)

    assert _counts() == (2, 1, 2)
    assert "created 2, updated 0, failed 0" in output
    assert sorted(Segment.objects.values_list("source__title", flat=True)) == sorted(
        [records[0]["source"]["title"], records[1]["source"]["title"]]
    )


def test_a_re_import_reconciles_a_changed_row_instead_of_keeping_it_stale(
    archive: Archive, tmp_path: Path
) -> None:
    """A corrected storage_key is the point: a stale one points at the wrong object."""
    path = tmp_path / "segments.json"
    records = _export(path)
    _clear_corpus()
    _import(path)
    counts = _counts()

    sha256 = records[0]["audio"]["sha256"]
    records[0]["audio"]["storage_key"] = f"audio/corrected/{sha256}.ogg"
    records[0]["audio"]["duration_ms"] += 1_000
    records[0]["title"] = "عنوان مصحح"
    _rewrite(path, records)

    output = _import(path)

    asset = AudioAsset.objects.get(sha256=sha256)
    assert asset.storage_key == records[0]["audio"]["storage_key"]
    assert asset.duration_ms == records[0]["audio"]["duration_ms"]
    assert Segment.objects.get(audio=asset).title == "عنوان مصحح"
    assert _counts() == counts
    assert "created 0, updated 2, failed 0" in output


def test_kind_exports_only_segments_of_that_kind(archive: Archive, tmp_path: Path) -> None:
    """``build_archive`` is khawatir throughout, so the recitation half is added here."""
    recitation = Segment.objects.create(
        source=archive.source,
        kind=SegmentKind.RECITATION,
        surah=archive.surah,
        ayah_start=1,
        ayah_end=3,
        audio=make_audio_asset(),
        ordinal=9,
        duration_ms=120_000,
        title="تلاوة البقرة ١-٣",
    )

    recitations = _export(tmp_path / "recitation.json", "--kind", "recitation")
    khawatir = _export(tmp_path / "khawatir.json", "--kind", "khawatir")

    assert [record["audio"]["sha256"] for record in recitations] == [recitation.audio.sha256]
    assert len(khawatir) == 2
    assert {record["kind"] for record in khawatir} == {SegmentKind.KHAWATIR}
