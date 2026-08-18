# Deploying the Sha'rawy Archive

Cold deploy on a clean Linux host with Docker + Compose v2 and the `aws` CLI.

## 1. Prepare

```bash
git clone <repo> /srv/shaarawy && cd /srv/shaarawy
cp .env.prod .env            # then edit every value marked change-me
```

Required values in `.env`:
- `SECRET_KEY`, `DB_PASSWORD`, `MEILI_MASTER_KEY` — long random strings.
- `AUDIO_S3_*` — Cloudflare R2 credentials for bucket `shaarawy`
  (endpoint `https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com`).
- `DOMAIN_NAME`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`,
  `NEXT_PUBLIC_API_URL` — your domain.
- Behind Cloudflare's proxy set `SECURE_SSL_REDIRECT=False` (Cloudflare terminates TLS).

## 2. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

`entrypoint.sh` waits for Postgres, migrates (incl. `CREATE EXTENSION vector`),
and collects static files. Caddy answers on 80/443 and provisions certificates
for `DOMAIN_NAME` automatically.

## 3. Seed data

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py import_quran
```

Audio ingestion runs from a (GPU) worker host with `pipeline/requirements.txt`
installed, pointed at this stack's Redis and Postgres:

```bash
celery -A pipeline.celery_app worker -Q pipeline   # long-running worker
python -m pipeline.run --folder /data/mp3s --source-title "خواطر التلفزيون المصري" --kind khawatir
```

## 4. Verify

```bash
curl -fsS https://$DOMAIN/healthz     # liveness: {"status":"ok"}
curl -fsS https://$DOMAIN/readyz      # readiness: db/redis/meilisearch all true
curl -fsS "https://$DOMAIN/api/surahs/" | head -c 200
```

## 5. Backups

Nightly cron on the host:

```cron
15 3 * * * cd /srv/shaarawy && set -a && . ./.env && set +a && ./scripts/backup.sh docker-compose.prod.yml >> /var/log/shaarawy-backup.log 2>&1
```

Backups are `pg_dump --format=custom` uploads to `s3://$AUDIO_S3_BUCKET/backups/postgres/`,
pruned after `BACKUP_KEEP_DAYS` (default 30).

**Verify a restore** (throwaway database — this is the test that matters):

```bash
./scripts/restore.sh backups/postgres/<latest>.dump restore_check docker-compose.prod.yml
# prints surahs=114 / ayahs=6236 on success
docker compose -f docker-compose.prod.yml exec db psql -U $DB_USER -d postgres -c "DROP DATABASE restore_check;"
```

The raw source audio is irreplaceable — keep an independent copy outside R2
(cold storage / offline drive), not just the transcoded Opus derivatives.

## 6. Updating

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Migrations run on container start. Meilisearch reindexing is only needed when
chunk data changes (`python manage.py shell` → `search.services.ensure_chunks_index()`
+ reindex, or re-run the pipeline `index` stage).
