"""Upload the raw corpus MP3s to Cloudflare R2 and emit a surah/ayah → key mapping.

``python -m pipeline.upload_r2`` (from the repo root, creds in the environment —
``scripts/upload_r2_local.sh`` sources ``.env.local`` and does both).

The 11-CD corpus under ``data/`` is pushed **as-is** (no transcode) to
``corpus/mp3/{surah:03d}/{surah:03d}_{start:03d}_{end:03d}.mp3`` — the key is
rebuilt from the parsed surah/ayah integers, never copied from the filename, so
the one dash-variant name normalizes for free. When every discovered file is
accounted for, a mapping JSON (``files`` list + per-ayah ``index``) is written
locally and mirrored to the bucket.

Idempotent and resumable per project rule 6: every completed file is appended to
a JSONL checkpoint keyed by content hash; a re-run skips checkpointed files
without touching the network, HEADs the destination for the rest, and only PUTs
what is missing. Single-part PUTs mean the response ETag is the body MD5 — a
mismatch is a hard failure and never checkpointed.

This module is stdlib + boto3 on purpose — no Django, no database. The mapping
comes from filenames and hashing alone; ``backend/segments_export.json`` is only
used to cross-check hashes and borrow ``duration_ms``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from pipeline import parsers

R2_ENDPOINT_DEFAULT = "https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com"
BUCKET_DEFAULT = "shaarawy"
KEY_PREFIX = "corpus/mp3"
MAPPING_KEY = "corpus/r2_corpus_mapping.json"
HASH_CHUNK = 1024 * 1024

UPLOADED = "uploaded"
EXISTS = "exists"


@dataclass(frozen=True)
class CorpusFile:
    """One MP3 of the corpus, as discovered on disk."""

    path: Path
    rel_path: str
    """Posix path relative to the data root — the stable identity across machines."""
    cd: int
    surah: int
    ayah_start: int
    ayah_end: int
    size_bytes: int

    @property
    def r2_key(self) -> str:
        return r2_key(self.surah, self.ayah_start, self.ayah_end)


def r2_key(surah: int, ayah_start: int, ayah_end: int) -> str:
    """The bucket key for one ayah-range file, zero-padded like the corpus names."""
    return f"{KEY_PREFIX}/{surah:03d}/{surah:03d}_{ayah_start:03d}_{ayah_end:03d}.mp3"


def discover_files(data_root: Path) -> list[CorpusFile]:
    """Every corpus MP3 under ``data_root``, sorted by (surah, ayah range).

    Raises ``ValueError`` on anything the mapping could not represent: an
    unparseable name, a file outside a ``CD-<n>`` directory, or two files
    claiming the same key. Non-audio files are ignored.
    """
    found: dict[str, CorpusFile] = {}
    for path in parsers.audio_files(data_root):
        rel = path.relative_to(data_root).as_posix()
        parsed = parsers.parse_filename(path.name)
        if parsed is None or parsed.surah is None or parsed.ayah_start is None:
            raise ValueError(f"unparseable corpus filename: {rel}")
        cd = next((part for part in rel.split("/") if part.startswith("CD-")), None)
        if cd is None or not cd.removeprefix("CD-").isdigit():
            raise ValueError(f"no CD-<n> directory in path: {rel}")
        ayah_end = parsed.ayah_end if parsed.ayah_end is not None else parsed.ayah_start
        corpus_file = CorpusFile(
            path=path,
            rel_path=rel,
            cd=int(cd.removeprefix("CD-")),
            surah=parsed.surah,
            ayah_start=parsed.ayah_start,
            ayah_end=ayah_end,
            size_bytes=path.stat().st_size,
        )
        clash = found.get(corpus_file.r2_key)
        if clash is not None:
            raise ValueError(
                f"duplicate key {corpus_file.r2_key}: {clash.rel_path} and {rel}"
            )
        found[corpus_file.r2_key] = corpus_file
    return sorted(found.values(), key=lambda cf: (cf.surah, cf.ayah_start, cf.ayah_end))


def hash_file(path: Path) -> tuple[str, str]:
    """``(sha256, md5)`` hex digests of ``path`` in one buffered pass."""
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            sha256.update(chunk)
            md5.update(chunk)
    return sha256.hexdigest(), md5.hexdigest()


def build_client(endpoint_url: str, workers: int) -> Any:
    """S3 client for R2 from ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY`` env vars."""
    import boto3
    from botocore.config import Config

    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if not access_key or not secret_key:
        raise SystemExit(
            "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set — "
            "source .env.local or use scripts/upload_r2_local.sh"
        )
    if len(access_key) != 32:
        raise SystemExit(
            f"R2_ACCESS_KEY_ID has length {len(access_key)}, expected 32. "
            "Use the S3 access key of an R2 API token, not a Cloudflare API token id."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            max_pool_connections=workers + 4,
            retries={"max_attempts": 8, "mode": "standard"},
            # boto3 >= 1.36 injects CRC32 checksums by default, which R2 rejects
            # in some modes; single-part PUTs already verify via ETag == MD5.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def head_object(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    """HEAD ``key`` or ``None`` when it does not exist (or is unreadable)."""
    import botocore.exceptions

    try:
        return client.head_object(Bucket=bucket, Key=key)
    except botocore.exceptions.ClientError:
        return None


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def upload_one(client: Any, bucket: str, corpus_file: CorpusFile) -> dict[str, Any]:
    """Hash one file, then PUT it unless the destination already has these bytes.

    An existing object counts only when its size matches and its ETag is either
    the local MD5 or a multipart ETag (where size is the best available check);
    anything else is overwritten. A PUT whose response ETag differs from the
    local MD5 raises — the record is never checkpointed.
    """
    sha256, md5 = hash_file(corpus_file.path)
    record: dict[str, Any] = {
        "source_path": corpus_file.rel_path,
        "r2_key": corpus_file.r2_key,
        "surah": corpus_file.surah,
        "ayah_start": corpus_file.ayah_start,
        "ayah_end": corpus_file.ayah_end,
        "cd": corpus_file.cd,
        "sha256": sha256,
        "md5": md5,
        "size_bytes": corpus_file.size_bytes,
        "uploaded_at": _utcnow(),
    }
    head = head_object(client, bucket, corpus_file.r2_key)
    if head is not None and int(head["ContentLength"]) == corpus_file.size_bytes:
        etag = str(head.get("ETag", "")).strip('"')
        if etag == md5 or "-" in etag:
            record["etag"] = etag
            record["outcome"] = EXISTS
            return record
    with corpus_file.path.open("rb") as handle:
        response = client.put_object(
            Bucket=bucket, Key=corpus_file.r2_key, Body=handle, ContentType="audio/mpeg"
        )
    etag = str(response.get("ETag", "")).strip('"')
    if etag != md5:
        raise RuntimeError(
            f"{corpus_file.r2_key}: response ETag {etag!r} != local md5 {md5!r}"
        )
    record["etag"] = etag
    record["outcome"] = UPLOADED
    return record


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    """Completed records keyed by ``r2_key``; later lines win.

    Only a corrupt *final* line (an append killed mid-write) is tolerated;
    corruption anywhere else means the file cannot be trusted, so it raises.
    """
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            if lineno == len(lines):
                print(f"warning: dropping truncated final line of {path}", file=sys.stderr)
                continue
            raise ValueError(f"corrupt checkpoint line {lineno} in {path}") from exc
        records[record["r2_key"]] = record
    return records


def cross_check(
    records: list[dict[str, Any]], export_path: Path | None
) -> tuple[int, int, int]:
    """Borrow ``duration_ms`` from the segments export where the sha256 agrees.

    Joined on ``(surah, ayah_start, ayah_end)``. Returns ``(matched, mismatched,
    missing)``; never fatal — a missing export just leaves ``duration_ms`` null.
    Only the export's raw-file fields are trusted: its ``audio.size_bytes`` and
    ``mime`` describe the transcoded Opus and are deliberately not compared.
    """
    for record in records:
        record.setdefault("duration_ms", None)
    if export_path is None or not export_path.exists():
        print(f"warning: segments export not found at {export_path}; duration_ms left null")
        return 0, 0, len(records)
    by_range: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for entry in json.loads(export_path.read_text(encoding="utf-8")):
        surah, start, end = entry.get("surah"), entry.get("ayah_start"), entry.get("ayah_end")
        if surah is None or start is None or end is None:
            continue
        by_range.setdefault((surah, start, end), []).append(entry)
    matched = mismatched = missing = 0
    for record in records:
        candidates = by_range.get((record["surah"], record["ayah_start"], record["ayah_end"]), [])
        hit = next(
            (e for e in candidates if e.get("audio", {}).get("sha256") == record["sha256"]), None
        )
        if hit is not None:
            record["duration_ms"] = hit.get("duration_ms")
            matched += 1
        elif candidates:
            mismatched += 1
            print(f"warning: sha256 mismatch vs segments export for {record['r2_key']}")
        else:
            missing += 1
    return matched, mismatched, missing


def build_mapping(
    records: list[dict[str, Any]], *, bucket: str, endpoint: str, generated_at: str
) -> dict[str, Any]:
    """The mapping document: a ``files`` list and a surah → ayah → key ``index``."""
    ordered = sorted(records, key=lambda r: (r["surah"], r["ayah_start"], r["ayah_end"]))
    fields = (
        "surah",
        "ayah_start",
        "ayah_end",
        "cd",
        "source_path",
        "r2_key",
        "sha256",
        "size_bytes",
        "etag",
        "duration_ms",
    )
    index: dict[str, dict[str, str]] = {}
    for record in ordered:
        per_surah = index.setdefault(str(record["surah"]), {})
        for ayah in range(record["ayah_start"], record["ayah_end"] + 1):
            per_surah[str(ayah)] = record["r2_key"]
    return {
        "meta": {
            "generated_at": generated_at,
            "generator": "pipeline.upload_r2",
            "bucket": bucket,
            "endpoint": endpoint,
            "key_prefix": KEY_PREFIX + "/",
            "file_count": len(ordered),
            "surah_count": len(index),
            "total_size_bytes": sum(r["size_bytes"] for r in ordered),
        },
        "files": [{field: record.get(field) for field in fields} for record in ordered],
        "index": index,
    }


def verify_keys(
    client: Any, bucket: str, files: list[CorpusFile], workers: int, check_mapping: bool
) -> int:
    """HEAD every expected key and compare sizes. Returns the exit code."""
    problems = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(head_object, client, bucket, cf.r2_key): cf for cf in files
        }
        for future in as_completed(futures):
            corpus_file = futures[future]
            head = future.result()
            if head is None:
                problems += 1
                print(f"MISSING {corpus_file.r2_key}")
            elif int(head["ContentLength"]) != corpus_file.size_bytes:
                problems += 1
                print(
                    f"SIZE MISMATCH {corpus_file.r2_key}: "
                    f"remote {head['ContentLength']}, local {corpus_file.size_bytes}"
                )
    if check_mapping:
        if head_object(client, bucket, MAPPING_KEY) is None:
            problems += 1
            print(f"MISSING {MAPPING_KEY}")
        else:
            print(f"mapping present at {MAPPING_KEY}")
    print(f"verified {len(files)} key(s), {problems} problem(s)")
    return 1 if problems else 0


def _write_mapping(
    mapping: dict[str, Any],
    out_path: Path,
    client: Any | None,
    bucket: str,
) -> None:
    """Write the mapping locally and, when a client is given, mirror it to the bucket."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(mapping, ensure_ascii=False, indent=2)
    out_path.write_text(body + "\n", encoding="utf-8")
    print(f"mapping written to {out_path} ({len(mapping['files'])} files)")
    if client is not None:
        client.put_object(
            Bucket=bucket,
            Key=MAPPING_KEY,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        print(f"mapping uploaded to r2://{bucket}/{MAPPING_KEY}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.upload_r2",
        description="Upload the raw corpus MP3s to R2 and build the surah/ayah mapping JSON.",
    )
    parser.add_argument("--data-root", default="data", help="Corpus root (default: data).")
    parser.add_argument("--bucket", default=BUCKET_DEFAULT)
    parser.add_argument("--endpoint", default=R2_ENDPOINT_DEFAULT)
    parser.add_argument("--workers", type=int, default=8, help="Concurrent uploads (default: 8).")
    parser.add_argument("--limit", type=int, default=None, help="First N files only (smoke test).")
    parser.add_argument(
        "--checkpoint",
        default="data/r2_upload_checkpoint.jsonl",
        help="Append-only JSONL of completed files; delete it to force re-verification.",
    )
    parser.add_argument("--mapping-out", default="data/r2_corpus_mapping.json")
    parser.add_argument(
        "--segments-export",
        default="backend/segments_export.json",
        help="Export to cross-check sha256 and borrow duration_ms from (skipped if absent).",
    )
    parser.add_argument(
        "--no-upload-mapping",
        action="store_true",
        help="Do not mirror the mapping JSON to the bucket.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upload plan and exit. No credentials needed, no network.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="HEAD every expected key (and the mapping) instead of uploading.",
    )
    parser.add_argument(
        "--mapping-only",
        action="store_true",
        help="Rebuild the local mapping from the checkpoint. Never uploads anything.",
    )
    args = parser.parse_args(argv)

    files = discover_files(Path(args.data_root))
    if args.limit is not None:
        files = files[: args.limit]
    total_bytes = sum(cf.size_bytes for cf in files)
    surahs = len({cf.surah for cf in files})
    print(
        f"{len(files)} file(s), {total_bytes / 1e9:.2f} GB, {surahs} surah(s) "
        f"-> r2://{args.bucket}/{KEY_PREFIX}/"
    )

    if args.dry_run:
        for corpus_file in files:
            source_name = corpus_file.rel_path.rsplit("/", 1)[-1]
            if source_name != corpus_file.r2_key.rsplit("/", 1)[-1]:
                print(f"normalized: {corpus_file.rel_path} -> {corpus_file.r2_key}")
        if files:
            print(f"first: {files[0].r2_key}")
            print(f"last:  {files[-1].r2_key}")
        return 0

    checkpoint_path = Path(args.checkpoint)
    done = load_checkpoint(checkpoint_path)
    records: dict[str, dict[str, Any]] = {}
    todo: list[CorpusFile] = []
    for corpus_file in files:
        prior = done.get(corpus_file.r2_key)
        if prior is not None and prior.get("size_bytes") == corpus_file.size_bytes:
            records[corpus_file.r2_key] = prior
        else:
            todo.append(corpus_file)

    if args.mapping_only:
        if todo:
            print(f"warning: {len(todo)} of {len(files)} file(s) not in checkpoint; "
                  "mapping covers only the completed ones")
        cross_check(list(records.values()), Path(args.segments_export))
        mapping = build_mapping(
            list(records.values()),
            bucket=args.bucket,
            endpoint=args.endpoint,
            generated_at=_utcnow(),
        )
        _write_mapping(mapping, Path(args.mapping_out), None, args.bucket)
        return 1 if todo else 0

    if args.verify_only:
        client = build_client(args.endpoint, args.workers)
        return verify_keys(
            client, args.bucket, files, args.workers, check_mapping=args.limit is None
        )

    uploaded = exists = failed = 0
    if todo:
        client = build_client(args.endpoint, args.workers)
        started = monotonic()
        moved_bytes = 0
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            checkpoint_path.open("a", encoding="utf-8") as checkpoint,
            ThreadPoolExecutor(max_workers=args.workers) as pool,
        ):
            futures = {
                pool.submit(upload_one, client, args.bucket, cf): cf for cf in todo
            }
            for position, future in enumerate(as_completed(futures), start=1):
                corpus_file = futures[future]
                try:
                    record = future.result()
                except Exception as exc:  # logged and counted; the run continues
                    failed += 1
                    print(f"FAILED {corpus_file.rel_path}: {exc}")
                    continue
                checkpoint.write(json.dumps(record, ensure_ascii=False) + "\n")
                checkpoint.flush()
                records[record["r2_key"]] = record
                if record["outcome"] == UPLOADED:
                    uploaded += 1
                    moved_bytes += record["size_bytes"]
                else:
                    exists += 1
                if position % 100 == 0 or position == len(todo):
                    rate = moved_bytes / 1e6 / max(monotonic() - started, 0.001)
                    print(
                        f"[{position}/{len(todo)}] uploaded {uploaded}, "
                        f"already-present {exists}, failed {failed}, {rate:.1f} MB/s"
                    )
    skipped = len(files) - len(todo)
    print(
        f"done: uploaded {uploaded}, already-present {exists}, "
        f"checkpoint-skipped {skipped}, failed {failed}"
    )

    if failed or len(records) < len(files):
        print("incomplete run — mapping not written; fix failures and re-run")
        return 1
    if args.limit is not None:
        print("limit set — mapping not written (run without --limit to build it)")
        return 0

    matched, mismatched, missing = cross_check(
        list(records.values()), Path(args.segments_export)
    )
    print(f"cross-check vs segments export: {matched} matched, "
          f"{mismatched} mismatched, {missing} not in export")
    mapping = build_mapping(
        list(records.values()),
        bucket=args.bucket,
        endpoint=args.endpoint,
        generated_at=_utcnow(),
    )
    upload_client: Any | None = None
    if not args.no_upload_mapping and args.limit is None:
        upload_client = build_client(args.endpoint, args.workers)
    _write_mapping(mapping, Path(args.mapping_out), upload_client, args.bucket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
