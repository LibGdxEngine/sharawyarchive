"""Config-driven filename → (surah, ayah range, ordinal, kind) parsing.

The pattern list lives in ``pipeline/parser_patterns.json``, not in this module:
the actual naming of the Sha'rawy archive files is not known in advance, and
editing JSON is the intended way to teach the ingest a new scheme. Patterns are
tried in file order and the first match wins.

This module is pure stdlib on purpose — no Django, no database — so the preview
CLI runs anywhere::

    python -m pipeline.parsers --dry-run /path/to/folder
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

PATTERNS_PATH = Path(__file__).with_name("parser_patterns.json")

AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".opus")
"""Extensions the ingest walks, lowercased."""

MIN_SURAH = 1
MAX_SURAH = 114


@dataclass(frozen=True)
class ParseResult:
    """What a filename claims about its contents.

    ``surah``/``ayah_start``/``ayah_end``/``ordinal`` are ``None`` when the
    matching pattern does not carry that information. ``kind`` is ``None`` when
    the pattern does not pin it down, in which case the caller's default kind
    applies. ``ayah_end`` falls back to ``ayah_start`` for single-ayah names.
    """

    surah: int | None = None
    ayah_start: int | None = None
    ayah_end: int | None = None
    ordinal: int | None = None
    kind: str | None = None
    pattern_name: str = ""


@dataclass(frozen=True)
class Pattern:
    """One compiled entry of ``parser_patterns.json``."""

    name: str
    regex: re.Pattern[str]
    kind: str | None
    description: str = ""


def load_patterns(path: Path | str | None = None) -> list[Pattern]:
    """Compile the enabled patterns from ``path`` (default: the shipped JSON)."""
    source = Path(path) if path is not None else PATTERNS_PATH
    raw = json.loads(source.read_text(encoding="utf-8"))
    patterns: list[Pattern] = []
    for entry in raw["patterns"]:
        if not entry.get("enabled", True):
            continue
        patterns.append(
            Pattern(
                name=entry["name"],
                regex=re.compile(entry["regex"], re.IGNORECASE),
                kind=entry.get("kind"),
                description=entry.get("description", ""),
            )
        )
    return patterns


_DEFAULT_PATTERNS: list[Pattern] | None = None


def default_patterns() -> list[Pattern]:
    """The shipped pattern list, compiled once per process."""
    global _DEFAULT_PATTERNS
    if _DEFAULT_PATTERNS is None:
        _DEFAULT_PATTERNS = load_patterns()
    return _DEFAULT_PATTERNS


def _int(value: str | None) -> int | None:
    return int(value) if value else None


def parse_filename(name: str, patterns: list[Pattern] | None = None) -> ParseResult | None:
    """Parse one filename. Returns ``None`` when no pattern matches.

    ``name`` may be a bare name or a full path; the directory and the extension
    are stripped first. A pattern whose ``surah`` group is outside 1-114 is
    treated as a non-match, so the next pattern still gets a chance.
    """
    stem = Path(name).stem.strip()
    for pattern in patterns if patterns is not None else default_patterns():
        match = pattern.regex.match(stem)
        if match is None:
            continue
        groups = match.groupdict()
        surah = _int(groups.get("surah"))
        if surah is not None and not (MIN_SURAH <= surah <= MAX_SURAH):
            continue
        ayah_start = _int(groups.get("ayah_start"))
        ayah_end = _int(groups.get("ayah_end"))
        return ParseResult(
            surah=surah,
            ayah_start=ayah_start,
            ayah_end=ayah_end if ayah_end is not None else ayah_start,
            ordinal=_int(groups.get("ordinal")),
            kind=pattern.kind,
            pattern_name=pattern.name,
        )
    return None


def audio_files(folder: Path | str) -> list[Path]:
    """Every audio file under ``folder``, recursively, in stable path order."""
    root = Path(folder)
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
    )


def _format_row(name: str, result: ParseResult | None) -> str:
    if result is None:
        return f"{name:<44} {'-- UNPARSEABLE --':<20}"
    ayah = ""
    if result.ayah_start is not None:
        ayah = str(result.ayah_start)
        if result.ayah_end is not None and result.ayah_end != result.ayah_start:
            ayah = f"{result.ayah_start}-{result.ayah_end}"
    surah = "" if result.surah is None else str(result.surah)
    ordinal = "" if result.ordinal is None else str(result.ordinal)
    return (
        f"{name:<44} {result.pattern_name:<20} surah={surah:<4} "
        f"ayah={ayah:<8} ordinal={ordinal:<5} kind={result.kind or ''}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.parsers",
        description="Preview how the ingest would parse the audio filenames in a folder.",
    )
    parser.add_argument("folder", help="Folder to scan (recursively).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only. This CLI never writes anything, so the flag is a no-op "
        "kept for symmetry with `python -m pipeline.run --dry-run`.",
    )
    parser.add_argument(
        "--patterns",
        default=None,
        help="Alternative parser_patterns.json to test before shipping it.",
    )
    args = parser.parse_args(argv)

    patterns = load_patterns(args.patterns) if args.patterns else default_patterns()
    files = audio_files(args.folder)
    parsed = 0
    for path in files:
        result = parse_filename(path.name, patterns)
        parsed += result is not None
        print(_format_row(path.name, result))
    print(f"{len(files)} files, {parsed} parsed, {len(files) - parsed} unparseable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
