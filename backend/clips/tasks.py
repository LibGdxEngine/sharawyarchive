"""The Celery side of clip rendering.

Rendering is minutes of somebody's CPU, so the API never does it inline: the
view creates the row and drops this task on the default queue. The task itself
is a two-liner on purpose — everything that can go wrong is handled inside
:func:`clips.rendering.render_clip`, which records failures on the row instead
of raising, so a clip never dies silently in a worker log.
"""

from __future__ import annotations

import logging

from celery import shared_task

from . import rendering
from .models import Clip

logger = logging.getLogger(__name__)


@shared_task(name='clips.render_clip')
def render_clip(clip_id: str) -> None:
    """Render the clip with this id, if it is still there.

    A queued task can outlive its row (the segment behind it was deleted, the
    database was reset); that is a no-op, not an error worth retrying.
    """
    clip = Clip.objects.filter(pk=clip_id).select_related('segment__audio').first()
    if clip is None:
        logger.warning('clip %s no longer exists, nothing to render', clip_id)
        return
    rendering.render_clip(clip)
