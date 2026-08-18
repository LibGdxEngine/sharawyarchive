"""HTTP surface for search. All ranking lives in :mod:`search.services`."""

from __future__ import annotations

from dataclasses import asdict

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


def _optional_int(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise services.SearchParameterError(f"{name} must be an integer") from error


class SearchView(APIView):
    """``GET /api/search/?q=&mode=&kind=&surah=&page=`` (API_CONTRACT.md).

    Never cached: results move with every pipeline run.
    """

    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        if not query:
            return _error("q is required")
        try:
            page = _optional_int(request, "page")
            response = services.search(
                query,
                mode=request.query_params.get("mode") or services.DEFAULT_MODE,
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
