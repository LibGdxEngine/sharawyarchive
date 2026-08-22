"""Pytest bootstrap for the pipeline suite.

The pipeline lives outside ``backend/``, so Django has to be set up by hand
before pytest-django loads the settings module. The database defaults to
``pipeline_pg`` on the host-published postgres (production parity; the
migration history still creates pgvector columns); anything already exported
wins.

The suite talks to the real MinIO from docker compose — the transcode stage
uploading and ``storage.object_exists`` seeing the object is exactly what these
tests are for. Only ``search.services`` is faked, because the search app is
built in a separate story.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ENV_DEFAULTS = {
    "DJANGO_SETTINGS_MODULE": "core.settings.dev",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "pipeline_pg",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
    # The stub recognizer fabricates text, so get_asr_engine() refuses it
    # without this explicit opt-in; test data never ships.
    "ALLOW_STUB_ENGINES": "true",
}

for _key, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

from pipeline.django_setup import setup_django

setup_django()

from django.conf import settings

from pipeline import stages

if "postgresql" not in settings.DATABASES["default"]["ENGINE"]:
    # pytest-django reads the settings before conftest defaults can land, so a
    # bare `pytest` would silently fall back to SQLite and die on the pgvector
    # index. Fail immediately, with the command that works.
    raise pytest.UsageError(
        "the pipeline suite needs postgres (pgvector). Run it as:\n"
        "  cd pipeline && DB_HOST=localhost DB_PORT=5432 DB_NAME=pipeline_pg "
        "DB_USER=postgres DB_PASSWORD=postgres ../.venv/bin/python -m pytest"
    )

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_ONE = "002 - al-baqarah - 01.mp3"
VALID_TWO = "002 - al-baqarah - 02.mp3"
CORRUPTED = "002 - al-baqarah - 03.mp3"


def synthesize_audio(path: Path, *, seconds: int = 30, frequency: int = 440) -> Path:
    """Write a real (tiny, boring) audio file with ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={seconds}",
            "-q:a",
            "9",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def audio_folder(tmp_path: Path) -> Path:
    """Two playable files and one that is not audio at all."""
    folder = tmp_path / "corpus"
    folder.mkdir()
    synthesize_audio(folder / VALID_ONE, frequency=440)
    synthesize_audio(folder / VALID_TWO, frequency=523)
    (folder / CORRUPTED).write_bytes(b"this is not an mp3, not even close\n" * 64)
    return folder


class FakeSearchServices:
    """Stand-in for ``search.services`` (built by another story)."""

    def __init__(self) -> None:
        self.ensure_calls = 0
        self.indexed: list[object] = []

    def ensure_chunks_index(self) -> None:
        self.ensure_calls += 1

    def index_chunks(self, chunks) -> None:  # noqa: ANN001 - list[corpus.models.Chunk]
        self.indexed.extend(chunks)


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> FakeSearchServices:
    """Replace the late ``search.services`` import in the index stage."""
    fake = FakeSearchServices()
    monkeypatch.setattr(stages, "_search_services", lambda: fake)
    return fake
