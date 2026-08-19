"""Tests for sitemap views in core.sitemaps."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from django.test import RequestFactory, override_settings

from core.sitemaps import sitemap_index, sitemap_quran, sitemap_segments

pytestmark = pytest.mark.django_db

SITE_BASE_URL = "http://example.com"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

factory = RequestFactory()


# ---------------------------------------------------------------------------
# Fixtures: minimal data so tests don't depend on full import_quran.
# ---------------------------------------------------------------------------

@pytest.fixture()
def surah_fixture(db):
    from quran.models import Surah

    surahs = [
        Surah(
            number=1,
            name_ar="الفاتحة",
            name_ar_plain="الفاتحة",
            name_en="Al-Fatihah",
            ayah_count=7,
            revelation_place="makkah",
            order_revealed=5,
        ),
        Surah(
            number=2,
            name_ar="البقرة",
            name_ar_plain="البقرة",
            name_en="Al-Baqarah",
            ayah_count=286,
            revelation_place="madinah",
            order_revealed=87,
        ),
    ]
    Surah.objects.bulk_create(surahs)
    return surahs


@pytest.fixture()
def ayah_fixture(surah_fixture):
    from quran.models import Ayah, Surah

    s1 = Surah.objects.get(number=1)
    s2 = Surah.objects.get(number=2)
    ayahs = [
        Ayah(
            surah=s1, number=1, text_uthmani="بِسْمِ",
            text_imlaei="بسم", text_normalized="بسم", juz=1, hizb=1, page=1,
        ),
        Ayah(
            surah=s1, number=2, text_uthmani="الْحَمْدُ",
            text_imlaei="الحمد", text_normalized="الحمد", juz=1, hizb=1, page=1,
        ),
        Ayah(
            surah=s2, number=1, text_uthmani="الم",
            text_imlaei="الم", text_normalized="الم", juz=1, hizb=1, page=2,
        ),
    ]
    Ayah.objects.bulk_create(ayahs)
    return ayahs


@pytest.fixture()
def segment_fixture(surah_fixture):
    from corpus.models import AudioAsset, Segment, SegmentStatus, Source

    src = Source.objects.create(title="Test Source", kind="recitation")
    audio = AudioAsset.objects.create(
        storage_key="test.opus",
        duration_ms=5000,
        mime="audio/ogg",
        sha256="a" * 64,
        size_bytes=10000,
    )
    from quran.models import Surah

    seg = Segment.objects.create(
        source=src,
        kind="recitation",
        surah=Surah.objects.get(number=1),
        ayah_start=1,
        ayah_end=7,
        audio=audio,
        duration_ms=5000,
        status=SegmentStatus.INDEXED,
    )
    # also create a non-indexed segment — should not appear
    Segment.objects.create(
        source=src,
        kind="recitation",
        surah=Surah.objects.get(number=1),
        ayah_start=1,
        ayah_end=7,
        audio=audio,
        duration_ms=5000,
        status=SegmentStatus.PENDING,
    )
    return seg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_index_parses(db):
    req = factory.get("/sitemap.xml")
    resp = sitemap_index(req)
    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    locs = [el.text for el in root.findall("sm:sitemap/sm:loc", NS)]
    assert f"{SITE_BASE_URL}/sitemap-quran.xml" in locs
    assert f"{SITE_BASE_URL}/sitemap-segments.xml" in locs


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_index_cache_header(db):
    req = factory.get("/sitemap.xml")
    resp = sitemap_index(req)
    assert "public" in resp["Cache-Control"]
    assert "max-age=86400" in resp["Cache-Control"]


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_quran_url_count(surah_fixture, ayah_fixture):
    req = factory.get("/sitemap-quran.xml")
    resp = sitemap_quran(req)
    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    urls = root.findall("sm:url", NS)
    # 2 surahs + 3 ayahs = 5 entries
    assert len(urls) == 5


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_quran_uses_site_base_url(surah_fixture, ayah_fixture):
    req = factory.get("/sitemap-quran.xml")
    resp = sitemap_quran(req)
    root = ET.fromstring(resp.content)
    locs = [el.text for el in root.findall("sm:url/sm:loc", NS)]
    assert all(loc.startswith(SITE_BASE_URL) for loc in locs)


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_quran_surah_urls(surah_fixture, ayah_fixture):
    req = factory.get("/sitemap-quran.xml")
    resp = sitemap_quran(req)
    root = ET.fromstring(resp.content)
    locs = [el.text for el in root.findall("sm:url/sm:loc", NS)]
    assert f"{SITE_BASE_URL}/surah/1" in locs
    assert f"{SITE_BASE_URL}/surah/2" in locs


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_quran_ayah_urls(surah_fixture, ayah_fixture):
    req = factory.get("/sitemap-quran.xml")
    resp = sitemap_quran(req)
    root = ET.fromstring(resp.content)
    locs = [el.text for el in root.findall("sm:url/sm:loc", NS)]
    assert f"{SITE_BASE_URL}/surah/1?ayah=1#ayah-1" in locs
    assert f"{SITE_BASE_URL}/surah/2?ayah=1#ayah-1" in locs


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_segments_only_indexed(segment_fixture):
    req = factory.get("/sitemap-segments.xml")
    resp = sitemap_segments(req)
    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    urls = root.findall("sm:url", NS)
    # Only the INDEXED segment appears (1 of 2 created)
    assert len(urls) == 1


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_segments_url_uses_base(segment_fixture):
    req = factory.get("/sitemap-segments.xml")
    resp = sitemap_segments(req)
    root = ET.fromstring(resp.content)
    locs = [el.text for el in root.findall("sm:url/sm:loc", NS)]
    assert locs[0].startswith(f"{SITE_BASE_URL}/listen/")


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_segments_cache_header(segment_fixture):
    req = factory.get("/sitemap-segments.xml")
    resp = sitemap_segments(req)
    assert "max-age=86400" in resp["Cache-Control"]


@override_settings(SITE_BASE_URL=SITE_BASE_URL)
def test_sitemap_quran_cache_header(surah_fixture, ayah_fixture):
    req = factory.get("/sitemap-quran.xml")
    resp = sitemap_quran(req)
    assert "max-age=86400" in resp["Cache-Control"]
