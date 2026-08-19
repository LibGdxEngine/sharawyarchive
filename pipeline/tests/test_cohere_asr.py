"""CohereASR engine tests.

The ``cohere`` SDK is mocked at the module level (it is a worker-only
dependency, deliberately absent from the test environment), so nothing here
touches the network. The audio-preparation paths use real ffmpeg on tiny
synthesized files.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pipeline import run, stages
from pipeline.engines import CohereASR, MissingEngineDependency, get_asr_engine

from .conftest import synthesize_audio

ARABIC_TEXT = "الصبر مفتاح الفرج والايمان نور القلوب"


@dataclass
class FakeCall:
    model: str
    language: str
    filename: str


@dataclass
class FakeTranscriptions:
    """Stands in for ``client.audio.transcriptions``: scripted texts/errors."""

    texts: list[str] = field(default_factory=lambda: [ARABIC_TEXT])
    errors: list[Exception] = field(default_factory=list)
    repeat_last: bool = True
    calls: list[FakeCall] = field(default_factory=list)

    def create(self, *, model: str, language: str, file):  # noqa: ANN001, ANN201
        self.calls.append(FakeCall(model, language, Path(file.name).name))
        assert file.read(4)  # the upload must be a real, readable file
        if self.errors:
            raise self.errors.pop(0)
        if len(self.texts) > 1:
            return types.SimpleNamespace(text=self.texts.pop(0))
        if self.repeat_last:
            return types.SimpleNamespace(text=self.texts[0])
        return types.SimpleNamespace(text=self.texts.pop(0))


@pytest.fixture
def fake_cohere(monkeypatch: pytest.MonkeyPatch) -> FakeTranscriptions:
    """Install a fake ``cohere`` module and a CO_API_KEY."""
    transcriptions = FakeTranscriptions()
    module = types.ModuleType("cohere")
    module.ClientV2 = lambda: types.SimpleNamespace(  # type: ignore[attr-defined]
        audio=types.SimpleNamespace(transcriptions=transcriptions)
    )
    monkeypatch.setitem(sys.modules, "cohere", module)
    monkeypatch.setenv("CO_API_KEY", "test-key")
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return transcriptions


@pytest.fixture
def wav_file(tmp_path: Path) -> Path:
    return synthesize_audio(tmp_path / "sample.wav", seconds=2)


def test_defaults_to_the_latest_arabic_model(fake_cohere: FakeTranscriptions, wav_file: Path):
    words = CohereASR().transcribe(str(wav_file), duration_ms=2000)

    call = fake_cohere.calls[0]
    assert call.model == "cohere-transcribe-arabic-07-2026"
    assert call.language == "ar"
    assert [word.text for word in words] == ARABIC_TEXT.split()


def test_env_overrides_model_and_language(
    fake_cohere: FakeTranscriptions, wav_file: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("COHERE_ASR_MODEL", "cohere-transcribe-03-2026")
    monkeypatch.setenv("COHERE_ASR_LANGUAGE", "en")
    engine = CohereASR()
    engine.transcribe(str(wav_file), duration_ms=2000)

    assert fake_cohere.calls[0].model == "cohere-transcribe-03-2026"
    assert fake_cohere.calls[0].language == "en"
    assert engine.version == "cohere-transcribe-03-2026"


def test_placeholder_timings_are_even_integer_ms(
    fake_cohere: FakeTranscriptions, wav_file: Path
):
    duration_ms = 6000
    words = CohereASR().transcribe(str(wav_file), duration_ms=duration_ms)

    assert all(isinstance(w.start_ms, int) and isinstance(w.end_ms, int) for w in words)
    assert all(w.confidence is None for w in words)
    starts = [w.start_ms for w in words]
    assert starts == sorted(starts) and starts[0] == 0
    assert all(w.start_ms < w.end_ms <= duration_ms for w in words)


def test_an_accepted_small_file_is_uploaded_as_is(
    fake_cohere: FakeTranscriptions, wav_file: Path
):
    CohereASR().transcribe(str(wav_file), duration_ms=2000)
    assert fake_cohere.calls[0].filename == "sample.wav"


def test_an_opus_master_is_reencoded_to_mp3(
    fake_cohere: FakeTranscriptions, tmp_path: Path
):
    import subprocess

    opus = tmp_path / "master.opus"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2", "-c:a", "libopus", "-b:a", "32k", str(opus)],
        check=True,
        capture_output=True,
    )
    CohereASR().transcribe(str(opus), duration_ms=2000)
    assert fake_cohere.calls[0].filename == "upload.mp3"


def test_oversize_audio_is_split_and_texts_concatenate_in_order(
    fake_cohere: FakeTranscriptions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A 6s mono 32k mp3 is ~24KB; a 12KB cap forces the split path.
    monkeypatch.setenv("COHERE_MAX_UPLOAD_BYTES", "12000")
    scripted = ["جزء اول", "جزء ثان", "جزء ثالث", "جزء رابع", "جزء خامس"]
    fake_cohere.texts = list(scripted)
    fake_cohere.repeat_last = False
    audio = synthesize_audio(tmp_path / "long.mp3", seconds=6)

    words = CohereASR().transcribe(str(audio), duration_ms=6000)

    part_count = len(fake_cohere.calls)
    assert part_count >= 2
    assert [call.filename for call in fake_cohere.calls] == [
        f"part-{index:03d}.mp3" for index in range(part_count)
    ]
    expected = " ".join(scripted[:part_count]).split()
    assert [w.text for w in words] == expected


def test_rate_limits_are_retried(fake_cohere: FakeTranscriptions, wav_file: Path):
    throttled = Exception("slow down")
    throttled.status_code = 429  # type: ignore[attr-defined]
    fake_cohere.errors = [throttled]

    words = CohereASR().transcribe(str(wav_file), duration_ms=2000)

    assert len(fake_cohere.calls) == 2
    assert words


def test_retries_exhaust_and_raise(fake_cohere: FakeTranscriptions, wav_file: Path):
    def throttled() -> Exception:
        error = Exception("slow down")
        error.status_code = 429  # type: ignore[attr-defined]
        return error

    fake_cohere.errors = [throttled() for _ in range(CohereASR.MAX_ATTEMPTS)]
    with pytest.raises(Exception, match="slow down"):
        CohereASR().transcribe(str(wav_file), duration_ms=2000)
    assert len(fake_cohere.calls) == CohereASR.MAX_ATTEMPTS


def test_client_errors_are_not_retried(fake_cohere: FakeTranscriptions, wav_file: Path):
    bad_request = Exception("unsupported language")
    bad_request.status_code = 400  # type: ignore[attr-defined]
    fake_cohere.errors = [bad_request]

    with pytest.raises(Exception, match="unsupported language"):
        CohereASR().transcribe(str(wav_file), duration_ms=2000)
    assert len(fake_cohere.calls) == 1


def test_a_missing_api_key_is_a_clear_error(
    wav_file: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("CO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CO_API_KEY"):
        CohereASR().transcribe(str(wav_file), duration_ms=2000)


def test_a_missing_sdk_is_a_clear_error(wav_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CO_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "cohere", None)  # import cohere -> ImportError
    with pytest.raises(MissingEngineDependency, match="cohere"):
        CohereASR().transcribe(str(wav_file), duration_ms=2000)


def test_the_factory_serves_cohere(settings) -> None:  # noqa: ANN001
    settings.ASR_BACKEND = "cohere"
    assert isinstance(get_asr_engine(), CohereASR)


@pytest.mark.django_db
def test_end_to_end_with_a_mocked_cohere(
    fake_cohere: FakeTranscriptions,
    fake_search,  # noqa: ANN001 - conftest.FakeSearchServices
    tmp_path: Path,
    settings,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
):
    """The driver takes a segment to indexed with Cohere text + stub timings.

    The stub aligner ``needs_words``, so the align stage transcribes again —
    two API calls total, harmless with the mock; production pairs Cohere with
    the CTC aligner and calls the API once.
    """
    from corpus.models import Segment, SegmentStatus, Transcript

    settings.ASR_BACKEND = "cohere"
    monkeypatch.setenv("ALIGNER_BACKEND", "stub")
    folder = tmp_path / "corpus"
    folder.mkdir()
    synthesize_audio(folder / "002 - cohere e2e - 01.mp3", seconds=4)

    items = stages.do_ingest(str(folder), "cohere e2e", "khawatir")
    for item in items:
        outcome, _detail = run.process_segment(item.segment_id, item.local_path)
        assert outcome == "processed"

    segment = Segment.objects.get(pk=items[0].segment_id)
    assert segment.status == SegmentStatus.INDEXED
    transcript = Transcript.objects.get(segment=segment)
    assert transcript.engine == "cohere-transcribe"
    assert transcript.engine_version == "cohere-transcribe-arabic-07-2026"
    assert transcript.raw_text == ARABIC_TEXT
    words = list(transcript.words.order_by("idx"))
    assert [w.text for w in words] == ARABIC_TEXT.split()
    assert all(isinstance(w.start_ms, int) and w.end_ms > w.start_ms for w in words)

    # Idempotent re-run: nothing new happens, no further API calls.
    calls_before = len(fake_cohere.calls)
    outcome, _detail = run.process_segment(items[0].segment_id, items[0].local_path)
    assert outcome == "skipped"
    assert len(fake_cohere.calls) == calls_before
