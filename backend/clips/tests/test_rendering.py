"""The renderer, against the real ffmpeg and the real bucket.

The point of these tests is the artefact: a file that ffprobe agrees is a
1080x1920 H.264 card with AAC audio of exactly the requested length. Everything
else here defends the two promises the API makes on top of it — a finished clip
is never re-rendered, and a broken one comes back as a ``failed`` row rather
than an exception nobody sees.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from api.tests.factories import Archive
from clips import rendering
from clips.models import Clip, ClipOutput, ClipPreset, ClipStatus
from corpus import storage

from .conftest import Renderable, ffprobe

pytestmark = pytest.mark.django_db

START_MS = 5_000
END_MS = 25_000
SPAN_MS = END_MS - START_MS


def _clip(
    renderable: Renderable,
    preset: str = ClipPreset.NIGHT,
    output: str = ClipOutput.VIDEO,
) -> Clip:
    return Clip.objects.create(
        segment=renderable.segment,
        start_ms=START_MS,
        end_ms=END_MS,
        preset=preset,
        output=output,
    )


def _download(key: str, path: Path) -> Path:
    storage.get_s3_client().download_file(settings.AUDIO_S3_BUCKET, key, str(path))
    return path


def _head(key: str) -> dict:
    return storage.get_s3_client().head_object(Bucket=settings.AUDIO_S3_BUCKET, Key=key)


# --- the artefact ------------------------------------------------------------


def test_a_clip_renders_to_a_vertical_h264_card(
    renderable: Renderable, tmp_path: Path, api: APIClient
) -> None:
    clip = _clip(renderable)

    rendering.render_clip(clip)

    clip.refresh_from_db()
    assert clip.status == ClipStatus.DONE
    assert clip.error == ''
    assert clip.storage_key == storage.clip_key(
        renderable.segment.pk, START_MS, END_MS, ClipPreset.NIGHT, clip.output
    )

    probe = ffprobe(_download(clip.storage_key, tmp_path / 'rendered.mp4'))
    streams = {stream['codec_type']: stream for stream in probe['streams']}
    assert streams['video']['codec_name'] == 'h264'
    assert (streams['video']['width'], streams['video']['height']) == (1080, 1920)
    assert streams['audio']['codec_name'] == 'aac'
    # -ss/-to trimmed the source, and the finite wave/audio ended the infinite
    # colour source with it.
    assert abs(float(probe['format']['duration']) * 1000 - SPAN_MS) <= 500

    body = api.get(f'/api/clips/{clip.pk}/').json()
    assert body['status'] == 'done'
    assert body['output'] == ClipOutput.VIDEO
    assert 'X-Amz-Signature=' in body['video_url']
    assert body['audio_url'] is None


def test_an_audio_clip_renders_to_an_m4a_that_carries_the_transcript(
    renderable: Renderable, tmp_path: Path, api: APIClient
) -> None:
    clip = _clip(renderable, output=ClipOutput.AUDIO)

    rendering.render_clip(clip)

    clip.refresh_from_db()
    assert clip.status == ClipStatus.DONE
    assert clip.storage_key.endswith('.m4a')

    probe = ffprobe(_download(clip.storage_key, tmp_path / 'rendered.m4a'))
    assert probe['streams'][0]['codec_name'] == 'aac'
    assert abs(float(probe['format']['duration']) * 1000 - SPAN_MS) <= 500
    # The machine transcript travels in the lyrics metadata, with its mark.
    assert 'lyrics' in probe['format']['tags']
    assert rendering.MACHINE_TRANSCRIPT_MARK in probe['format']['tags']['lyrics']

    body = api.get(f'/api/clips/{clip.pk}/').json()
    assert body['output'] == ClipOutput.AUDIO
    assert body['video_url'] is None
    assert 'X-Amz-Signature=' in body['audio_url']


def test_a_finished_clip_is_never_rendered_twice(
    renderable: Renderable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotence is what makes a redelivered task free."""
    clip = _clip(renderable)
    rendering.render_clip(clip)
    clip.refresh_from_db()
    before = _head(clip.storage_key)
    commands: list[dict] = []
    monkeypatch.setattr(
        rendering, 'ffmpeg_command', lambda **kwargs: commands.append(kwargs)
    )

    rendering.render_clip(Clip.objects.get(pk=clip.pk))

    after = _head(clip.storage_key)
    assert commands == []
    assert (after['ETag'], after['LastModified']) == (before['ETag'], before['LastModified'])


# --- failure -----------------------------------------------------------------


def test_audio_that_is_not_in_the_bucket_fails_the_clip(archive: Archive) -> None:
    """The archive fixture's audio was never uploaded, which is the point."""
    clip = Clip.objects.create(
        segment=archive.segment,
        start_ms=125_000,
        end_ms=145_000,
        preset=ClipPreset.CLASSIC,
    )

    rendering.render_clip(clip)  # must not raise: the row is the error channel

    clip.refresh_from_db()
    assert clip.status == ClipStatus.FAILED
    assert 'Traceback' in clip.error
    assert clip.storage_key == ''


def test_a_corrupt_audio_object_fails_with_ffmpegs_own_words(
    renderable: Renderable,
) -> None:
    storage.upload_bytes(
        renderable.audio.storage_key, b'this is not audio, not even close\n' * 64, 'audio/ogg'
    )
    clip = _clip(renderable)

    rendering.render_clip(clip)

    clip.refresh_from_db()
    assert clip.status == ClipStatus.FAILED
    assert 'render failed' in clip.error
    assert 'Invalid data found' in clip.error


def test_a_failed_render_can_be_retried(
    renderable: Renderable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``failed`` is not a terminal state — the row is reused, not abandoned."""
    clip = _clip(renderable)
    monkeypatch.setattr(rendering, 'FFMPEG', 'ffmpeg-that-does-not-exist')
    rendering.render_clip(clip)
    assert clip.status == ClipStatus.FAILED
    monkeypatch.undo()

    rendering.render_clip(Clip.objects.get(pk=clip.pk))

    clip.refresh_from_db()
    assert (clip.status, clip.error) == (ClipStatus.DONE, '')


# --- the pieces --------------------------------------------------------------


def test_only_the_words_inside_the_clip_reach_the_subtitles(
    renderable: Renderable,
) -> None:
    words = rendering.clip_words(_clip(renderable))

    assert len(words) == 20
    assert (words[0][1], words[-1][2]) == (5_000, 24_800)


def test_the_command_trims_the_audio_and_paints_the_preset() -> None:
    clip = Clip(start_ms=START_MS, end_ms=END_MS, preset=ClipPreset.NIGHT)

    command = rendering.ffmpeg_command(
        audio_path=Path('/tmp/source-audio'),
        ass_path=Path('/tmp/od:d/karaoke.ass'),
        output_path=Path('/tmp/clip.mp4'),
        preset=ClipPreset.NIGHT,
        clip=clip,
    )

    assert command[command.index('-ss') + 1] == '5.000'
    assert command[command.index('-to') + 1] == '25.000'
    # The trim options come before the input they apply to.
    assert command.index('-to') < command.index('-i')
    graph = command[command.index('-filter_complex') + 1]
    assert 'color=c=0x101312:s=1080x1920:r=30' in command
    # The animated wave is driven by the audio and composited over the colour,
    # then the karaoke card is burned on top.
    assert 'showwaves=s=1080x1920:mode=cline:rate=30:colors=0x3aad7a:scale=sqrt' in graph
    assert 'blend=all_mode=screen:shortest=1' in graph
    # A colon in the path would otherwise be read as a filter option separator.
    assert r'ass=/tmp/od\:d/karaoke.ass' in graph
    assert command[command.index('-c:v') + 1] == 'libx264'
    assert command[command.index('-c:a') + 1] == 'aac'
    assert {'-shortest', '-pix_fmt', '[v]'} <= set(command)


def test_the_audio_command_embeds_the_machine_transcript() -> None:
    clip = Clip(start_ms=START_MS, end_ms=END_MS, preset=ClipPreset.NIGHT)

    command = rendering.ffmpeg_audio_command(
        audio_path=Path('/tmp/source-audio'),
        output_path=Path('/tmp/clip.m4a'),
        clip=clip,
    )

    assert command[command.index('-ss') + 1] == '5.000'
    assert command[command.index('-to') + 1] == '25.000'
    # Audio only: no video encoder, no colour source, no subtitle filter.
    assert '-filter_complex' not in command
    assert '-c:v' not in command
    assert command[command.index('-c:a') + 1] == 'aac'
    assert any(part.startswith('lyrics=') for part in command)
    # The transcribed words ride along in the metadata, marked as ASR output.
    assert any(rendering.MACHINE_TRANSCRIPT_MARK in part for part in command)


def test_every_clip_carries_a_mark_the_deployment_can_set() -> None:
    # The default names this deployment's own host rather than a literal, so a
    # fork does not stamp somebody else's domain on its clips.
    assert urlparse(settings.SITE_BASE_URL).hostname in settings.CLIP_ATTRIBUTION
    assert settings.CLIP_ATTRIBUTION in rendering.attribution_text()

    with override_settings(CLIP_ATTRIBUTION='archive.example'):
        assert 'archive.example' in rendering.attribution_text()


def test_no_card_can_pass_the_machine_transcript_off_as_anything_else() -> None:
    """Project rule 1: ASR output is always marked, and a clip travels alone."""
    with override_settings(CLIP_ATTRIBUTION='archive.example'):
        assert rendering.MACHINE_TRANSCRIPT_MARK in rendering.attribution_text()
