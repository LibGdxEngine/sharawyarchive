"""The seven ingestion stages, as Celery tasks and as plain callables.

Every stage is:

* **resumable** — it checks what is already in the database (and in object
  storage) and raises :class:`StageSkipped` instead of redoing work, so a full
  re-run over a finished corpus is a fast no-op (project rule 6);
* **accounted for** — each attempt writes one ``PipelineRun`` row
  (``running`` → ``completed`` / ``skipped`` / ``failed`` with the traceback);
* **non-fatal** — a failure marks the segment ``failed`` and returns
  ``ok=False``; it never raises out of the task, so a batch keeps going.

Each stage exists twice: ``do_<stage>()`` is the synchronous function (used by
``pipeline.run`` and by the tests), and the Celery task of the same name wraps
it. Task names are the strings Django dispatches by
(``send_task('pipeline.ingest', ...)``) — renaming one is a breaking change.

Idempotency contract per stage
-------------------------------

Each stage guards against being run twice by checking for its own completed
output, not a shared ``sha256`` column.  The exact guard per stage is:

* **ingest** — ``sha256_file(path)`` → ``AudioAsset.sha256``; an existing asset
  whose segment is still alive returns the existing ``IngestedFile`` with
  ``created=False`` and skips all database writes.
* **transcode** — a completed ``PipelineRun`` row for this segment at
  ``stage=TRANSCODE`` *and* the Opus object already present in object storage →
  ``StageSkipped``.  Both conditions must hold: a run row without the object
  (upload interrupted) is re-executed.
* **transcribe** — an existing ``Transcript`` row for this segment →
  ``StageSkipped``.
* **align** — existing ``TranscriptWord`` rows on the segment's transcript →
  ``StageSkipped``.
* **chunk** — an existing ``Chunk`` row on the segment's transcript →
  ``StageSkipped``.
* **embed** — ``Chunk.embedding`` non-null for every pending chunk → ``StageSkipped``.
* **index_segment** — ``Segment.status == INDEXED`` → ``StageSkipped``.

Checking for a stage's own output (rather than a shared flag) means the stage
only skips when *its* work is genuinely done; partial writes (process killed
mid-stage) are automatically retried on the next run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from celery import chain
from django.utils import timezone

from pipeline.celery_app import app
from pipeline.chunking import WordSpan, plan_chunks
from pipeline.django_setup import setup_django
from pipeline.engines import ASRWord, get_aligner, get_asr_engine
from pipeline.parsers import ParseResult, audio_files, parse_filename

# Django has to be configured before any model class is imported, which is why
# the ORM imports below sit under a statement (ruff E402 is waived for this file
# in pipeline/pyproject.toml).
setup_django()

from corpus import storage
from corpus.arabic import normalize_for_index
from corpus.embeddings import get_embedder
from corpus.models import (
    AudioAsset,
    Chunk,
    PipelineRun,
    PipelineRunStatus,
    Segment,
    SegmentKind,
    SegmentStatus,
    Source,
    Transcript,
    TranscriptWord,
)
from quran.models import Surah

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

OPUS_BITRATE = 32_000
OPUS_SAMPLE_RATE = 48_000
WAVEFORM_BUCKETS = 800
WAVEFORM_SAMPLE_RATE = 8_000
HASH_BLOCK_BYTES = 1 << 20
MAX_WORD_CHARS = 100

INGEST = "ingest"
TRANSCODE = "transcode"
TRANSCRIBE = "transcribe"
ALIGN = "align"
CHUNK = "chunk"
EMBED = "embed"
INDEX = "index_segment"


class StageSkipped(Exception):
    """Raised by a stage body when its output already exists."""


@dataclass(frozen=True)
class StageResult:
    """Outcome of one stage attempt."""

    ok: bool
    skipped: bool
    detail: str = ""


@dataclass(frozen=True)
class IngestedFile:
    """One audio file the ingest accepted, with the local path stages need."""

    segment_id: int
    local_path: str
    created: bool


# --------------------------------------------------------------------------- #
# bookkeeping
# --------------------------------------------------------------------------- #


def _finish(run: PipelineRun, status: str, detail: str) -> None:
    run.status = status
    run.detail = detail
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "detail", "finished_at"])


def _run_stage(stage: str, segment_id: int, body: Callable[[], str]) -> StageResult:
    """Run ``body`` inside a ``PipelineRun``, converting failures into a result."""
    if not Segment.objects.filter(pk=segment_id).exists():
        # A queued task can outlive its segment; a dangling FK would be an
        # IntegrityError escaping the task, which is exactly what must not happen.
        detail = f"segment {segment_id} no longer exists"
        logger.error("stage %s skipped: %s", stage, detail)
        PipelineRun.objects.create(
            stage=stage,
            status=PipelineRunStatus.FAILED,
            detail=detail,
            finished_at=timezone.now(),
        )
        return StageResult(ok=False, skipped=False, detail=detail)

    run = PipelineRun.objects.create(
        stage=stage, segment_id=segment_id, status=PipelineRunStatus.RUNNING
    )
    try:
        detail = body()
    except StageSkipped as exc:
        _finish(run, PipelineRunStatus.SKIPPED, str(exc))
        return StageResult(ok=True, skipped=True, detail=str(exc))
    except Exception:
        formatted = traceback.format_exc()
        _finish(run, PipelineRunStatus.FAILED, formatted)
        Segment.objects.filter(pk=segment_id).update(status=SegmentStatus.FAILED)
        logger.error("stage %s failed for segment %s\n%s", stage, segment_id, formatted)
        return StageResult(ok=False, skipped=False, detail=formatted)
    _finish(run, PipelineRunStatus.COMPLETED, detail)
    return StageResult(ok=True, skipped=False, detail=detail)


def _ingest_detail(segment_id: int) -> dict:
    """The JSON detail written by the ingest stage for this segment."""
    run = (
        PipelineRun.objects.filter(
            segment_id=segment_id, stage=INGEST, status=PipelineRunStatus.COMPLETED
        )
        .order_by("-started_at")
        .first()
    )
    if run is None or not run.detail:
        return {}
    try:
        return json.loads(run.detail)
    except json.JSONDecodeError:
        return {}


def resolve_local_path(segment_id: int, local_path: str | None = None) -> str:
    """The path of the original file: the kwarg if given, else the ingest record.

    The source folder is not object storage, so the path never becomes part of
    the data model — it is passed from stage to stage and, as a fallback for
    workers that lost it, recovered from the ingest ``PipelineRun`` detail.
    """
    if local_path:
        return local_path
    recorded = _ingest_detail(segment_id).get("local_path")
    if not recorded:
        raise FileNotFoundError(f"no source path recorded for segment {segment_id}")
    return str(recorded)


# --------------------------------------------------------------------------- #
# ffmpeg helpers
# --------------------------------------------------------------------------- #


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(HASH_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_duration_ms(path: Path | str) -> int:
    """Duration in integer milliseconds. Raises on anything ffprobe dislikes."""
    completed = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    value = completed.stdout.strip()
    if not value or value == "N/A":
        raise ValueError(f"ffprobe reported no duration for {path}")
    return int(round(float(value) * 1000))


def waveform_peaks(path: Path | str, buckets: int = WAVEFORM_BUCKETS) -> list[float]:
    """``buckets`` peak amplitudes in 0-1, for the frontend waveform/scrubber."""
    import numpy as np

    completed = subprocess.run(
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(WAVEFORM_SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
        check=True,
    )
    samples = np.frombuffer(completed.stdout, dtype="<i2")
    if samples.size == 0:
        return [0.0] * buckets
    peaks = np.array(
        [
            int(np.abs(part.astype(np.int32)).max()) if part.size else 0
            for part in np.array_split(samples, buckets)
        ],
        dtype=np.float64,
    )
    loudest = peaks.max() or 1.0
    return [round(float(value / loudest), 4) for value in peaks]


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #


def _segment_surah_id(surah: int | None) -> int | None:
    """The FK value, but only when that surah has actually been imported.

    ``import_quran`` may not have run yet in a dev environment; a parsed surah
    number that has no row stays in the ingest ``PipelineRun`` detail rather
    than breaking the whole file on a foreign key violation.
    """
    if surah is None:
        return None
    return surah if Surah.objects.filter(number=surah).exists() else None


def _ingest_one(
    path: Path, parsed: ParseResult, source_title: str, default_kind: str
) -> IngestedFile:
    sha256 = sha256_file(path)
    asset = AudioAsset.objects.filter(sha256=sha256).first()
    if asset is not None:
        existing = asset.segments.order_by("id").first()
        if existing is not None:
            return IngestedFile(segment_id=existing.pk, local_path=str(path), created=False)

    duration_ms = probe_duration_ms(path)
    kind = parsed.kind or default_kind
    source, _ = Source.objects.get_or_create(title=source_title, defaults={"kind": kind})
    if asset is None:
        asset = AudioAsset.objects.create(
            # The final Opus key from the start: transcode uploads to exactly
            # this key, so the asset never points at a path that will move.
            storage_key=storage.audio_key(sha256),
            duration_ms=duration_ms,
            mime="audio/opus",
            sha256=sha256,
            # Provisional — replaced with the Opus size by the transcode stage.
            size_bytes=path.stat().st_size,
        )
    segment = Segment.objects.create(
        source=source,
        kind=kind,
        surah_id=_segment_surah_id(parsed.surah),
        ayah_start=parsed.ayah_start,
        ayah_end=parsed.ayah_end,
        audio=asset,
        ordinal=parsed.ordinal or 0,
        duration_ms=duration_ms,
        title=path.stem[:255],
        status=SegmentStatus.PENDING,
    )
    PipelineRun.objects.create(
        stage=INGEST,
        segment=segment,
        status=PipelineRunStatus.COMPLETED,
        detail=json.dumps(
            {
                "local_path": str(path),
                "sha256": sha256,
                "pattern": parsed.pattern_name,
                "surah": parsed.surah,
                "ayah_start": parsed.ayah_start,
                "ayah_end": parsed.ayah_end,
                "ordinal": parsed.ordinal,
                "duration_ms": duration_ms,
            },
            ensure_ascii=False,
        ),
        finished_at=timezone.now(),
    )
    return IngestedFile(segment_id=segment.pk, local_path=str(path), created=True)


def do_ingest(
    folder: str,
    source_title: str,
    default_kind: str,
    limit: int | None = None,
    surah: int | None = None,
) -> list[IngestedFile]:
    """Walk ``folder``, create ``Segment`` rows, return what to process.

    Already-ingested files (same sha256) come back too, flagged
    ``created=False``, so a re-run resumes them instead of ignoring them.
    Unparseable names are skipped and files ffprobe cannot read are recorded as
    failed ``PipelineRun`` rows — neither aborts the batch.
    """
    if default_kind not in SegmentKind.values:
        raise ValueError(f"kind must be one of {SegmentKind.values}, got {default_kind!r}")

    batch = PipelineRun.objects.create(stage=INGEST, status=PipelineRunStatus.RUNNING)
    files: list[IngestedFile] = []
    unparseable = 0
    failed = 0
    try:
        for path in audio_files(folder):
            if limit is not None and len(files) >= limit:
                break
            parsed = parse_filename(path.name)
            if parsed is None:
                unparseable += 1
                logger.warning("unparseable filename, skipped: %s", path)
                PipelineRun.objects.create(
                    stage=INGEST,
                    status=PipelineRunStatus.SKIPPED,
                    detail=f"unparseable filename: {path}",
                    finished_at=timezone.now(),
                )
                continue
            if surah is not None and parsed.surah != surah:
                continue
            try:
                files.append(_ingest_one(path, parsed, source_title, default_kind))
            except Exception:
                failed += 1
                formatted = traceback.format_exc()
                logger.error("ingest failed for %s\n%s", path, formatted)
                PipelineRun.objects.create(
                    stage=INGEST,
                    status=PipelineRunStatus.FAILED,
                    detail=f"file: {path}\n{formatted}",
                    finished_at=timezone.now(),
                )
    except Exception:
        _finish(batch, PipelineRunStatus.FAILED, traceback.format_exc())
        raise

    _finish(
        batch,
        PipelineRunStatus.COMPLETED,
        json.dumps(
            {
                "folder": str(folder),
                "source_title": source_title,
                "kind": default_kind,
                "accepted": len(files),
                "created": sum(1 for item in files if item.created),
                "unparseable": unparseable,
                "failed": failed,
            },
            ensure_ascii=False,
        ),
    )
    return files


# --------------------------------------------------------------------------- #
# per-segment stages
# --------------------------------------------------------------------------- #


def _transcode(segment: Segment, local_path: str) -> str:
    key = segment.audio.storage_key
    already = PipelineRun.objects.filter(
        segment=segment, stage=TRANSCODE, status=PipelineRunStatus.COMPLETED
    ).exists()
    if already and storage.object_exists(key):
        raise StageSkipped(f"{key} already uploaded")

    with tempfile.TemporaryDirectory(prefix="shaarawy-transcode-") as tmp:
        opus_path = Path(tmp) / "audio.opus"
        subprocess.run(
            [
                FFMPEG,
                "-nostdin",
                "-y",
                "-v",
                "error",
                "-i",
                local_path,
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-ac",
                "1",
                str(opus_path),
            ],
            capture_output=True,
            check=True,
        )
        size_bytes = opus_path.stat().st_size
        storage.upload_file(key, str(opus_path), "audio/opus")

    peaks = waveform_peaks(local_path)
    storage.upload_bytes(
        storage.waveform_key(segment.audio.sha256),
        json.dumps({"peaks": peaks, "duration_ms": segment.duration_ms}).encode(),
        "application/json",
    )
    AudioAsset.objects.filter(pk=segment.audio_id).update(
        size_bytes=size_bytes, bitrate=OPUS_BITRATE, sample_rate=OPUS_SAMPLE_RATE
    )
    return f"{key} ({size_bytes} bytes) + {len(peaks)} waveform peaks"


def _transcribe(segment: Segment, local_path: str) -> str:
    if Transcript.objects.filter(segment=segment).exists():
        raise StageSkipped("transcript already exists")

    engine = get_asr_engine()
    words = engine.transcribe(local_path, duration_ms=int(segment.duration_ms))
    if not words:
        raise ValueError(f"{engine.name} produced no words for segment {segment.pk}")

    raw_text = " ".join(word.text for word in words)
    scored = [word.confidence for word in words if word.confidence is not None]
    Transcript.objects.create(
        segment=segment,
        engine=engine.name,
        engine_version=engine.version,
        language="ar",
        raw_text=raw_text,
        text_normalized=normalize_for_index(raw_text),
        confidence=sum(scored) / len(scored) if scored else None,
        word_count=len(words),
        version=1,
    )
    Segment.objects.filter(pk=segment.pk).update(status=SegmentStatus.TRANSCRIBED)
    return f"{len(words)} words via {engine.name} {engine.version}"


def _align(segment: Segment, local_path: str) -> str:
    transcript = Transcript.objects.get(segment=segment)
    if transcript.words.exists():
        raise StageSkipped("words already aligned")

    aligner = get_aligner()
    words: Sequence[ASRWord] | None = None
    if aligner.needs_words:
        # The stub aligner only refines existing timings, and the stub ASR is
        # deterministic, so re-running it here is free and keeps the two stages
        # independent. A real CTC aligner sets needs_words = False.
        words = get_asr_engine().transcribe(local_path, duration_ms=int(segment.duration_ms))

    aligned = aligner.align(
        local_path, transcript.raw_text, words, duration_ms=int(segment.duration_ms)
    )
    if not aligned:
        raise ValueError(f"{aligner.name} aligned no words for segment {segment.pk}")

    TranscriptWord.objects.bulk_create(
        [
            TranscriptWord(
                transcript=transcript,
                idx=index,
                text=word.text[:MAX_WORD_CHARS],
                start_ms=int(word.start_ms),
                end_ms=int(word.end_ms),
                confidence=word.confidence,
            )
            for index, word in enumerate(aligned)
        ]
    )
    Segment.objects.filter(pk=segment.pk).update(status=SegmentStatus.ALIGNED)
    return f"{len(aligned)} words via {aligner.name} {aligner.version}"


def ayah_starts_for(segment: Segment, word_count: int) -> list[int] | None:
    """Word indices where an ayah begins, or ``None`` when they are unknown.

    Only recitation segments with a known ayah range get boundaries. Until the
    aligner can map ayah text onto the audio, the ayat are assumed to be spoken
    at an even pace, which is enough to keep chunk edges off mid-ayah positions;
    replace this with real boundaries when alignment against ``quran.Ayah``
    lands (Phase 6 corrections rely on the same mapping).
    """
    if segment.kind != SegmentKind.RECITATION:
        return None
    if not segment.ayah_start or not segment.ayah_end:
        return None
    count = int(segment.ayah_end) - int(segment.ayah_start) + 1
    if count < 1 or word_count == 0:
        return None
    # TODO(real-alignment): replace with real ayah-text CTC alignment (Phase 6)
    logger.warning(
        "segment %s (recitation, ayahs %s-%s): using even-pace placeholder ayah "
        "boundaries — transcription accuracy will be limited until real alignment lands",
        segment.pk,
        segment.ayah_start,
        segment.ayah_end,
    )
    return sorted({round(index * word_count / count) for index in range(count)})


def _chunk(segment: Segment) -> str:
    transcript = Transcript.objects.get(segment=segment)
    if Chunk.objects.filter(transcript=transcript).exists():
        raise StageSkipped("chunks already planned")

    words = list(transcript.words.order_by("idx"))
    if not words:
        raise ValueError(f"segment {segment.pk} has no aligned words to chunk")

    spans = [WordSpan(word.text, int(word.start_ms), int(word.end_ms)) for word in words]
    plans = plan_chunks(
        spans, kind=segment.kind, ayah_starts=ayah_starts_for(segment, len(spans))
    )
    rows = []
    for index, plan in enumerate(plans):
        text = " ".join(word.text for word in plan.words(spans))
        rows.append(
            Chunk(
                transcript=transcript,
                idx=index,
                text=text,
                text_normalized=normalize_for_index(text),
                start_ms=plan.start_ms,
                end_ms=plan.end_ms,
            )
        )
    Chunk.objects.bulk_create(rows)
    return f"{len(rows)} chunks from {len(words)} words"


def _embed(segment: Segment) -> str:
    transcript = Transcript.objects.get(segment=segment)
    pending = list(
        Chunk.objects.filter(transcript=transcript, embedding__isnull=True).order_by("idx")
    )
    if not pending:
        raise StageSkipped("every chunk already has an embedding")

    # The normalized form is embedded so passages and queries (which are
    # normalized before search, rule 2) meet in the same space.
    vectors = get_embedder().embed_passages([row.text_normalized for row in pending])
    for row, vector in zip(pending, vectors, strict=True):
        row.embedding = vector
    Chunk.objects.bulk_update(pending, ["embedding"])
    return f"{len(pending)} chunks embedded"


def _search_services():  # noqa: ANN202 - the search app's module, resolved late
    """Import ``search.services`` at call time.

    Late on purpose: it keeps the Meilisearch client out of every pipeline
    import, and it gives the tests a single seam to substitute a fake indexer
    without touching the search app.
    """
    from search import services

    return services


def _index(segment: Segment) -> str:
    if segment.status == SegmentStatus.INDEXED:
        raise StageSkipped("segment already indexed")

    transcript = Transcript.objects.get(segment=segment)
    # A queryset, not a list: search.services.index_chunks select_relates the
    # segment off it instead of firing two queries per chunk.
    chunks = Chunk.objects.filter(transcript=transcript).order_by("idx")
    count = chunks.count()
    if not count:
        raise ValueError(f"segment {segment.pk} has no chunks to index")

    services = _search_services()
    services.ensure_chunks_index()
    services.index_chunks(chunks)
    Segment.objects.filter(pk=segment.pk).update(status=SegmentStatus.INDEXED)
    return f"{count} chunks indexed"


# --------------------------------------------------------------------------- #
# synchronous stage entry points
# --------------------------------------------------------------------------- #


def do_transcode(segment_id: int, local_path: str | None = None) -> StageResult:
    def body() -> str:
        segment = Segment.objects.select_related("audio").get(pk=segment_id)
        return _transcode(segment, resolve_local_path(segment_id, local_path))

    return _run_stage(TRANSCODE, segment_id, body)


def do_transcribe(segment_id: int, local_path: str | None = None) -> StageResult:
    def body() -> str:
        segment = Segment.objects.get(pk=segment_id)
        return _transcribe(segment, resolve_local_path(segment_id, local_path))

    return _run_stage(TRANSCRIBE, segment_id, body)


def do_align(segment_id: int, local_path: str | None = None) -> StageResult:
    def body() -> str:
        segment = Segment.objects.get(pk=segment_id)
        return _align(segment, resolve_local_path(segment_id, local_path))

    return _run_stage(ALIGN, segment_id, body)


def do_chunk(segment_id: int) -> StageResult:
    def body() -> str:
        return _chunk(Segment.objects.get(pk=segment_id))

    return _run_stage(CHUNK, segment_id, body)


def do_embed(segment_id: int) -> StageResult:
    def body() -> str:
        return _embed(Segment.objects.get(pk=segment_id))

    return _run_stage(EMBED, segment_id, body)


def do_index_segment(segment_id: int) -> StageResult:
    def body() -> str:
        return _index(Segment.objects.get(pk=segment_id))

    return _run_stage(INDEX, segment_id, body)


# --------------------------------------------------------------------------- #
# Celery tasks
# --------------------------------------------------------------------------- #
#
# Every task takes the previous link's result as its first positional argument
# (that is how Celery chains work) and short-circuits on False, so one failed
# stage stops that segment's chain without touching any other segment.


@app.task(name="pipeline.ingest")
def ingest(
    previous: object = None,
    *,
    folder: str,
    source_title: str,
    kind: str,
    limit: int | None = None,
    surah: int | None = None,
) -> list[int]:
    """Walk the folder and fan out one stage chain per audio file."""
    files = do_ingest(folder, source_title, kind, limit=limit, surah=surah)
    for item in files:
        chain(
            transcode.s(segment_id=item.segment_id, local_path=item.local_path),
            transcribe.s(segment_id=item.segment_id, local_path=item.local_path),
            align.s(segment_id=item.segment_id, local_path=item.local_path),
            chunk.s(segment_id=item.segment_id),
            embed.s(segment_id=item.segment_id),
            index_segment.s(segment_id=item.segment_id),
        ).apply_async()
    return [item.segment_id for item in files]


@app.task(name="pipeline.transcode")
def transcode(
    previous: object = None, *, segment_id: int, local_path: str | None = None
) -> bool:
    if previous is False:
        return False
    return do_transcode(segment_id, local_path).ok


@app.task(name="pipeline.transcribe")
def transcribe(
    previous: object = None, *, segment_id: int, local_path: str | None = None
) -> bool:
    if previous is False:
        return False
    return do_transcribe(segment_id, local_path).ok


@app.task(name="pipeline.align")
def align(previous: object = None, *, segment_id: int, local_path: str | None = None) -> bool:
    if previous is False:
        return False
    return do_align(segment_id, local_path).ok


@app.task(name="pipeline.chunk")
def chunk(previous: object = None, *, segment_id: int) -> bool:
    if previous is False:
        return False
    return do_chunk(segment_id).ok


@app.task(name="pipeline.embed")
def embed(previous: object = None, *, segment_id: int) -> bool:
    if previous is False:
        return False
    return do_embed(segment_id).ok


@app.task(name="pipeline.index_segment")
def index_segment(previous: object = None, *, segment_id: int) -> bool:
    if previous is False:
        return False
    return do_index_segment(segment_id).ok
