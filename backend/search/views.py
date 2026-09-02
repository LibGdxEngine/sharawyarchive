"""HTTP surface for search. All ranking lives in :mod:`search.services`."""

from __future__ import annotations

from dataclasses import asdict

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import Throttled
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
    """

    throttle_classes = [SmartRateThrottle]
    throttle_scope = "smart"

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
        with smart_budget.inflight_slot() as acquired:
            if not acquired:
                raise Throttled(wait=INFLIGHT_RETRY_S)
            response = pipeline.run_smart_search(data["question"], filters=filters, run=run)
        return _no_store(Response(response.model_dump()))


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
