"""Rebuild ``data/`` from the raw MP3s in R2 on a fresh worker host.

``python scripts/fetch_corpus_from_r2.py [--data-root data] [--workers 8]``
(run from the repo root; R2 credentials in ``R2_ACCESS_KEY_ID`` /
``R2_SECRET_ACCESS_KEY``, e.g. ``set -a; . ./.env.local; set +a``).

Reads ``corpus/r2_corpus_mapping.json`` (written by ``pipeline.upload_r2``) and
downloads every ``r2_key`` to its original ``source_path`` under the data root.
The pipeline keys segments on the file's sha256 and records paths relative to
the repo root, so the layout must match the machine that ingested — this
restores ``data/CD-N/<surah folder>/<file>.mp3`` byte for byte. Idempotent: a
file whose sha256 already matches is skipped, so re-running resumes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3

ENDPOINT = os.environ.get(
    "R2_ENDPOINT_URL", "https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com"
)
BUCKET = os.environ.get("R2_BUCKET", "shaarawy")
MAPPING_KEY = "corpus/r2_corpus_mapping.json"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(client: object, record: dict[str, object], data_root: Path) -> str:
    target = data_root / str(record["source_path"])
    if target.exists() and sha256_of(target) == record["sha256"]:
        return "skipped"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    client.download_file(BUCKET, str(record["r2_key"]), str(partial))  # type: ignore[attr-defined]
    if sha256_of(partial) != record["sha256"]:
        partial.unlink()
        raise ValueError(f"sha256 mismatch after download: {record['r2_key']}")
    partial.replace(target)
    return "downloaded"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            print(f"{name} is not set", file=sys.stderr)
            return 2
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="auto",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    mapping = json.loads(client.get_object(Bucket=BUCKET, Key=MAPPING_KEY)["Body"].read())
    files = mapping["files"]
    data_root = Path(args.data_root)
    print(f"{len(files)} files in {MAPPING_KEY}; data root {data_root.resolve()}")

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, client, record, data_root): record for record in files}
        for done, future in enumerate(as_completed(futures), 1):
            record = futures[future]
            try:
                counts[future.result()] += 1
            except (OSError, ValueError, boto3.exceptions.Boto3Error) as exc:
                counts["failed"] += 1
                print(f"FAILED {record['source_path']}: {exc}", file=sys.stderr)
            if done % 200 == 0 or done == len(files):
                print(f"{done}/{len(files)} {counts}", flush=True)
    print(f"done: {counts}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
