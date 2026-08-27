# Corpus database snapshot

`shaarawy.sql.xz` is an xz-compressed plain-SQL `pg_dump --no-owner` of the
corpus database (all transcripts, word alignments, chunks, segments, Quran
text; no Django users/sessions), committed so any host can pull it with the
repo. `shaarawy.sql.xz.sha256` is its checksum and `shaarawy.dump.counts.txt`
lists the row counts at dump time.

The same snapshot in `pg_dump --format=custom` form (`shaarawy.dump`, ~130 MB)
is too large for GitHub's 100 MB file limit, so it lives in R2 instead:
`r2://shaarawy/backups/postgres/postgres-<UTC stamp>.dump` (+ `.sha256`), the
latest being the one whose stamp matches `shaarawy.dump.counts.txt`.
`shaarawy.dump.sha256` is the checksum of that R2 object. `*.dump` and `*.sql`
are gitignored — only `db/shaarawy.sql.xz` is allowed through (`.gitignore`).

## Restore from the committed SQL snapshot

```bash
sha256sum -c db/shaarawy.sql.xz.sha256
createdb -U postgres shaarawy                      # or: docker compose exec -T db createdb -U postgres shaarawy
xz -dc db/shaarawy.sql.xz | psql -U postgres -d shaarawy -v ON_ERROR_STOP=1 -q
#   (docker: xz -dc db/shaarawy.sql.xz | docker compose exec -T db psql -U postgres -d shaarawy -v ON_ERROR_STOP=1 -q)
```

The dump needs the `vector` extension available on the server
(postgres+pgvector image / `postgresql-16-pgvector`).

## Restore from the R2 custom-format dump

```bash
scripts/restore.sh backups/postgres/postgres-<STAMP>.dump shaarawy docker-compose.yml      # dev/worker host
scripts/restore.sh backups/postgres/postgres-<STAMP>.dump "$DB_NAME" docker-compose.prod.yml # production (see DEPLOY.md §8)
```

Then verify against the counts file:

```bash
docker compose exec -T db psql -U postgres -d shaarawy -tAc "
SELECT 'segments:'||status||'='||count(*) FROM corpus_segment GROUP BY status
UNION ALL SELECT 'transcripts='||count(*) FROM corpus_transcript
UNION ALL SELECT 'words='||count(*) FROM corpus_transcriptword
UNION ALL SELECT 'chunks='||count(*) FROM corpus_chunk;"
```

The snapshot contains no Django users, sessions or admin log entries
(`--exclude-table-data=auth_user --exclude-table-data=django_session`); create
accounts on the target host.

## Refreshing the snapshot

```bash
export PGPASSWORD=postgres   # or go through docker compose exec -T db …
pg_dump -h localhost -U postgres -d shaarawy --format=plain --no-owner \
  --exclude-table-data=auth_user --exclude-table-data=django_session | xz -T8 -9 > db/shaarawy.sql.xz
sha256sum db/shaarawy.sql.xz > db/shaarawy.sql.xz.sha256
pg_dump -h localhost -U postgres -d shaarawy --format=custom --no-owner \
  --exclude-table-data=auth_user --exclude-table-data=django_session > db/shaarawy.dump   # upload to R2, do not commit
sha256sum db/shaarawy.dump > db/shaarawy.dump.sha256
```

and regenerate `shaarawy.dump.counts.txt` with the query above.
