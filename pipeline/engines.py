"""Pluggable ASR and forced-alignment engines.

Selected by the Django setting ``ASR_BACKEND`` (``'stub'`` | ``'faster-whisper'``),
the same way ``corpus.embeddings.get_embedder`` reads ``EMBEDDING_BACKEND``. The
stub engines are deterministic and dependency-free so the whole pipeline runs in
CI and on a laptop without torch; the real engines live here too but import
their heavy dependencies lazily, inside the methods.

All timings are integer milliseconds (project rule 5).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Protocol

from django.conf import settings

WORD_GAP_MS = 100
"""Silence the stub leaves between two consecutive words."""

STUB_MS_PER_WORD = 600
"""How fast the stub speaker talks, used to size a synthetic transcript."""

STUB_VOCABULARY: tuple[str, ...] = (
    "وَقَالَ",
    "الشَّيْخُ",
    "الشَّعْرَاوِي",
    "رَحِمَهُ",
    "اللَّهُ",
    "فِي",
    "خَوَاطِرِهِ",
    "حَوْلَ",
    "هَذِهِ",
    "الْآيَةِ",
    "الْكَرِيمَةِ",
    "إِنَّ",
    "الْمَعْنَى",
    "هُنَا",
    "وَاضِحٌ",
    "لِكُلِّ",
    "مَنْ",
    "تَدَبَّرَ",
)
"""Fixed word list the stub cycles through. Diacritics on purpose: the chunk
text keeps them and only ``text_normalized`` strips them."""


@dataclass(frozen=True)
class ASRWord:
    """One word as the recognizer heard it."""

    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


class AlignedWord(NamedTuple):
    """One word after forced alignment — what a ``TranscriptWord`` row is built from."""

    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


class ASREngine(Protocol):
    name: str
    version: str

    def transcribe(self, audio_path: str, *, duration_ms: int) -> list[ASRWord]: ...


class Aligner(Protocol):
    name: str
    version: str
    needs_words: bool

    def align(
        self,
        audio_path: str,
        text: str,
        words: Sequence[ASRWord] | None = None,
        *,
        duration_ms: int,
    ) -> list[AlignedWord]: ...


# --------------------------------------------------------------------------- #
# sidecars
# --------------------------------------------------------------------------- #


def _sidecar(audio_path: str, extension: str) -> Path | None:
    """Find ``x.mp3.<ext>`` or ``x.<ext>`` next to ``x.mp3``, if either exists."""
    path = Path(audio_path)
    candidates = (
        path.with_suffix(path.suffix + extension),
        path.with_suffix(extension),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _even_timings(count: int, duration_ms: int) -> list[tuple[int, int]]:
    """Split ``duration_ms`` into ``count`` slots with a ``WORD_GAP_MS`` gap."""
    slot = max(1, duration_ms // count)
    spans = []
    for index in range(count):
        start = index * slot
        spans.append((start, start + max(1, slot - WORD_GAP_MS)))
    return spans


# --------------------------------------------------------------------------- #
# stub engines
# --------------------------------------------------------------------------- #


class StubASR:
    """Deterministic fake recognizer, seeded by the audio's sha256.

    Three sources of truth, in order:

    1. ``<audio>.timing.json`` — a list of ``{"text", "start_ms", "end_ms"}``
       honoured verbatim. Tests use it to craft pause patterns for chunking.
    2. ``<audio>.txt`` — real Arabic text, spoken evenly across the duration.
    3. nothing — ``duration_ms // 600`` words taken from :data:`STUB_VOCABULARY`,
       starting at an offset derived from the file hash.
    """

    name = "stub"
    version = "1"

    def transcribe(self, audio_path: str, *, duration_ms: int) -> list[ASRWord]:
        digest = hashlib.sha256(Path(audio_path).read_bytes()).digest()

        timing = _sidecar(audio_path, ".timing.json")
        if timing is not None:
            entries = json.loads(timing.read_text(encoding="utf-8"))
            return [
                ASRWord(
                    text=entry["text"],
                    start_ms=int(entry["start_ms"]),
                    end_ms=int(entry["end_ms"]),
                    confidence=self._confidence(digest, index),
                )
                for index, entry in enumerate(entries)
            ]

        transcript = _sidecar(audio_path, ".txt")
        if transcript is not None:
            texts = transcript.read_text(encoding="utf-8").split()
        else:
            count = max(1, duration_ms // STUB_MS_PER_WORD)
            offset = digest[0]
            texts = [
                STUB_VOCABULARY[(offset + index) % len(STUB_VOCABULARY)]
                for index in range(count)
            ]

        spans = _even_timings(len(texts), duration_ms)
        return [
            ASRWord(
                text=text,
                start_ms=start,
                end_ms=end,
                confidence=self._confidence(digest, index),
            )
            for index, (text, (start, end)) in enumerate(zip(texts, spans, strict=True))
        ]

    @staticmethod
    def _confidence(digest: bytes, index: int) -> float:
        return round(0.80 + digest[index % len(digest)] / 255 * 0.19, 4)


class StubAligner:
    """Pass-through refinement: already-timed ASR words in, aligned words out."""

    name = "stub"
    version = "1"
    needs_words = True

    def align(
        self,
        audio_path: str,
        text: str,
        words: Sequence[ASRWord] | None = None,
        *,
        duration_ms: int,
    ) -> list[AlignedWord]:
        if words is None:
            raise ValueError("StubAligner needs the ASR words it is refining")
        return [
            AlignedWord(
                text=word.text,
                start_ms=int(word.start_ms),
                end_ms=int(word.end_ms),
                confidence=word.confidence,
            )
            for word in words
        ]


# --------------------------------------------------------------------------- #
# real engines (heavy deps, see pipeline/requirements.txt)
# --------------------------------------------------------------------------- #


class MissingEngineDependency(RuntimeError):
    """A real engine was selected but its package is not installed."""


class FasterWhisperASR:
    """Whisper via faster-whisper/CTranslate2, word timestamps on.

    Install ``pipeline/requirements.txt`` in the worker image before selecting
    ``ASR_BACKEND=faster-whisper``.
    """

    name = "faster-whisper"

    def __init__(self) -> None:
        self.model_name = os.environ.get("ASR_MODEL", "large-v3")
        self.device = os.environ.get("ASR_DEVICE", "auto")
        self.compute_type = os.environ.get("ASR_COMPUTE_TYPE", "default")
        self.version = self.model_name
        self._model = None

    def _load(self):  # noqa: ANN202 - WhisperModel only exists in workers
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover - depends on the image
                raise MissingEngineDependency(
                    "ASR_BACKEND='faster-whisper' needs faster-whisper: "
                    "pip install -r pipeline/requirements.txt"
                ) from exc
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, audio_path: str, *, duration_ms: int) -> list[ASRWord]:
        model = self._load()
        segments, _info = model.transcribe(
            audio_path, language="ar", word_timestamps=True, vad_filter=True
        )
        words: list[ASRWord] = []
        for segment in segments:
            for word in segment.words or ():
                words.append(
                    ASRWord(
                        text=word.word.strip(),
                        start_ms=int(round(word.start * 1000)),
                        end_ms=int(round(word.end * 1000)),
                        confidence=getattr(word, "probability", None),
                    )
                )
        return words


class CTCAligner:
    """Forced alignment with ctc-forced-aligner: audio + text in, word spans out.

    Does not need the ASR word timings (``needs_words = False``) — it re-derives
    them from the acoustic model, which is the whole point of the stage.
    """

    name = "ctc-forced-aligner"
    needs_words = False

    def __init__(self) -> None:
        self.model_name = os.environ.get(
            "ALIGNER_MODEL", "MahmoudAshraf/mms-300m-1130-forced-aligner"
        )
        self.device = os.environ.get("ASR_DEVICE", "auto")
        self.version = self.model_name

    def align(
        self,
        audio_path: str,
        text: str,
        words: Sequence[ASRWord] | None = None,
        *,
        duration_ms: int,
    ) -> list[AlignedWord]:
        try:
            from ctc_forced_aligner import (
                generate_emissions,
                get_alignments,
                get_spans,
                load_alignment_model,
                load_audio,
                postprocess_results,
                preprocess_text,
            )
        except ImportError as exc:  # pragma: no cover - depends on the image
            raise MissingEngineDependency(
                "ASR_BACKEND='faster-whisper' alignment needs ctc-forced-aligner: "
                "pip install -r pipeline/requirements.txt"
            ) from exc

        model, tokenizer = load_alignment_model(self.device, self.model_name)
        waveform = load_audio(audio_path, model.dtype, model.device)
        emissions, stride = generate_emissions(model, waveform)
        tokens_starred, text_starred = preprocess_text(text, romanize=True, language="ara")
        segments, scores, blank_token = get_alignments(emissions, tokens_starred, tokenizer)
        spans = get_spans(tokens_starred, segments, blank_token)
        results = postprocess_results(text_starred, spans, stride, scores)
        return [
            AlignedWord(
                text=result["text"],
                start_ms=int(round(result["start"] * 1000)),
                end_ms=int(round(result["end"] * 1000)),
                confidence=result.get("score"),
            )
            for result in results
        ]


def get_asr_engine() -> ASREngine:
    """The ASR engine named by ``settings.ASR_BACKEND``."""
    backend = getattr(settings, "ASR_BACKEND", "stub")
    if backend == "stub":
        return StubASR()
    if backend == "faster-whisper":
        return FasterWhisperASR()
    raise ValueError(f"Unknown ASR_BACKEND: {backend!r}")


def get_aligner() -> Aligner:
    """The aligner that pairs with ``settings.ASR_BACKEND``."""
    backend = getattr(settings, "ASR_BACKEND", "stub")
    if backend == "stub":
        return StubAligner()
    if backend == "faster-whisper":
        return CTCAligner()
    raise ValueError(f"Unknown ASR_BACKEND: {backend!r}")
