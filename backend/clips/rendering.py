"""Turn a queued :class:`~clips.models.Clip` into a file in object storage.

Two outputs, two passes:

* **video** — one ffmpeg pass draws the card: the segment's audio trimmed with
  ``-ss/-to``, an animated waveform (``showwaves``, driven by the audio itself)
  composited over the preset's colour field, and the karaoke ASS file from
  :mod:`clips.subtitles` burned on with libass. H.264 + AAC.
* **audio** — one ffmpeg pass trims and re-encodes to AAC in an ``m4a``
  container, embedding the clipped transcript as ID3/lyrics metadata so the
  machine transcription travels with the file.

:func:`render_clip` is the entire contract of this module and it is deliberately
blunt about failure: it never raises. A render that dies leaves the row
``failed`` with the traceback in ``error`` for the API to report, because a
Celery task that explodes tells the person waiting on the clip nothing.

It is also idempotent — a finished clip whose object is still in the bucket is
returned untouched — so a redelivered task, a retried job, or a second worker
picking up the same id costs nothing.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import traceback
from pathlib import Path

from django.conf import settings

from corpus import storage
from corpus.models import TranscriptWord

from .models import Clip, ClipOutput, ClipStatus
from .subtitles import PRESETS, build_ass

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get('FFMPEG_BIN', 'ffmpeg')

FRAME_RATE = 30
FRAME_SIZE = '1080x1920'
VIDEO_CRF = '20'
AUDIO_BITRATE = '128k'
AUDIO_CONTAINER = 'm4a'
VIDEO_CONTENT_TYPE = 'video/mp4'
AUDIO_CONTENT_TYPE = 'audio/mp4'

MACHINE_TRANSCRIPT_MARK = 'نص آلي'
"""A clip card burns the machine transcript into a video that then travels
without us, which makes it the surface where project rule 1 matters most: ASR
output is never presented as anything but ASR output. The mark lives here, in
code, rather than in ``settings.CLIP_ATTRIBUTION``, so that a deployment
restamping the card with its own domain cannot drop it."""


def attribution_text() -> str:
    """The line along the bottom of every card: the machine-transcript mark,
    then whoever this deployment is.

    ``settings.CLIP_ATTRIBUTION`` defaults to the site's own host (see
    ``core.settings.base``) rather than a literal, because a clip that outlives
    the page it came from has to name an archive that actually exists. Read
    late, so ``override_settings`` in a test is honoured."""
    return f'{MACHINE_TRANSCRIPT_MARK} · {settings.CLIP_ATTRIBUTION}'


def _escape_filter_path(path: str) -> str:
    """Quote a path for use inside an ffmpeg filter argument.

    ``:`` separates filter options and ``\\`` escapes, so a temp directory with
    either in its name would silently rewrite the filtergraph.
    """
    return path.replace('\\', '\\\\').replace(':', r'\:').replace("'", r"\'")


def _run(command: list[str], *, what: str) -> None:
    """Run ffmpeg, and put its stderr in the exception when it fails.

    ``CalledProcessError`` alone says only "exit 1"; the reason a render failed
    is always in the last lines of ffmpeg's stderr, and that is what ends up in
    ``Clip.error``.
    """
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f'{what} failed (exit {completed.returncode})\n'
            f'{" ".join(command)}\n{completed.stderr.strip()[-2000:]}'
        )


def clip_words(clip: Clip) -> list[tuple[str, int, int]]:
    """The transcript words that overlap the clip, on the segment's timeline.

    Half-open overlap on both ends: a word straddling an edge belongs to the
    clip (:mod:`clips.subtitles` clamps it), because dropping it would leave the
    karaoke silent while the speaker is clearly mid-word.
    """
    rows = (
        TranscriptWord.objects.filter(
            transcript__segment_id=clip.segment_id,
            start_ms__lt=clip.end_ms,
            end_ms__gt=clip.start_ms,
        )
        .order_by('idx')
        .values_list('text', 'start_ms', 'end_ms')
    )
    return [(text, int(start), int(end)) for text, start, end in rows]


def clip_transcript_text(clip: Clip) -> str:
    """The clipped transcript as one plain line of prose, for audio metadata.

    Rule 1 travels with the file: the machine-transcript mark is prepended, so
    an audio export that lands in somebody's library still names its words as
    ASR output.
    """
    words = ' '.join(text for text, _start, _end in clip_words(clip)).strip()
    return f'{MACHINE_TRANSCRIPT_MARK}: {words}' if words else MACHINE_TRANSCRIPT_MARK


def _wave_colour(preset: str) -> str:
    """The waveform's line colour — the preset's spoken-word highlight, so the
    animated wave and the karaoke sweep share one palette."""
    return f'0x{PRESETS[preset].spoken.lstrip("#")}'


def ffmpeg_command(
    *, audio_path: Path, ass_path: Path, output_path: Path, preset: str, clip: Clip
) -> list[str]:
    """The video pass: trim, draw the wave over the preset colour, burn, encode."""
    background = PRESETS[preset].background.lstrip('#')
    return [
        FFMPEG,
        '-nostdin',
        '-y',
        '-v',
        'error',
        # Input options, so ffmpeg seeks instead of decoding-and-discarding.
        '-ss',
        f'{clip.start_ms / 1000:.3f}',
        '-to',
        f'{clip.end_ms / 1000:.3f}',
        '-i',
        str(audio_path),
        '-f',
        'lavfi',
        '-i',
        # 0x form, not '#': lavfi parses this string as a filtergraph.
        f'color=c=0x{background}:s={FRAME_SIZE}:r={FRAME_RATE}',
        '-filter_complex',
        # showwaves paints the wave on black; `blend=screen` turns that black
        # into the preset colour, and `ass` burns the karaoke card on top.
        #
        # The blend must happen in RGB. `screen` is an RGB operator, and on
        # yuv420p it screens the chroma planes as if they were colour channels
        # — which lifts U and V towards 255 and renders the whole card magenta
        # on a near-black preset. Verified against ffmpeg 5.1: gbrp in, blend,
        # yuv420p back out.
        f'[0:a]showwaves=s={FRAME_SIZE}:mode=cline:rate={FRAME_RATE}:'
        f'colors={_wave_colour(preset)}:scale=sqrt,format=gbrp[wave];'
        f'[1:v]format=gbrp[bg];'
        f'[bg][wave]blend=all_mode=screen:shortest=1,format=yuv420p[v0];'
        f'[v0]ass={_escape_filter_path(str(ass_path))}[v]',
        '-map',
        '[v]',
        '-map',
        '0:a',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        VIDEO_CRF,
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        AUDIO_BITRATE,
        # The colour source is infinite; the trimmed audio is what ends the clip.
        '-shortest',
        '-movflags',
        '+faststart',
        str(output_path),
    ]


def ffmpeg_audio_command(
    *, audio_path: Path, output_path: Path, clip: Clip
) -> list[str]:
    """The audio pass: trim, re-encode to AAC, and embed the transcription."""
    return [
        FFMPEG,
        '-nostdin',
        '-y',
        '-v',
        'error',
        '-ss',
        f'{clip.start_ms / 1000:.3f}',
        '-to',
        f'{clip.end_ms / 1000:.3f}',
        '-i',
        str(audio_path),
        '-metadata',
        f'title={attribution_text()}',
        '-metadata',
        f'lyrics={clip_transcript_text(clip)}',
        '-c:a',
        'aac',
        '-b:a',
        AUDIO_BITRATE,
        '-movflags',
        '+faststart',
        str(output_path),
    ]


def _render(clip: Clip, key: str) -> None:
    with tempfile.TemporaryDirectory(prefix='shaarawy-clip-') as tmp:
        folder = Path(tmp)
        audio_path = folder / 'source-audio'
        output_path = (
            folder / 'clip.mp4'
            if clip.output == ClipOutput.VIDEO
            else folder / 'clip.m4a'
        )

        storage.get_s3_client().download_file(
            settings.AUDIO_S3_BUCKET, clip.segment.audio.storage_key, str(audio_path)
        )

        if clip.output == ClipOutput.VIDEO:
            subtitle_path = folder / 'karaoke.ass'
            subtitle_path.write_text(
                build_ass(
                    clip_words(clip),
                    clip_start_ms=clip.start_ms,
                    clip_end_ms=clip.end_ms,
                    preset=clip.preset,
                    attribution=attribution_text(),
                ),
                encoding='utf-8',
            )
            command = ffmpeg_command(
                audio_path=audio_path,
                ass_path=subtitle_path,
                output_path=output_path,
                preset=clip.preset,
                clip=clip,
            )
            what = f'clip {clip.pk} video render'
            content_type = VIDEO_CONTENT_TYPE
        else:
            command = ffmpeg_audio_command(
                audio_path=audio_path, output_path=output_path, clip=clip
            )
            what = f'clip {clip.pk} audio render'
            content_type = AUDIO_CONTENT_TYPE

        _run(command, what=what)
        storage.upload_file(key, str(output_path), content_type)


def render_clip(clip: Clip) -> None:
    """Render ``clip`` and publish it, or record why it could not be rendered.

    Synchronous by design: :mod:`clips.tasks` is the only thing that makes it a
    background job, and the tests drive this function directly.
    """
    key = clip.storage_key or storage.clip_key(
        clip.segment_id, clip.start_ms, clip.end_ms, clip.preset, clip.output
    )
    if clip.status == ClipStatus.DONE and storage.object_exists(key):
        logger.info('clip %s already rendered at %s', clip.pk, key)
        return

    clip.status = ClipStatus.RENDERING
    clip.error = ''
    clip.save(update_fields=['status', 'error'])
    try:
        _render(clip, key)
    except Exception:
        clip.status = ClipStatus.FAILED
        clip.error = traceback.format_exc()
        clip.save(update_fields=['status', 'error'])
        logger.error('clip %s failed to render\n%s', clip.pk, clip.error)
        return

    clip.status = ClipStatus.DONE
    clip.storage_key = key
    clip.error = ''
    clip.save(update_fields=['status', 'storage_key', 'error'])
    logger.info('clip %s rendered to %s', clip.pk, key)
