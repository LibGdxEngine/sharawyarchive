"""Turn a queued :class:`~clips.models.Clip` into an mp4 in object storage.

One ffmpeg pass does the whole card: the segment's audio trimmed with
``-ss/-to``, a flat 1080x1920 colour field from ``lavfi``, and the karaoke ASS
file from :mod:`clips.subtitles` burned on with libass. H.264 + AAC, because the
clip is going to be dropped into a social timeline.

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

from .models import Clip, ClipStatus
from .subtitles import PRESETS, build_ass

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get('FFMPEG_BIN', 'ffmpeg')

FRAME_RATE = 30
FRAME_SIZE = '1080x1920'
VIDEO_CRF = '20'
AUDIO_BITRATE = '128k'

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


def ffmpeg_command(
    *, audio_path: Path, ass_path: Path, output_path: Path, preset: str, clip: Clip
) -> list[str]:
    """The single pass: trim, paint, burn, encode."""
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
        f'color=c=0x{PRESETS[preset].background.lstrip("#")}:s={FRAME_SIZE}:r={FRAME_RATE}',
        '-vf',
        f'ass={_escape_filter_path(str(ass_path))}',
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


def _render(clip: Clip, key: str) -> None:
    with tempfile.TemporaryDirectory(prefix='shaarawy-clip-') as tmp:
        folder = Path(tmp)
        audio_path = folder / 'source-audio'
        subtitle_path = folder / 'karaoke.ass'
        output_path = folder / 'clip.mp4'

        storage.get_s3_client().download_file(
            settings.AUDIO_S3_BUCKET, clip.segment.audio.storage_key, str(audio_path)
        )
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
        _run(
            ffmpeg_command(
                audio_path=audio_path,
                ass_path=subtitle_path,
                output_path=output_path,
                preset=clip.preset,
                clip=clip,
            ),
            what=f'clip {clip.pk} render',
        )
        storage.upload_file(key, str(output_path), 'video/mp4')


def render_clip(clip: Clip) -> None:
    """Render ``clip`` and publish it, or record why it could not be rendered.

    Synchronous by design: :mod:`clips.tasks` is the only thing that makes it a
    background job, and the tests drive this function directly.
    """
    key = clip.storage_key or storage.clip_key(
        clip.segment_id, clip.start_ms, clip.end_ms, clip.preset
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
