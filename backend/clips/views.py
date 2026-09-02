"""Clip render jobs: the API enqueues them, :mod:`clips.tasks` runs them."""

from __future__ import annotations

from django.db import transaction
from django.db.models import QuerySet
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from corpus.storage import clip_key, presigned_url

from .models import Clip, ClipStatus
from .naming import download_filename
from .serializers import ClipCreateSerializer, ClipDetailSerializer, ClipStatusSerializer
from .tasks import render_clip


class ClipCreateView(APIView):
    """``POST /api/clips/`` — enqueue a render, or hand back the one that is
    already running.

    The (segment, range, preset) tuple is unique, which makes the job table its
    own cache: the second person to share the same passage joins the first
    person's render instead of starting another. ``202`` means "queued by you",
    ``200`` means "already queued".

    The one job that is *not* simply handed back is a failed one: asking for it
    again queues one more attempt on the same row, so a transient worker or
    storage failure is not a clip nobody can ever have.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'clips'

    @extend_schema(
        operation_id='clip_create',
        request=ClipCreateSerializer,
        responses={202: ClipStatusSerializer, 200: ClipStatusSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ClipCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            clip, created = Clip.objects.get_or_create(**serializer.validated_data)
            requeued = False
            if not created:
                # Re-read the row under a lock. Read-committed means two
                # requests arriving on the same failed clip both see `failed`
                # and both enqueue a render, so the same ffmpeg job runs twice
                # and two workers write the same object. The lock serialises
                # them: the second one wakes up to `queued` and does nothing.
                clip = Clip.objects.select_for_update().get(pk=clip.pk)
                if clip.status == ClipStatus.FAILED:
                    # A queued, rendering or finished job is left strictly
                    # alone — that is the cache doing its work. A *failed* one
                    # is re-queued instead: the failure is usually transient (a
                    # worker died, storage blinked) and the alternative is a
                    # permanently dead clip nobody can ever ask for again,
                    # because the unique constraint hands every later request
                    # the same broken row.
                    clip.status = ClipStatus.QUEUED
                    clip.error = ''
                    clip.save(update_fields=['status', 'error'])
                    requeued = True
            if created or requeued:
                # After commit, or the worker races the transaction and looks
                # up a row that is not there yet.
                transaction.on_commit(lambda: render_clip.delay(str(clip.pk)))
        return Response(
            ClipStatusSerializer(clip).data,
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )


class ClipDetailView(RetrieveAPIView):
    """``GET /api/clips/{id}/`` — poll a job. Never cached: status moves."""

    serializer_class = ClipDetailSerializer

    def get_queryset(self) -> QuerySet[Clip]:
        # The download filename reads the segment, and the client polls this
        # endpoint every three seconds — do not pay for a second query each time.
        return Clip.objects.select_related('segment')


class ClipFileView(APIView):
    """``GET /api/clips/{id}/media/`` and ``.../download/`` — the clip bytes.

    Both redirect to a freshly presigned object URL rather than answering with
    one, which buys two things a presigned URL in a JSON body cannot:

    * **The link never rots.** A presigned URL dies in six hours, and these
      addresses are the ones that get shared, embedded in OpenGraph metadata and
      pasted into chats.
    * **The download actually downloads.** The bucket is a different origin from
      the site, and HTML ignores ``download`` on a cross-origin anchor. The
      attachment disposition is signed into the redirect target instead, so the
      browser saves the file whatever the anchor says.

    ``as_attachment`` is what separates the two routes: the clip page plays the
    same object inline, and an attachment disposition would fight that.
    """

    as_attachment = False

    @extend_schema(
        # Nothing to infer a serializer from: the body is a redirect, not JSON.
        responses={
            (302, None): OpenApiResponse(description='redirect to the clip object'),
            404: OpenApiResponse(description='no such clip, or not rendered yet'),
        },
    )
    def get(self, request: Request, pk: str) -> HttpResponseRedirect:
        clip = get_object_or_404(Clip.objects.select_related('segment'), pk=pk)
        if clip.status != ClipStatus.DONE:
            raise Http404('clip is not rendered')

        key = clip.storage_key or clip_key(
            clip.segment_id, clip.start_ms, clip.end_ms, clip.preset, clip.output
        )
        url = presigned_url(
            key,
            download_as=download_filename(clip) if self.as_attachment else None,
        )
        response = HttpResponseRedirect(url)
        # Never cache the redirect for longer than the URL it points at.
        response['Cache-Control'] = 'private, max-age=300'
        return response
