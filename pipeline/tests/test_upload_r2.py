"""Offline tests for ``pipeline.upload_r2`` — no database, no network.

``FakeS3Client`` stands in for boto3: it records HEAD/PUT calls and returns
single-part ETags (the body MD5), which is exactly the contract the uploader's
integrity check relies on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import botocore.exceptions
import pytest

from pipeline import upload_r2
from pipeline.parsers import parse_filename


def make_tree(root: Path, spec: dict[str, bytes]) -> None:
    for rel, data in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class FakeS3Client:
    def __init__(self, objects: dict[str, bytes] | None = None, bad_etag: bool = False) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})
        self.multipart_keys: set[str] = set()
        self.bad_etag = bad_etag
        self.head_calls: list[str] = []
        self.put_calls: list[str] = []

    def _etag(self, key: str) -> str:
        if key in self.multipart_keys:
            return "0123456789abcdef-2"
        return hashlib.md5(self.objects[key], usedforsecurity=False).hexdigest()

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.head_calls.append(Key)
        if Key not in self.objects:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )
        return {"ContentLength": len(self.objects[Key]), "ETag": f'"{self._etag(Key)}"'}

    def put_object(self, *, Bucket: str, Key: str, Body: Any, ContentType: str) -> dict[str, Any]:
        data = Body if isinstance(Body, bytes) else Body.read()
        self.put_calls.append(Key)
        self.objects[Key] = data
        etag = "0" * 32 if self.bad_etag else self._etag(Key)
        return {"ETag": f'"{etag}"'}


def main_args(data: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--data-root", str(data),
        "--checkpoint", str(tmp_path / "checkpoint.jsonl"),
        "--mapping-out", str(tmp_path / "mapping.json"),
        "--segments-export", str(tmp_path / "absent_export.json"),
        "--no-upload-mapping",
        "--workers", "2",
        *extra,
    ]


# --- key building -----------------------------------------------------------


def test_r2_key_zero_padding() -> None:
    assert upload_r2.r2_key(1, 2, 7) == "corpus/mp3/001/001_002_007.mp3"


def test_dash_variant_normalizes() -> None:
    parsed = parse_filename("038_065-068.mp3")
    assert parsed is not None
    assert parsed.surah is not None and parsed.ayah_start is not None
    assert parsed.ayah_end is not None
    key = upload_r2.r2_key(parsed.surah, parsed.ayah_start, parsed.ayah_end)
    assert key == "corpus/mp3/038/038_065_068.mp3"


# --- discovery --------------------------------------------------------------


def test_discover_files(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            "CD-2/004 x/004_010_012.mp3": b"bb",
            "CD-1/001 alfat7a/001_001_007.mp3": b"a",
            "CD-1/001 alfat7a/cover.jpg": b"jpg",
            "CD-1/Thumbs.db": b"junk",
        },
    )
    files = upload_r2.discover_files(tmp_path)
    assert [cf.r2_key for cf in files] == [
        "corpus/mp3/001/001_001_007.mp3",
        "corpus/mp3/004/004_010_012.mp3",
    ]
    assert (files[0].cd, files[1].cd) == (1, 2)
    assert files[0].size_bytes == 1
    assert files[0].rel_path == "CD-1/001 alfat7a/001_001_007.mp3"


def test_discover_rejects_unparseable(tmp_path: Path) -> None:
    make_tree(tmp_path, {"CD-1/junk/badname.mp3": b"a"})
    with pytest.raises(ValueError, match="unparseable"):
        upload_r2.discover_files(tmp_path)


def test_discover_rejects_missing_cd_dir(tmp_path: Path) -> None:
    make_tree(tmp_path, {"001_001_002.mp3": b"a"})
    with pytest.raises(ValueError, match="CD-<n>"):
        upload_r2.discover_files(tmp_path)


def test_discover_rejects_duplicate_key(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            "CD-1/001 a/001_001_007.mp3": b"a",
            "CD-2/001 b/001_001_007.mp3": b"b",
        },
    )
    with pytest.raises(ValueError, match="duplicate key"):
        upload_r2.discover_files(tmp_path)


# --- checkpoint -------------------------------------------------------------


def test_load_checkpoint_missing(tmp_path: Path) -> None:
    assert upload_r2.load_checkpoint(tmp_path / "nope.jsonl") == {}


def test_load_checkpoint_later_line_wins(tmp_path: Path) -> None:
    path = tmp_path / "cp.jsonl"
    path.write_text(
        json.dumps({"r2_key": "k", "size_bytes": 1}) + "\n"
        + json.dumps({"r2_key": "k", "size_bytes": 2}) + "\n",
        encoding="utf-8",
    )
    assert upload_r2.load_checkpoint(path)["k"]["size_bytes"] == 2


def test_load_checkpoint_drops_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "cp.jsonl"
    path.write_text(
        json.dumps({"r2_key": "k", "size_bytes": 1}) + '\n{"r2_key": "half',
        encoding="utf-8",
    )
    assert list(upload_r2.load_checkpoint(path)) == ["k"]


def test_load_checkpoint_corrupt_middle_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "cp.jsonl"
    path.write_text(
        '{"broken\n' + json.dumps({"r2_key": "k", "size_bytes": 1}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="corrupt checkpoint line 1"):
        upload_r2.load_checkpoint(path)


# --- upload + resume through main() -----------------------------------------


def corpus_tree(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    make_tree(
        data,
        {
            "CD-1/001 alfat7a/001_001_003.mp3": b"first-file",
            "CD-9/038 sad/038_065-068.mp3": b"dash-variant-file",
        },
    )
    return data


def test_main_uploads_then_resumes_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = corpus_tree(tmp_path)
    fake = FakeS3Client()
    monkeypatch.setattr(upload_r2, "build_client", lambda endpoint, workers: fake)

    assert upload_r2.main(main_args(data, tmp_path)) == 0
    assert sorted(fake.put_calls) == [
        "corpus/mp3/001/001_001_003.mp3",
        "corpus/mp3/038/038_065_068.mp3",
    ]
    mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["meta"]["file_count"] == 2
    assert mapping["index"]["38"]["67"] == "corpus/mp3/038/038_065_068.mp3"

    # Complete checkpoint: the second run must not even build a client.
    def boom(endpoint: str, workers: int) -> Any:
        raise AssertionError("client built on a fully checkpointed run")

    monkeypatch.setattr(upload_r2, "build_client", boom)
    assert upload_r2.main(main_args(data, tmp_path)) == 0


def test_main_reuploads_when_source_size_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = corpus_tree(tmp_path)
    fake = FakeS3Client()
    monkeypatch.setattr(upload_r2, "build_client", lambda endpoint, workers: fake)
    assert upload_r2.main(main_args(data, tmp_path)) == 0

    (data / "CD-1/001 alfat7a/001_001_003.mp3").write_bytes(b"changed-and-longer")
    fake.put_calls.clear()
    assert upload_r2.main(main_args(data, tmp_path)) == 0
    assert fake.put_calls == ["corpus/mp3/001/001_001_003.mp3"]


def test_main_head_hit_skips_put(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = corpus_tree(tmp_path)
    fake = FakeS3Client(
        objects={
            "corpus/mp3/001/001_001_003.mp3": b"first-file",
            "corpus/mp3/038/038_065_068.mp3": b"dash-variant-file",
        }
    )
    monkeypatch.setattr(upload_r2, "build_client", lambda endpoint, workers: fake)
    assert upload_r2.main(main_args(data, tmp_path)) == 0
    assert fake.put_calls == []
    assert len(fake.head_calls) == 2
    checkpoint = upload_r2.load_checkpoint(tmp_path / "checkpoint.jsonl")
    assert all(record["outcome"] == "exists" for record in checkpoint.values())


def test_main_etag_mismatch_fails_and_is_not_checkpointed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = corpus_tree(tmp_path)
    fake = FakeS3Client(bad_etag=True)
    monkeypatch.setattr(upload_r2, "build_client", lambda endpoint, workers: fake)
    assert upload_r2.main(main_args(data, tmp_path)) == 1
    assert upload_r2.load_checkpoint(tmp_path / "checkpoint.jsonl") == {}
    assert not (tmp_path / "mapping.json").exists()


def test_main_dry_run_builds_no_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = corpus_tree(tmp_path)

    def boom(endpoint: str, workers: int) -> Any:
        raise AssertionError("dry run must not build a client")

    monkeypatch.setattr(upload_r2, "build_client", boom)
    assert upload_r2.main(main_args(data, tmp_path, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "2 file(s)" in out
    assert "normalized: CD-9/038 sad/038_065-068.mp3 -> corpus/mp3/038/038_065_068.mp3" in out


# --- mapping ----------------------------------------------------------------


def record(surah: int, start: int, end: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "surah": surah,
        "ayah_start": start,
        "ayah_end": end,
        "cd": 1,
        "source_path": f"CD-1/x/{surah:03d}_{start:03d}_{end:03d}.mp3",
        "r2_key": upload_r2.r2_key(surah, start, end),
        "sha256": f"sha-{surah}-{start}",
        "md5": "m",
        "size_bytes": 10,
        "etag": "e",
        "duration_ms": None,
    }
    base.update(overrides)
    return base


def test_build_mapping_expands_ranges_and_sorts() -> None:
    mapping = upload_r2.build_mapping(
        [record(38, 65, 68), record(1, 1, 3)],
        bucket="shaarawy",
        endpoint="https://example.com",
        generated_at="2026-08-24T00:00:00Z",
    )
    assert mapping["meta"]["file_count"] == 2
    assert mapping["meta"]["surah_count"] == 2
    assert mapping["meta"]["total_size_bytes"] == 20
    assert [f["surah"] for f in mapping["files"]] == [1, 38]
    key = "corpus/mp3/038/038_065_068.mp3"
    assert mapping["index"]["38"] == {"65": key, "66": key, "67": key, "68": key}
    assert set(mapping["index"]["1"]) == {"1", "2", "3"}
    assert "md5" not in mapping["files"][0]


def test_cross_check_joins_duration_on_sha_match(tmp_path: Path) -> None:
    export = tmp_path / "export.json"
    export.write_text(
        json.dumps(
            [
                {"surah": 1, "ayah_start": 1, "ayah_end": 3, "duration_ms": 1234,
                 "audio": {"sha256": "sha-1-1"}},
                {"surah": 38, "ayah_start": 65, "ayah_end": 68, "duration_ms": 999,
                 "audio": {"sha256": "different"}},
                {"surah": 2, "ayah_start": None, "ayah_end": None, "duration_ms": 1,
                 "audio": {"sha256": "irrelevant"}},
            ]
        ),
        encoding="utf-8",
    )
    records = [record(1, 1, 3), record(38, 65, 68), record(3, 1, 2)]
    matched, mismatched, missing = upload_r2.cross_check(records, export)
    assert (matched, mismatched, missing) == (1, 1, 1)
    assert records[0]["duration_ms"] == 1234
    assert records[1]["duration_ms"] is None


def test_cross_check_missing_export_is_not_fatal(tmp_path: Path) -> None:
    records = [record(1, 1, 3)]
    matched, mismatched, missing = upload_r2.cross_check(records, tmp_path / "absent.json")
    assert (matched, mismatched, missing) == (0, 0, 1)
    assert records[0]["duration_ms"] is None


# --- verify -----------------------------------------------------------------


def test_verify_keys_reports_missing_and_mismatched(tmp_path: Path) -> None:
    data = corpus_tree(tmp_path)
    files = upload_r2.discover_files(data)
    fake = FakeS3Client(objects={"corpus/mp3/001/001_001_003.mp3": b"wrong-size!"})
    assert upload_r2.verify_keys(fake, "shaarawy", files, 2, check_mapping=False) == 1

    ok = FakeS3Client(
        objects={
            "corpus/mp3/001/001_001_003.mp3": b"first-file",
            "corpus/mp3/038/038_065_068.mp3": b"dash-variant-file",
        }
    )
    assert upload_r2.verify_keys(ok, "shaarawy", files, 2, check_mapping=False) == 0
