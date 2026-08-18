"""Cache-Control policy shared by the read endpoints.

The archive is an append-only corpus: an ayah never changes, and a transcript
that changes gets a new ``Transcript.version`` (and therefore a new ``?v=``),
so every 200 from these views is safe to treat as immutable for a year
(``API_CONTRACT.md``). Search is the exception and sets ``no-store`` itself.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

IMMUTABLE = 'public, max-age=31536000, immutable'
"""One year, never revalidated — the value frozen in API_CONTRACT.md."""


class ImmutableCacheMixin:
    """Stamp :data:`IMMUTABLE` on successful reads. Errors stay uncached."""

    def finalize_response(
        self, request: Request, response: Response, *args: Any, **kwargs: Any
    ) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)  # type: ignore[misc]
        if request.method in ('GET', 'HEAD') and response.status_code == 200:
            response['Cache-Control'] = IMMUTABLE
        return response
