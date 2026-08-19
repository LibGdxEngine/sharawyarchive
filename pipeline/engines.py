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


class CohereASR:
    """Cohere's hosted transcription API (``POST /v2/audio/transcriptions``).

    Defaults to ``cohere-transcribe-arabic-07-2026`` — the Arabic-specialized
    release (MSA + dialects incl. Egyptian, Arabic/English code-switching),
    newer than the general ``cohere-transcribe-03-2026``.

    The API returns plain text with **no word-level timestamps**, so the
    ``ASRWord`` timings produced here are even placeholders from
    :func:`_even_timings` (exactly like ``StubASR``'s sidecar-text path); the
    ``align`` stage derives the real millisecond spans acoustically with
    :class:`CTCAligner` (``needs_words = False``, so Cohere is called once per
    segment). Auth comes from the ``CO_API_KEY`` env var, which the SDK reads.

    Uploads are capped at 25MB and the accepted containers do not include our
    Opus master, so inputs are re-encoded to mono 32k MP3 when needed and
    audio past the cap is split at detected silences (no overlap — cutting in
    silence keeps plain text concatenation faithful).
    """

    name = "cohere-transcribe"

    ACCEPTED_SUFFIXES = frozenset({".flac", ".mp3", ".mpeg", ".mpga", ".ogg", ".wav"})
    RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    MAX_ATTEMPTS = 3

    def __init__(self) -> None:
        self.model_name = os.environ.get("COHERE_ASR_MODEL", "cohere-transcribe-arabic-07-2026")
        self.language = os.environ.get("COHERE_ASR_LANGUAGE", "ar")
        self.max_upload_bytes = int(
            os.environ.get("COHERE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
        )
        self.version = self.model_name
        self._client = None

    def _load(self):  # noqa: ANN202 - cohere client only exists in workers
        if self._client is None:
            if not os.environ.get("CO_API_KEY"):
                raise RuntimeError(
                    "ASR_BACKEND='cohere' needs the CO_API_KEY environment variable "
                    "(create a key at https://dashboard.cohere.com)"
                )
            try:
                import cohere
            except ImportError as exc:  # pragma: no cover - depends on the image
                raise MissingEngineDependency(
                    "ASR_BACKEND='cohere' needs the cohere SDK: "
                    "pip install -r pipeline/requirements.txt"
                ) from exc
            self._client = cohere.ClientV2()
        return self._client

    def transcribe(self, audio_path: str, *, duration_ms: int) -> list[ASRWord]:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cohere-asr-") as tmpdir:
            parts = self._prepare_upload(audio_path, tmpdir, duration_ms=duration_ms)
            text = " ".join(self._transcribe_file(part) for part in parts).strip()

        texts = text.split()
        if not texts:
            return []
        spans = _even_timings(len(texts), duration_ms)
        return [
            ASRWord(text=text, start_ms=start, end_ms=end, confidence=None)
            for text, (start, end) in zip(texts, spans, strict=True)
        ]

    # -- upload preparation -------------------------------------------------- #

    def _prepare_upload(self, audio_path: str, tmpdir: str, *, duration_ms: int) -> list[str]:
        path = Path(audio_path)
        if (
            path.suffix.lower() in self.ACCEPTED_SUFFIXES
            and path.stat().st_size <= self.max_upload_bytes
        ):
            return [audio_path]

        encoded = self._encode(audio_path, Path(tmpdir) / "upload.mp3")
        if encoded.stat().st_size <= self.max_upload_bytes:
            return [str(encoded)]
        return self._split(audio_path, tmpdir, encoded, duration_ms=duration_ms)

    def _encode(
        self,
        audio_path: str,
        target: Path,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> Path:
        import subprocess

        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        if start_ms is not None:
            command += ["-ss", f"{start_ms / 1000:.3f}"]
        if end_ms is not None:
            command += ["-to", f"{end_ms / 1000:.3f}"]
        command += ["-i", audio_path, "-ac", "1", "-c:a", "libmp3lame", "-b:a", "32k", str(target)]
        subprocess.run(command, check=True, capture_output=True)
        return target

    def _split(
        self, audio_path: str, tmpdir: str, encoded: Path, *, duration_ms: int
    ) -> list[str]:
        part_count = -(-encoded.stat().st_size // self.max_upload_bytes)  # ceil
        boundaries = self._cut_points(audio_path, duration_ms, part_count)
        parts: list[str] = []
        for index, (start_ms, end_ms) in enumerate(
            zip([0, *boundaries], [*boundaries, duration_ms], strict=True)
        ):
            target = Path(tmpdir) / f"part-{index:03d}.mp3"
            parts.append(str(self._encode(audio_path, target, start_ms=start_ms, end_ms=end_ms)))
        return parts

    def _cut_points(self, audio_path: str, duration_ms: int, part_count: int) -> list[int]:
        """Ideal equal-split boundaries, each snapped to the nearest detected
        silence midpoint within ±30s so no word is cut in half."""
        ideal = [duration_ms * index // part_count for index in range(1, part_count)]
        silences = self._silence_midpoints(audio_path)
        cuts = []
        for target in ideal:
            near = [s for s in silences if abs(s - target) <= 30_000]
            cuts.append(min(near, key=lambda s: abs(s - target)) if near else target)
        return cuts

    @staticmethod
    def _silence_midpoints(audio_path: str) -> list[int]:
        import re
        import subprocess

        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-i", audio_path,
                "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
        )
        starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
        ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
        return [
            int(round((start + end) / 2 * 1000)) for start, end in zip(starts, ends, strict=False)
        ]

    # -- API call ------------------------------------------------------------ #

    def _transcribe_file(self, path: str) -> str:
        import time

        client = self._load()
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with open(path, "rb") as handle:
                    response = client.audio.transcriptions.create(
                        model=self.model_name, language=self.language, file=handle
                    )
                return str(response.text)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status in self.RETRYABLE_STATUS and attempt < self.MAX_ATTEMPTS:
                    time.sleep(2**attempt)
                    continue
                raise


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
                "The CTC aligner needs ctc-forced-aligner: "
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
    """The ASR engine named by ``settings.ASR_BACKEND``.

    The stub recognizer FABRICATES text, and this factory is the one gate every
    ingest path goes through — the prod-settings guard cannot see a worker that
    booted with dev settings, so the stub is refused here too unless the run
    opts in with ``ALLOW_STUB_ENGINES=true`` (tests and dev smoke only).
    """
    backend = getattr(settings, "ASR_BACKEND", "stub")
    if backend == "stub":
        if os.environ.get("ALLOW_STUB_ENGINES", "").strip().lower() != "true":
            raise RuntimeError(
                "ASR_BACKEND='stub' fabricates transcript text; refusing to transcribe. "
                "Set ASR_BACKEND=cohere (or faster-whisper), or ALLOW_STUB_ENGINES=true "
                "for a test/dev run whose data never ships."
            )
        return StubASR()
    if backend == "faster-whisper":
        return FasterWhisperASR()
    if backend == "cohere":
        return CohereASR()
    raise ValueError(f"Unknown ASR_BACKEND: {backend!r}")


def get_aligner() -> Aligner:
    """The aligner named by ``ALIGNER_BACKEND``, defaulting to the ASR pairing.

    Any real ASR backend pairs with the CTC forced aligner: it re-derives word
    timings acoustically (``needs_words = False``), which also means an
    API-backed recognizer like Cohere is only called once per segment. Pairing
    a ``needs_words`` aligner with ``cohere`` would re-call the API in the
    align stage — acceptable only in tests where the client is mocked.
    """
    asr = getattr(settings, "ASR_BACKEND", "stub")
    backend = os.environ.get("ALIGNER_BACKEND") or ("stub" if asr == "stub" else "ctc")
    if backend == "stub":
        return StubAligner()
    if backend == "ctc":
        return CTCAligner()
    raise ValueError(f"Unknown ALIGNER_BACKEND: {backend!r}")
