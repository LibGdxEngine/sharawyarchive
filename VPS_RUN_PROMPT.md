# Brief for Claude Code on the rented GPU host

Paste everything below the line into Claude Code on the vast.ai instance
(after `git clone https://github.com/LibGdxEngine/sharawyarchive.git shaarawy && cd shaarawy`
and creating `.env.local`). It is written for a session with no memory of the
laptop work.

---

You are on a rented-by-the-hour vast.ai GPU instance. Your job: finish
transcribing and word-aligning the Sha'rawy audio corpus for this repository,
checkpoint the results off-box, and tell me when it is done so I can destroy
the instance. Every idle hour costs money — verify early, parallelize, and
never sit waiting without a monitor.

Read `CLAUDE.md` first (its rules are binding) and `DEPLOY.md` §9, which is the
runbook you are executing; `db/README.md` explains the database snapshot.

## What exists already

- The corpus is 4,357 MP3s / 670.9 hours. A laptop run finished 125 segments
  (plus 1 transcribed but not yet aligned); 4,231 segments are `pending`.
  That state is in `db/shaarawy.dump` (pg_dump custom format, sha256 beside it).
- All raw MP3s are in Cloudflare R2 (`corpus/mp3/`, mapping in
  `corpus/r2_corpus_mapping.json`); `scripts/fetch_corpus_from_r2.py` rebuilds
  `data/` byte-for-byte. The pipeline keys segments on file sha256 and records
  paths relative to the repo root, so that exact layout is required.
- The pipeline is `scripts/pipeline_corpus.sh` → `scripts/pipeline_local.sh`
  → `python -m pipeline.run`. Every stage is idempotent and resumable: a
  re-run skips finished stages in seconds and retries `failed` segments.
- Transcription is Cohere's hosted API (`ASR_BACKEND=cohere`, fast); word
  timings come from the local CTC aligner (`ctc-forced-aligner`, ONNX), which
  is ~90% of the work and is what the GPU is for.
- `.env.local` (I created it, mode 600, gitignored) holds `CO_API_KEY`,
  `AUDIO_S3_ACCESS_KEY_ID`, `AUDIO_S3_SECRET_ACCESS_KEY`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`. Check the names exist; never print the values.

## Hard rules

1. `ASR_BACKEND` must be `cohere`. Never run with `stub` engines or set
   `ALLOW_STUB_ENGINES` — the stub fabricates text.
2. Always launch with `PIPELINE_STORAGE=r2` and
   `AUDIO_S3_ENDPOINT_URL=https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com`
   so Opus/waveforms go straight to R2 (there is no MinIO here).
3. Restore the snapshot into a database named `shaarawy` and export
   `DB_NAME=shaarawy` for every pipeline/status command.
4. Do not change models, migrations, or pipeline stage logic. Fixing the host
   environment is in scope; changing what gets written to the database is not.
5. Never commit `.env.local` or any secret. Never run `docker compose down -v`.
6. Check `pgrep -f 'pipeline[.]run'` before launching anything — do not run
   two processes over the same folder.

## Steps

### 1. Host check (first 10 minutes — abandon the instance if this fails)

- `nvidia-smi` shows the GPU; `python3.12 --version`; `ffmpeg -version`.
- Decide the services path: if `docker info` works, follow DEPLOY.md §9 as
  written (`docker compose up -d db redis meilisearch`). If there is no Docker
  daemon (most vast.ai container listings), install natively instead:
  PostgreSQL 16 + `postgresql-16-pgvector` (PGDG repo), `redis-server`, and the
  Meilisearch v1.15 static binary; run Postgres on `localhost:5432` with role
  `postgres`/password `postgres`, Meilisearch on `:7700` with
  `--master-key` equal to `MEILI_MASTER_KEY` from `.env.dev`, Redis on `:6379`.
  Start them under `nohup` (no systemd). Then restore with
  `createdb -U postgres shaarawy && pg_restore -U postgres -d shaarawy --no-owner --exit-on-error db/shaarawy.dump`
  instead of `scripts/restore.sh`.
- Measure bandwidth: download the largest file from
  `corpus/r2_corpus_mapping.json` and time it. Below ~50 MB/s, tell me.

### 2. Python env with CUDA

Follow §9 step 2 (`pip install -r pipeline/requirements.txt`, swap
`onnxruntime` for `onnxruntime-gpu`, CUDA torch wheels, download the aligner
model with `ensure_onnx_model`). If `onnxruntime` complains about missing
libcublas/libcudnn: `pip install nvidia-cudnn-cu12 nvidia-cublas-cu12`.
Prove it: `CUDAExecutionProvider` must be in `onnxruntime.get_available_providers()`
and `torch.cuda.is_available()` must be True.

### 3. Database and audio

- Restore the snapshot (§9 step 3 or the native command above), then verify
  the counts match `db/shaarawy.dump.counts.txt`.
- `python scripts/fetch_corpus_from_r2.py --workers 16` (7.3 GB). It is
  resumable; re-run until `failed: 0`.

### 4. Prove the GPU is actually used (one segment)

Run one short folder, e.g.
`PIPELINE_STORAGE=r2 AUDIO_S3_ENDPOINT_URL=… DB_NAME=shaarawy scripts/pipeline_local.sh --folder "data/CD-11/113 alfalq" --until index`,
and watch `nvidia-smi` while the align stage runs. Then check
`corpus_pipelinerun`: the align row's duration divided by the segment's
`duration_ms/1000` must be far below 0.4 (the laptop CPU ratio). If the GPU
sits idle or the ratio is ~0.4, the aligner fell back to CPU — fix that before
going further (provider order, CUDA libs), and tell me if you cannot.

### 5. Full run, in parallel

Launch three detached processes on disjoint folder lists, each with the env
from rule 2 and `DB_NAME=shaarawy`, logs under `.omc/logs/`
(`setsid nohup … > .omc/logs/corpus-A.log 2>&1 < /dev/null &`):

- A: `data/CD-1 data/CD-2 data/CD-3 data/CD-4`
- B: `data/CD-5 data/CD-6 data/CD-7`
- C: `data/CD-8 data/CD-9 data/CD-10 data/CD-11`

Record `date -u +%FT%TZ > .omc/logs/corpus-run-start.txt` first;
`scripts/pipeline_status.sh` reads it. If host RAM or CPU is the limit, use
two processes instead of three; never two on the same folder.

Monitor every 30–60 minutes with `scripts/pipeline_status.sh` and
`nvidia-smi`; report to me hourly with: segments done, audio hours done,
effective ratio, failures, disk free. Watch disk — pause if free space drops
under 5 GB.

### 6. Checkpoints (do not let results live only on this box)

Every ~3 hours and at the end:

```bash
pg_dump -U postgres -d shaarawy --format=custom --no-owner > db/shaarawy.dump   # (via docker compose exec -T db … on the Docker path)
sha256sum db/shaarawy.dump > db/shaarawy.dump.sha256
```

then upload it to R2 under `backups/postgres/postgres-<UTC stamp>.dump` with
boto3 using the `R2_*` credentials (endpoint in rule 2, bucket `shaarawy`).
If `gh auth status` shows GitHub access, also commit and push
`db/shaarawy.dump*` with an updated `db/shaarawy.dump.counts.txt`
(conventional commit, e.g. `chore(db): snapshot after CD-1..4`); otherwise
skip git and tell me the R2 key.

### 7. Finish

When all three processes exit: re-run the same three commands once more
(they only touch `failed` segments); if anything still fails after two
passes, list it with the latest failure detail:

```sql
SELECT s.id, s.title, p.stage, left(p.detail, 200)
FROM corpus_segment s
JOIN LATERAL (SELECT * FROM corpus_pipelinerun p WHERE p.segment_id = s.id
              AND p.status = 'failed' ORDER BY p.started_at DESC LIMIT 1) p ON true
WHERE s.status = 'failed';
```

Done means: `pending = 0`, `SELECT engine, count(*) FROM corpus_transcript GROUP BY engine`
shows only `cohere-transcribe`, the word-timing sanity checks return 0
(overlapping consecutive words per transcript; `end_ms > segment.duration_ms`;
`end_ms <= start_ms`), the final dump is in R2 (and pushed, if possible), and
`db/shaarawy.dump.counts.txt` reflects it. Report those numbers, the total
GPU-hours used, and the failure list. Then stop — I destroy the instance.
