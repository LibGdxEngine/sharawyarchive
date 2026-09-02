"""The filename a reader sees when a clip lands in their Downloads folder.

The storage key (``clips/17-125000-155000-night-video.mp4``) is an internal
identifier and, per project rule 4, never leaves the backend. What the browser
saves should instead say what the clip *is*, in Arabic, so a shared file is
still identifiable a month later.
"""

from __future__ import annotations

from corpus.models import Segment

from .models import Clip, ClipOutput

ARCHIVE_NAME = 'أرشيف-الشعراوي'


def _timecode(ms: int) -> str:
    """``h.mm.ss`` — colons are illegal in filenames on Windows and macOS."""
    seconds, _ = divmod(int(ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}.{minutes:02d}.{seconds:02d}' if hours else f'{minutes}.{seconds:02d}'


def _segment_label(segment: Segment) -> str:
    """A short human name for the segment, mirroring ``Segment.__str__``."""
    if segment.surah_id and segment.ayah_start:
        span = (
            f'{segment.ayah_start}-{segment.ayah_end}'
            if segment.ayah_end and segment.ayah_end != segment.ayah_start
            else f'{segment.ayah_start}'
        )
        return f'{segment.surah_id}.{span}'
    return segment.title or f'مقطع-{segment.pk}'


def download_filename(clip: Clip) -> str:
    """``أرشيف-الشعراوي-<segment>-<from>-<to>.<mp4|m4a>``.

    Sanitising and length-capping happen in :func:`corpus.storage.content_disposition`,
    which owns the header this string ends up in.
    """
    ext = 'm4a' if clip.output == ClipOutput.AUDIO else 'mp4'
    label = _segment_label(clip.segment).replace(' ', '-')
    return (
        f'{ARCHIVE_NAME}-{label}'
        f'-{_timecode(clip.start_ms)}-{_timecode(clip.end_ms)}.{ext}'
    )
