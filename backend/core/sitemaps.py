"""Hand-rolled sitemap views.

We do not use django.contrib.sitemaps because it requires django.contrib.sites
(a database-backed Site table) and couples URL generation to the incoming
request host.  Here we use SITE_BASE_URL from settings so every response is
deterministic and matches the canonical domain regardless of how the container
is reached internally.

URL layout
----------
GET /sitemap.xml          — sitemap index listing the two children
GET /sitemap-quran.xml    — Surah (114) + Ayah (6 236) entries
GET /sitemap-segments.xml — Indexed Segment entries

All responses carry ``Cache-Control: public, max-age=86400``.
"""

from __future__ import annotations

import datetime
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

_CACHE_1DAY = "public, max-age=86400"


def _base_url() -> str:
    return getattr(settings, "SITE_BASE_URL", "http://localhost:3000").rstrip("/")


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _urlset_open() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    )


def _urlset_close() -> str:
    return "</urlset>\n"


def _url_entry(loc: str, lastmod: str | None = None, changefreq: str = "weekly") -> str:
    lines = [f"  <url>\n    <loc>{escape(loc)}</loc>"]
    if lastmod:
        lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
    lines.append(f"    <changefreq>{changefreq}</changefreq>")
    lines.append("  </url>")
    return "\n".join(lines) + "\n"


def _sitemap_index_open() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    )


def _sitemap_index_close() -> str:
    return "</sitemapindex>\n"


def _sitemap_entry(loc: str) -> str:
    today = datetime.date.today().isoformat()
    return (
        f"  <sitemap>\n"
        f"    <loc>{escape(loc)}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"  </sitemap>\n"
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@require_GET
def sitemap_index(request: HttpRequest) -> HttpResponse:
    """``GET /sitemap.xml`` — index pointing to child sitemaps."""
    base = _base_url()
    body = _sitemap_index_open()
    body += _sitemap_entry(f"{base}/sitemap-quran.xml")
    body += _sitemap_entry(f"{base}/sitemap-segments.xml")
    body += _sitemap_index_close()
    response = HttpResponse(body, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = _CACHE_1DAY
    return response


@require_GET
def sitemap_quran(request: HttpRequest) -> HttpResponse:
    """``GET /sitemap-quran.xml`` — 114 surahs + 6 236 ayahs."""
    from quran.models import Ayah, Surah  # local import avoids circular at module load

    base = _base_url()
    body = _urlset_open()

    for surah in Surah.objects.only("number").order_by("number").iterator():
        body += _url_entry(f"{base}/surah/{surah.number}", changefreq="monthly")

    for ayah in (
        Ayah.objects.select_related("surah")
        .only("number", "surah__number")
        .order_by("surah_id", "number")
        .iterator()
    ):
        body += _url_entry(
            f"{base}/surah/{ayah.surah_id}?ayah={ayah.number}",
            changefreq="monthly",
        )

    body += _urlset_close()
    response = HttpResponse(body, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = _CACHE_1DAY
    return response


@require_GET
def sitemap_segments(request: HttpRequest) -> HttpResponse:
    """``GET /sitemap-segments.xml`` — all indexed segments."""
    from corpus.models import Segment, SegmentStatus  # local import

    base = _base_url()
    body = _urlset_open()

    for seg in (
        Segment.objects.filter(status=SegmentStatus.INDEXED)
        .only("id", "updated_at")
        .order_by("id")
        .iterator()
    ):
        lastmod = seg.updated_at.date().isoformat() if seg.updated_at else None
        body += _url_entry(f"{base}/listen/{seg.id}", lastmod=lastmod, changefreq="monthly")

    body += _urlset_close()
    response = HttpResponse(body, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = _CACHE_1DAY
    return response
