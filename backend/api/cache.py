"""Cache-Control policy shared by the read endpoints.

Most of the archive is content-addressed: an ayah never changes, and a
transcript that changes gets a new ``Transcript.version`` (and therefore a new
``?v=``), so those responses are safe to treat as immutable for a year
(``API_CONTRACT.md``).

Two kinds of payload are *not*, and saying they are is a real bug rather than a
missed optimisation:

* anything carrying a **presigned URL**, which expires in six hours. A year of
  ``public`` caching hands out dead links, and a shared cache would hand one
  reader's signed URL to another — hence ``private`` and five minutes.
* **topics**, whose whole point is the publish/unpublish gate. An immutable
  response means unpublishing never reaches a reader who has already looked.

Search is the third exception and sets ``no-store`` itself.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

IMMUTABLE = 'public, max-age=31536000, immutable'
"""One year, never revalidated — the value frozen in API_CONTRACT.md."""

PRIVATE_SHORT = 'private, max-age=300'
"""For bodies holding a presigned URL: never a shared cache, never for long."""

PUBLIC_SHORT = 'public, max-age=300'
"""For bodies an editor can change: cacheable, but it has to come back."""


class CacheControlMixin:
    """Stamp :attr:`cache_control` on successful reads. Errors stay uncached."""

    cache_control: str = IMMUTABLE

    def finalize_response(
        self, request: Request, response: Response, *args: Any, **kwargs: Any
    ) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)  # type: ignore[misc]
        if request.method in ('GET', 'HEAD') and response.status_code == 200:
            response['Cache-Control'] = self.cache_control
        return response


class ImmutableCacheMixin(CacheControlMixin):
    """For content-addressed reads only: the body cannot change under this URL."""
