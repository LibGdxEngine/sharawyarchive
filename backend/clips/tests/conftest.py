"""Fixtures for the clip suite.

The API fixtures come from ``api.tests.factories`` unchanged. Rendering needs
something they cannot give it — audio that actually exists in object storage —
so :func:`renderable` builds a small real archive: 40 seconds of synthesized
tone encoded to Opus, uploaded to MinIO under its own content hash, with a
one-word-per-second transcript over it. Everything the renderer touches is real:
the bucket, ffmpeg, the database.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from api.tests.factories import (  # noqa: F401
    WORD_TEXTS,
    api,
    archive,
    reset_throttles,
)
from corpus import storage
from corpus.arabic import normalize_for_index
from corpus.models import (
    AudioAsset,
    Segment,
    SegmentKind,
    Source,
    Transcript,
    TranscriptWord,
)

AUDIO_SECONDS = 40
WORD_COUNT = 40
WORD_SPOKEN_MS = 800
"""One word per second, spoken for 800ms of it — the 200ms rest is the gap the
karaoke tag has to absorb."""


@dataclass(frozen=True)
class Renderable:
    """A segment whose audio is really in the bucket, with a real transcript."""

    segment: Segment
    audio: AudioAsset
    transcript: Transcript
    words: list[TranscriptWord]


def ffprobe(path: Path | str) -> dict:
    """Streams and format of a media file, as ffprobe sees it."""
    completed = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-print_format',
            'json',
            '-show_format',
            '-show_streams',
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def synthesize_opus(folder: Path, *, seconds: int = AUDIO_SECONDS) -> Path:
    """A boring but genuine Opus file: a sine tone, encoded as the pipeline does."""
    path = folder / 'segment.opus'
    subprocess.run(
        [
            'ffmpeg',
            '-nostdin',
            '-y',
            '-v',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'sine=frequency=440:duration={seconds}',
            '-c:a',
            'libopus',
            '-b:a',
            '32k',
            '-ac',
            '1',
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def renderable(db: None, tmp_path: Path) -> Renderable:
    path = synthesize_opus(tmp_path)
    payload = path.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    key = storage.audio_key(sha256)
    storage.upload_file(key, str(path), 'audio/ogg')

    duration_ms = AUDIO_SECONDS * 1000
    audio, _ = AudioAsset.objects.update_or_create(
        sha256=sha256,
        defaults={
            'storage_key': key,
            'duration_ms': duration_ms,
            'mime': 'audio/ogg',
            'bitrate': 32_000,
            'sample_rate': 48_000,
            'size_bytes': len(payload),
        },
    )
    source, _ = Source.objects.get_or_create(title='خواطر — عينة تركيب', kind='tv')
    segment = Segment.objects.create(
        source=source,
        kind=SegmentKind.KHAWATIR,
        audio=audio,
        ordinal=0,
        duration_ms=duration_ms,
        title='مقطع اختبار',
    )
    texts = [WORD_TEXTS[index % len(WORD_TEXTS)] for index in range(WORD_COUNT)]
    raw_text = ' '.join(texts)
    transcript = Transcript.objects.create(
        segment=segment,
        engine='stub',
        raw_text=raw_text,
        text_normalized=normalize_for_index(raw_text),
        word_count=len(texts),
    )
    words = TranscriptWord.objects.bulk_create(
        TranscriptWord(
            transcript=transcript,
            idx=index,
            text=text,
            start_ms=index * 1000,
            end_ms=index * 1000 + WORD_SPOKEN_MS,
        )
        for index, text in enumerate(texts)
    )
    return Renderable(segment=segment, audio=audio, transcript=transcript, words=words)
