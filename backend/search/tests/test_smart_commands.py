"""The Phase 2 management commands: build, embed, retrieve, evaluate."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
import respx
from django.core.management import CommandError, call_command
from pytest_django.fixtures import Settings

from search.management.commands.embed_passages import embedding_text
from search.models import EMBEDDING_DIMENSIONS, Passage
from search.smart import embedding_model_tag
from search.smart.eval import GOLDEN_PATH, GoldenError, load_golden
from search.smart.eval import metrics as m

from .conftest import CorpusFixture
from .openrouter_fakes import embedding_response, error_response, request_json, stub_vector

pytestmark = pytest.mark.django_db

SMALL = ["--min-words", "6", "--max-words", "12"]


def _run(*args: str) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


# --- build_passages -------------------------------------------------------------


def test_build_passages_is_idempotent(corpus: CorpusFixture) -> None:
    out, _ = _run("build_passages", *SMALL)
    count = Passage.objects.count()
    assert count > 2
    assert f"passages: wrote {count} (deleted 0, unchanged 0, embeddings carried 0)" in out
    assert "over 2 transcripts" in out

    out, _ = _run("build_passages", *SMALL)
    assert f"wrote 0 (deleted 0, unchanged {count}" in out
    assert Passage.objects.count() == count


def test_build_passages_dry_run_and_scoping(corpus: CorpusFixture) -> None:
    out, _ = _run("build_passages", "--dry-run", *SMALL)
    assert "would write" in out and not Passage.objects.exists()

    _run("build_passages", "--segment", str(corpus.recitation.pk), *SMALL)
    assert set(Passage.objects.values_list("segment_id", flat=True)) == {corpus.recitation.pk}

    _run("build_passages", "--limit", "1", "--rebuild", *SMALL)
    assert set(Passage.objects.values_list("segment_id", flat=True)) == {
        corpus.recitation.pk,
        corpus.khawatir.pk,
    }


# --- embed_passages -------------------------------------------------------------


def _embed_ok(request: httpx.Request) -> httpx.Response:
    texts = request_json(request)["input"]
    return embedding_response([stub_vector(text, EMBEDDING_DIMENSIONS) for text in texts])


@pytest.fixture
def built(corpus: CorpusFixture, smart_settings: Settings) -> int:
    smart_settings.SMART_EMBEDDING_DIMENSIONS = EMBEDDING_DIMENSIONS
    _run("build_passages", *SMALL)
    return Passage.objects.count()


def test_embed_passages_embeds_in_batches_and_is_resumable(
    built: int, openrouter: respx.MockRouter
) -> None:
    route = openrouter.post("/embeddings").mock(side_effect=_embed_ok)

    out, _ = _run("embed_passages", "--batch-size", "4")

    assert route.call_count == -(-built // 4)
    first = request_json(route.calls[0].request)
    assert len(first["input"]) == 4 and "\n" in first["input"][0]
    assert first["input"][0].startswith("خواطر")
    tag = embedding_model_tag()
    rows = list(Passage.objects.all())
    assert all(row.is_embedded and row.embedding_model == tag for row in rows)
    assert all(row.embedded_hash == row.content_hash and row.embedded_at for row in rows)
    assert f"embedded {built} passages in {route.call_count} batches with {tag}" in out

    # Nothing is stale any more: a second run makes no call at all.
    route.reset()
    out, _ = _run("embed_passages", "--batch-size", "4")
    assert route.call_count == 0 and "embedded 0 passages" in out

    # A row whose text moved on is the only one re-embedded; --force does all.
    stale = rows[0]
    Passage.objects.filter(pk=stale.pk).update(embedded_hash="stale")
    _run("embed_passages")
    assert route.call_count == 1
    assert len(request_json(route.calls.last.request)["input"]) == 1
    assert Passage.objects.get(pk=stale.pk).embedded_hash == stale.content_hash

    Passage.objects.filter(pk=stale.pk).update(embedding_model="old/model@1024")
    _run("embed_passages")
    assert route.call_count == 2
    assert Passage.objects.get(pk=stale.pk).embedding_model == tag

    route.reset()
    _run("embed_passages", "--force", "--batch-size", "100")
    assert route.call_count == 1
    assert len(request_json(route.calls.last.request)["input"]) == built


def test_embed_passages_skips_a_failing_batch_and_picks_it_up_next_run(
    built: int, openrouter: respx.MockRouter
) -> None:
    poison = Passage.objects.order_by("pk").first()
    assert poison is not None
    poisoned_text = embedding_text(poison.header, poison.text)

    def flaky(request: httpx.Request) -> httpx.Response:
        if poisoned_text in request_json(request)["input"]:
            return error_response(503, "overloaded")
        return _embed_ok(request)

    route = openrouter.post("/embeddings").mock(side_effect=flaky)

    out, err = _run("embed_passages", "--batch-size", "4")

    assert "failed, skipped" in err
    assert f"embedded {built - 4} passages" in out and "failed 4" in out
    assert Passage.objects.filter(embedding__isnull=True).count() == 4
    assert not Passage.objects.get(pk=poison.pk).is_embedded

    route.reset()
    route.mock(side_effect=_embed_ok)
    out, _ = _run("embed_passages", "--batch-size", "4")
    assert route.call_count == 1 and "embedded 4 passages" in out
    assert not Passage.objects.filter(embedding__isnull=True).exists()


def test_embed_passages_dry_run_and_cost_cap(built: int, openrouter: respx.MockRouter) -> None:
    route = openrouter.post("/embeddings").mock(side_effect=_embed_ok)

    out, _ = _run("embed_passages", "--dry-run")
    assert f"would embed {built} passages" in out and "tokens" in out
    assert route.call_count == 0

    out, err = _run("embed_passages", "--batch-size", "2", "--max-cost-usd", "0")
    assert route.call_count == 1 and "exceeds --max-cost-usd" in err
    assert Passage.objects.filter(embedding__isnull=False).count() == 2

    out, _ = _run("embed_passages", "--limit", "3", "--batch-size", "10")
    assert len(request_json(route.calls.last.request)["input"]) == 3


# --- smart_retrieve -------------------------------------------------------------


def test_smart_retrieve_prints_channels_and_candidates(built: int) -> None:
    out, _ = _run("smart_retrieve", "الصبر عند الصدمة", "--no-llm", "-k", "3")

    assert "[lexical:0 ×2]" in out
    assert " 1. passage " in out and "segment" in out
    assert out.count(". passage ") <= 3


def test_smart_retrieve_json_is_machine_readable(built: int, corpus: CorpusFixture) -> None:
    out, _ = _run("smart_retrieve", "الصبر", "--no-llm", "--json", "--surah", "2")

    payload = json.loads(out)
    assert payload["queries"] == ["الصبر"] and payload["warnings"] == []
    assert [lst["name"] for lst in payload["lists"]] == ["lexical:0"]
    assert payload["candidates"][0]["rank"] == 1
    assert {c["segment_id"] for c in payload["candidates"]} == {corpus.khawatir.pk}
    assert isinstance(payload["candidates"][0]["start_ms"], int)


# --- smart_eval and the golden set ------------------------------------------------


def test_the_committed_golden_file_loads() -> None:
    items = load_golden(GOLDEN_PATH)

    assert len(items) >= 3
    assert all(item.expected_status in {"answered", "partial", "not_found"} for item in items)


@pytest.mark.parametrize(
    "line",
    [
        '{"id": "x", "question": "q", "expected_status": "answered"}',  # no segments
        '{"id": "x", "question": "q", "expected_status": "bogus", "expected_segment_ids": [1]}',
        '{"id": "", "question": "q", "expected_status": "not_found"}',
        '{"id": "x", "question": "", "expected_status": "not_found"}',
        "not json",
    ],
)
def test_malformed_golden_lines_are_refused(tmp_path: Path, line: str) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(GoldenError):
        load_golden(golden)


def test_duplicate_golden_ids_are_refused(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    row = '{"id": "x", "question": "q", "expected_status": "not_found"}\n'
    golden.write_text(row * 2, encoding="utf-8")

    with pytest.raises(GoldenError, match="duplicate"):
        load_golden(golden)


def test_metrics() -> None:
    assert m.first_hit_rank([5, 7, 9], [9]) == 3
    assert m.first_hit_rank([5, 7], [9]) is None
    assert m.recall_at_k([5, 7, 9], [9], 2) == 0.0
    assert m.recall_at_k([5, 7, 9], [9], 3) == 1.0
    assert m.reciprocal_rank([5, 9], [9]) == 0.5
    assert m.reciprocal_rank([5], [9]) == 0.0
    assert m.mean([]) == 0.0 and m.mean([1.0, 3.0]) == 2.0
    assert m.percentile([], 50) == 0.0
    assert m.percentile([10.0, 20.0, 30.0, 40.0], 50) == 20.0  # nearest rank
    assert m.percentile([40.0, 10.0, 30.0, 20.0], 95) == 40.0


def test_smart_eval_scores_retrieval_against_a_golden_file(
    built: int, corpus: CorpusFixture, tmp_path: Path
) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        "\n".join(
            [
                "# comment",
                json.dumps(
                    {
                        "id": "hit",
                        "question": "الصبر عند الصدمة الأولى",
                        "expected_segment_ids": [corpus.khawatir.pk],
                        "expected_status": "answered",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "miss",
                        "question": "الزكاة طهرة",
                        "expected_segment_ids": [corpus.recitation.pk],
                        "expected_status": "answered",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {"id": "abstain", "question": "x", "expected_status": "not_found"},
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    out, _ = _run(
        "smart_eval", "--no-llm", "--golden", str(golden), "--out", str(report_path), "-k", "5"
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run"]["stage"] == "retrieval" and report["run"]["n"] == 2
    assert report["run"]["llm"] is False and report["run"]["k"] == 5
    assert report["summary"]["recall_at_5"] == 0.5
    assert report["summary"]["mrr"] == 0.5
    assert report["summary"]["errors"] == 0
    by_id = {item["id"]: item for item in report["items"]}
    assert by_id["hit"]["hit_rank"] == 1 and by_id["miss"]["hit_rank"] is None
    assert "recall@5=0.500" in out and "mrr=0.500" in out
    assert "text" not in json.dumps(report["items"])


def test_smart_eval_rerank_stage_scores_what_the_generator_would_read(
    built: int, corpus: CorpusFixture, tmp_path: Path
) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        json.dumps(
            {
                "id": "hit",
                "question": "الصبر عند الصدمة الأولى",
                "expected_segment_ids": [corpus.khawatir.pk],
                "expected_status": "answered",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    out, _ = _run(
        "smart_eval",
        "--stage",
        "rerank",
        "--no-llm",
        "--golden",
        str(golden),
        "--out",
        str(report_path),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run"]["stage"] == "rerank" and report["run"]["k"] == 8
    assert report["run"]["rerank_model"] == "test/rerank"
    assert report["summary"]["recall_at_8"] == 1.0 and report["summary"]["weak_evidence"] == 0
    (item,) = report["items"]
    assert item["hit_rank"] == 1 and item["retrieval_hit_rank"] == 1
    assert "rerank: n=1 recall@8=1.000" in out


def test_smart_eval_full_stage_reports_statuses_and_gates(
    built: int, corpus: CorpusFixture, tmp_path: Path
) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "hit",
                        "question": "الصبر عند الصدمة الأولى",
                        "expected_segment_ids": [corpus.khawatir.pk],
                        "expected_status": "answered",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {"id": "abstain", "question": "xyzzy plugh", "expected_status": "not_found"},
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    out, _ = _run(
        "smart_eval",
        "--stage",
        "full",
        "--no-llm",
        "--golden",
        str(golden),
        "--out",
        str(report_path),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run"]["stage"] == "full" and report["run"]["judge"] is False
    assert report["run"]["models"]["judge"] is None
    by_id = {item["id"]: item for item in report["items"]}
    # Without a provider nothing is generated: retrieval hits degrade, misses abstain.
    assert by_id["hit"]["status"] == "degraded" and by_id["hit"]["hit_rank"] == 1
    assert by_id["abstain"]["status"] == "not_found" and by_id["abstain"]["hit_rank"] is None
    summary = report["summary"]
    assert summary["n"] == 2 and summary["errors"] == 0 and summary["labelled"] == 1
    assert summary["recall_at_8"] == 1.0
    assert summary["abstention_accuracy"] == 1.0
    assert summary["confusion"] == {"answered": {"degraded": 1}, "not_found": {"not_found": 1}}
    assert summary["citation_validity"] is None and summary["unsupported_ratio"] is None
    assert report["gates"]["recall_at_8"] is True
    assert report["gates"]["citation_validity"] is None
    assert report["gates"]["latency_p95_ms"] in {True, False}
    assert "gates: passed" in out and "full: n=2" in out
    assert "text" not in json.dumps(report["items"])


def test_smart_eval_full_refuses_judge_without_a_provider(built: int) -> None:
    with pytest.raises(CommandError, match="--judge"):
        _run("smart_eval", "--stage", "full", "--no-llm", "--judge")


def test_smart_label_lists_segments_once_with_an_excerpt(
    built: int, corpus: CorpusFixture
) -> None:
    out, _ = _run("smart_label", "الصبر عند الصدمة", "--no-llm", "--json")

    payload = json.loads(out)
    ids = [item["segment_id"] for item in payload["segments"]]
    assert ids[0] == corpus.khawatir.pk and len(ids) == len(set(ids))
    first = payload["segments"][0]
    assert first["title"] == "خواطر البقرة" and first["surah"] == 2
    assert isinstance(first["start_ms"], int) and first["excerpt"]

    out, _ = _run("smart_label", "الصبر عند الصدمة", "--no-llm")
    assert f"segment {corpus.khawatir.pk}" in out and "expected_segment_ids" in out


def test_smart_eval_refuses_unlabelled_sets(built: int, tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text('{"id": "a", "question": "q", "expected_status": "not_found"}\n')
    with pytest.raises(CommandError, match="no labelled items"):
        _run("smart_eval", "--golden", str(golden))

    with pytest.raises(CommandError):
        _run("smart_eval", "--golden", str(tmp_path / "missing.jsonl"))
