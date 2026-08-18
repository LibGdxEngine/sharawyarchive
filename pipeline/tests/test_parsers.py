"""Filename parsing: every shipped pattern, the misses, and the preview CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.parsers import ParseResult, load_patterns, parse_filename

from .conftest import REPO_ROOT

# One case per entry in parser_patterns.json, plus the variants each accepts.
CASES: list[tuple[str, ParseResult]] = [
    (
        "khawatir_002_015.mp3",
        ParseResult(surah=2, ordinal=15, kind="khawatir", pattern_name="khawatir_surah_ordinal"),
    ),
    (
        "khawatir-018.m4a",
        ParseResult(surah=18, kind="khawatir", pattern_name="khawatir_surah_ordinal"),
    ),
    (
        "khawatir 002 15 - الفاتحة.mp3",
        ParseResult(surah=2, ordinal=15, kind="khawatir", pattern_name="khawatir_surah_ordinal"),
    ),
    (
        "surah-2-ayah-1-10.mp3",
        ParseResult(
            surah=2,
            ayah_start=1,
            ayah_end=10,
            kind="recitation",
            pattern_name="surah_ayah_range",
        ),
    ),
    (
        "sura_2_aya_255.wav",
        ParseResult(
            surah=2,
            ayah_start=255,
            ayah_end=255,
            kind="recitation",
            pattern_name="surah_ayah_range",
        ),
    ),
    ("s002e01.mp3", ParseResult(surah=2, ordinal=1, pattern_name="surah_episode")),
    ("S114-E12.opus", ParseResult(surah=114, ordinal=12, pattern_name="surah_episode")),
    (
        "002 - al-baqarah - 01.mp3",
        ParseResult(surah=2, ordinal=1, pattern_name="surah_title_ordinal"),
    ),
    ("002.mp3", ParseResult(surah=2, pattern_name="surah_only")),
    ("2.opus", ParseResult(surah=2, pattern_name="surah_only")),
]

UNPARSEABLE = [
    "random-podcast.mp3",
    "2024 - lecture - 01.mp3",  # 2024 is not a surah number
    "surah-200-ayah-1.mp3",  # 200 is out of the 1-114 range
    "خواطر.mp3",
    "",
]


@pytest.mark.parametrize(("name", "expected"), CASES, ids=[case[0] for case in CASES])
def test_default_patterns_parse_their_examples(name: str, expected: ParseResult) -> None:
    assert parse_filename(name) == expected


@pytest.mark.parametrize("name", UNPARSEABLE)
def test_unparseable_names_return_none(name: str) -> None:
    assert parse_filename(name) is None


def test_a_full_path_is_reduced_to_its_stem() -> None:
    assert parse_filename("/srv/audio/khawatir/s002e07.mp3") == ParseResult(
        surah=2, ordinal=7, pattern_name="surah_episode"
    )


def test_the_first_matching_pattern_wins() -> None:
    # "khawatir_002_015" would also satisfy nothing else, but the ordering
    # guarantee is what lets an operator shadow a generic pattern with a
    # specific one by putting it earlier in the JSON.
    names = [pattern.name for pattern in load_patterns()]
    assert names.index("khawatir_surah_ordinal") < names.index("surah_only")


def test_patterns_are_config_driven(tmp_path: Path) -> None:
    """A new naming scheme needs a JSON entry, not a code change."""
    config = tmp_path / "patterns.json"
    config.write_text(
        json.dumps(
            {
                "patterns": [
                    {
                        "name": "tape_side",
                        "regex": r"^tape(?P<surah>\d{1,3})[a-z]$",
                        "kind": "recitation",
                        "enabled": True,
                    },
                    {
                        "name": "disabled_catch_all",
                        "regex": "^.*$",
                        "kind": "khawatir",
                        "enabled": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    patterns = load_patterns(config)

    assert [pattern.name for pattern in patterns] == ["tape_side"]
    assert parse_filename("tape018b.mp3", patterns) == ParseResult(
        surah=18, kind="recitation", pattern_name="tape_side"
    )
    assert parse_filename("002 - al-baqarah - 01.mp3", patterns) is None


def test_dry_run_cli_prints_a_table_and_writes_nothing(audio_folder: Path) -> None:
    before = sorted(path.name for path in audio_folder.iterdir())

    completed = subprocess.run(
        [sys.executable, "-m", "pipeline.parsers", "--dry-run", str(audio_folder)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "002 - al-baqarah - 01.mp3" in completed.stdout
    assert "surah_title_ordinal" in completed.stdout
    assert "3 files, 3 parsed, 0 unparseable" in completed.stdout
    assert sorted(path.name for path in audio_folder.iterdir()) == before


def test_dry_run_cli_reports_unparseable_files(tmp_path: Path) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    (folder / "002 - al-baqarah - 01.mp3").write_bytes(b"")
    (folder / "random-podcast.mp3").write_bytes(b"")

    completed = subprocess.run(
        [sys.executable, "-m", "pipeline.parsers", "--dry-run", str(folder)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "-- UNPARSEABLE --" in completed.stdout
    assert "2 files, 1 parsed, 1 unparseable" in completed.stdout
