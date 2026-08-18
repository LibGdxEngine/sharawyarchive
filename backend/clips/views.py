"""Clip render jobs. This app enqueues them; the renderer (Phase 8) runs them."""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Clip
from .serializers import ClipCreateSerializer, ClipDetailSerializer, ClipStatusSerializer


class ClipCreateView(APIView):
    """``POST /api/clips/`` — enqueue a render, or hand back the one that is
    already running.

    The (segment, range, preset) tuple is unique, which makes the job table its
    own cache: the second person to share the same passage joins the first
    person's render instead of starting another. ``202`` means "queued by you",
    ``200`` means "already queued".
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
        clip, created = Clip.objects.get_or_create(**serializer.validated_data)
        return Response(
            ClipStatusSerializer(clip).data,
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )


class ClipDetailView(RetrieveAPIView):
    """``GET /api/clips/{id}/`` — poll a job. Never cached: status moves."""

    serializer_class = ClipDetailSerializer

    def get_queryset(self) -> QuerySet[Clip]:
        return Clip.objects.all()
