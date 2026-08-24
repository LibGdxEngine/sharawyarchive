"""``manage.py index_chunks`` rebuilds the chunks index from the database."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from search import services
from search.management.commands import index_chunks

from .conftest import KHAWATIR_TEXTS, CorpusFixture

pytestmark = pytest.mark.django_db


def _document_count() -> int:
    index = services.meili_client().index(services.chunks_index_name())
    return index.get_stats().number_of_documents


def test_command_creates_the_index_and_indexes_every_chunk(
    meili_prefix: str, corpus: CorpusFixture
) -> None:
    out = StringIO()
    call_command("index_chunks", stdout=out)

    assert _document_count() == len(corpus.chunks)
    assert f"indexed {len(corpus.chunks)} chunks into {services.chunks_index_name()}" in (
        out.getvalue()
    )
    chunk = corpus.chunk_for(KHAWATIR_TEXTS[0])
    document = services.meili_client().index(services.chunks_index_name()).get_document(chunk.pk)
    assert document.segment_id == corpus.khawatir.pk
    assert document.text_normalized == chunk.text_normalized


def test_command_is_idempotent(meili_prefix: str, corpus: CorpusFixture) -> None:
    call_command("index_chunks", stdout=StringIO())
    call_command("index_chunks", stdout=StringIO())

    assert _document_count() == len(corpus.chunks)


def test_command_flushes_the_partial_final_batch(
    meili_prefix: str, corpus: CorpusFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(index_chunks, "BATCH_SIZE", 4)  # 10 chunks -> 4 + 4 + 2
    out = StringIO()
    call_command("index_chunks", stdout=out)

    assert _document_count() == len(corpus.chunks)
    assert f"indexed {len(corpus.chunks)} chunks into" in out.getvalue()


def test_command_reports_zero_on_an_empty_database(meili_prefix: str) -> None:
    out = StringIO()
    call_command("index_chunks", stdout=out)

    assert _document_count() == 0
    assert "indexed 0 chunks into" in out.getvalue()
