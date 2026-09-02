"""Content-Disposition for clip downloads.

The header is what makes a browser save a file instead of playing it, and it
has to survive an Arabic filename — which is the whole reason it is not a
one-liner. Pure string work; no bucket, no network.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from corpus.storage import MAX_FILENAME_STEM, content_disposition

ARABIC = 'أرشيف-الشعراوي-1.1-12.04-12.39.mp4'


def test_an_arabic_name_travels_in_the_rfc_5987_form() -> None:
    header = content_disposition(ARABIC)

    assert header.startswith('attachment; ')
    assert "filename*=UTF-8''" in header
    assert unquote(header.split("UTF-8''")[1]) == ARABIC


def test_the_header_is_pure_ascii() -> None:
    """A raw Arabic byte in a header is a mojibake filename at best, and a
    rejected response at worst."""
    content_disposition(ARABIC).encode('ascii')


def test_the_ascii_fallback_keeps_the_extension() -> None:
    """Clients that ignore `filename*` still get something openable."""
    assert 'filename="clip.mp4"' in content_disposition(ARABIC)
    assert 'filename="clip.m4a"' in content_disposition('صوت.m4a')


@pytest.mark.parametrize('hostile', ['a"b.mp4', 'a/b.mp4', 'a:b.mp4', 'a\nb.mp4', '../../etc.mp4'])
def test_path_and_quote_characters_are_stripped(hostile: str) -> None:
    name = unquote(content_disposition(hostile).split("UTF-8''")[1])

    assert '/' not in name
    assert '"' not in name
    assert '\n' not in name


def test_a_long_name_is_truncated_without_losing_the_extension() -> None:
    header = content_disposition('ا' * 300 + '.mp4')

    name = unquote(header.split("UTF-8''")[1])
    assert name.endswith('.mp4')
    assert len(name) <= MAX_FILENAME_STEM + len('.mp4')


def test_a_name_with_no_extension_still_produces_a_fallback() -> None:
    assert 'filename="clip.bin"' in content_disposition('مقطع')
