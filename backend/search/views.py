"""HTTP surface for search. All ranking lives in :mod:`search.services`."""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import asdict
from typing import Any

from django.conf import settings
from django.db import connection
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from api.ip import client_ip
from api.serializers import (
    ErrorSerializer,
    SearchResponseSerializer,
    SmartFeedbackResponseSerializer,
    SmartFeedbackSerializer,
    SmartRequestSerializer,
    SmartResponseSerializer,
)

from . import services
from .models import SmartQuery
from .smart import budget as smart_budget
from .smart import cache as smart_cache
from .smart import pipeline, retrieval
from .smart.throttles import SmartRateThrottle

SMART_OFF_DETAIL = "البحث الذكي غير متاح حاليًا."
INFLIGHT_RETRY_S = 10
SSE_PING_S = 10.0
"""A comment line every so often keeps proxies from timing out an idle stream."""
STREAM_ERROR_DETAIL = "تعذّر إكمال الإجابة."

logger = logging.getLogger(__name__)


class EventStreamRenderer(BaseRenderer):
    """Lets DRF's content negotiation accept ``Accept: text/event-stream``.

    The stream itself is a plain :class:`StreamingHttpResponse` that never
    goes through a renderer; this only renders the DRF responses that can
    precede it (a 400 or a 429), as JSON, so a streaming client still gets a
    readable error body.
    """

    media_type = "text/event-stream"
    format = "sse"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        return json.dumps(data, ensure_ascii=False).encode()


def _optional_int(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise services.SearchParameterError(f"{name} must be an integer") from error


class SuggestView(APIView):
    """``GET /api/search/suggest/?q=&kind=`` — autocomplete suggestions.

    ``kind`` scopes suggestions to the selected content (recitation → mushaf
    text, khawatir → khawatir transcript snippets). Returns a plain list of
    strings (matched text snippets). Never cached; results move with every
    pipeline run.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'search'

    @extend_schema(
        operation_id='search_suggest',
        parameters=[
            OpenApiParameter('q', str, required=True),
            OpenApiParameter('kind', str),
        ],
        responses={200: list[str]},
    )
    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        if not query:
            return _no_store(Response([]))
        suggestions = services.suggest(query, kind=request.query_params.get("kind") or None)
        return _no_store(Response(suggestions))


class SearchView(APIView):
    """``GET /api/search/?q=&kind=&surah=&page=`` (API_CONTRACT.md).

    Never cached: results move with every pipeline run.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'search'

    @extend_schema(
        operation_id='search_retrieve',
        parameters=[
            OpenApiParameter('q', str, required=True),
            OpenApiParameter('kind', str),
            OpenApiParameter('surah', int),
            OpenApiParameter('page', int),
        ],
        responses={200: SearchResponseSerializer, 400: ErrorSerializer},
    )
    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        if not query:
            return _error("q is required")
        try:
            page = _optional_int(request, "page")
            response = services.search(
                query,
                kind=request.query_params.get("kind") or None,
                surah=_optional_int(request, "surah"),
                page=1 if page is None else page,
            )
        except services.SearchParameterError as error:
            return _error(str(error))
        return _no_store(Response(asdict(response)))


def _error(detail: str) -> Response:
    return _no_store(Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST))


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


# --- Smart search ---------------------------------------------------------------


class SmartSearchView(APIView):
    """``POST /api/search/smart/`` — a cited, grounded answer (API_CONTRACT.md).

    503 while ``SMART_ENABLED`` is off (distinct from a missing route); 429
    with ``Retry-After`` both from the hourly per-IP rate and from the
    concurrency cap, which is held for the whole request. ``debug`` output is
    reserved for staff sessions. Never cached by clients: the server keeps its
    own answer cache.

    With ``Accept: text/event-stream`` the same POST answers as server-sent
    events — ``stage`` lines as the pipeline advances, ``passages`` as soon as
    the reranked passages are known (sources visible within seconds), then one
    ``result`` carrying the full verified response, or ``error``. No token
    stream: the answer must pass the verifier before anyone sees a quote.
    """

    throttle_classes = [SmartRateThrottle]
    throttle_scope = "smart"
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    def get_throttles(self) -> list[SmartRateThrottle]:
        return super().get_throttles() if settings.SMART_ENABLED else []

    @extend_schema(
        operation_id="search_smart",
        request=SmartRequestSerializer,
        responses={
            200: SmartResponseSerializer,
            400: ErrorSerializer,
            429: ErrorSerializer,
            503: ErrorSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        if not settings.SMART_ENABLED:
            return _no_store(
                Response({"detail": SMART_OFF_DETAIL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            )
        body = SmartRequestSerializer(data=request.data)
        if not body.is_valid():
            return _error(_first_error(body.errors))
        data = body.validated_data
        filters = retrieval.Filters(
            surah=(data.get("filters") or {}).get("surah"),
            source_id=(data.get("filters") or {}).get("source_id"),
        )
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        run = pipeline.RunContext(
            session_key=getattr(getattr(request, "session", None), "session_key", "") or "",
            ip_hash=smart_cache.ip_hash(client_ip(request)),
            user=user,
            debug=bool(data.get("debug")) and bool(getattr(user, "is_staff", False)),
        )
        slot = ExitStack()
        if not slot.enter_context(smart_budget.inflight_slot()):
            slot.close()
            raise Throttled(wait=INFLIGHT_RETRY_S)
        if "text/event-stream" in request.META.get("HTTP_ACCEPT", ""):
            return _stream_smart_search(data["question"], filters, run, slot)
        with slot:
            response = pipeline.run_smart_search(data["question"], filters=filters, run=run)
        return _no_store(Response(response.model_dump()))


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _stream_smart_search(
    question: str, filters: retrieval.Filters, run: pipeline.RunContext, slot: ExitStack
) -> StreamingHttpResponse:
    """Run the pipeline on a helper thread and relay its events as they come.

    The in-flight ``slot`` is released when the stream ends, however it ends.
    ``Content-Encoding: identity`` makes GZipMiddleware leave the body alone
    (it would otherwise buffer it whole); ``X-Accel-Buffering: no`` asks the
    proxy to do the same.
    """
    events: queue.Queue[tuple[str, Any] | None] = queue.Queue()
    run.on_event = lambda name, data: events.put((name, data))

    def work() -> None:
        try:
            response = pipeline.run_smart_search(question, filters=filters, run=run)
            events.put(("result", response.model_dump()))
        except Exception:  # noqa: BLE001 — the reader gets an error event, the log the trace
            logger.exception("smart: streaming request failed")
            events.put(("error", {"detail": STREAM_ERROR_DETAIL}))
        finally:
            connection.close()  # this thread's own database connection
            events.put(None)

    def generate() -> Iterator[bytes]:
        threading.Thread(target=work, name="smart-search", daemon=True).start()
        try:
            while True:
                try:
                    item = events.get(timeout=SSE_PING_S)
                except queue.Empty:
                    yield b": ping\n\n"
                    continue
                if item is None:
                    return
                yield _sse(*item)
        finally:
            slot.close()

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-store"
    response["Content-Encoding"] = "identity"
    response["X-Accel-Buffering"] = "no"
    return response


class SmartFeedbackView(APIView):
    """``POST /api/search/smart/{query_id}/feedback/`` — a thumb on one answer."""

    throttle_classes = [SmartRateThrottle]
    throttle_scope = "smart_feedback"

    @extend_schema(
        operation_id="search_smart_feedback",
        request=SmartFeedbackSerializer,
        responses={
            201: SmartFeedbackResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def post(self, request: Request, query_id: str) -> Response:
        body = SmartFeedbackSerializer(data=request.data)
        if not body.is_valid():
            return _error(_first_error(body.errors))
        updated = SmartQuery.objects.filter(pk=query_id).update(
            feedback=body.validated_data["vote"],
            feedback_note=body.validated_data.get("note", ""),
            feedback_at=timezone.now(),
        )
        if not updated:
            return _no_store(
                Response({"detail": "unknown query"}, status=status.HTTP_404_NOT_FOUND)
            )
        return _no_store(Response({"status": "recorded"}, status=status.HTTP_201_CREATED))


def _first_error(errors: dict[str, object]) -> str:
    for key, value in errors.items():
        message = value
        while isinstance(message, list | dict):
            message = next(iter(message.values())) if isinstance(message, dict) else message[0]
        return f"{key}: {message}"
    return "invalid request"
