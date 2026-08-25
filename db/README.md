# Corpus database snapshot

`shaarawy.dump` is a `pg_dump --format=custom --no-owner` of the corpus
database, committed so a worker host can pull it with the repo instead of
fetching it from R2. `shaarawy.dump.counts.txt` lists the row counts at dump
time and `shaarawy.dump.sha256` its checksum. `*.dump` is otherwise ignored
by git — only this file is allowed through (`.gitignore`).

Restore it into a fresh database on any host running the compose stack:

```bash
sha256sum -c db/shaarawy.dump.sha256
scripts/restore.sh db/shaarawy.dump shaarawy docker-compose.yml      # dev/worker host
scripts/restore.sh db/shaarawy.dump "$DB_NAME" docker-compose.prod.yml # production (see DEPLOY.md §8)
```

Then verify against the counts file:

```bash
docker compose exec -T db psql -U postgres -d shaarawy -tAc "
SELECT 'segments:'||status||'='||count(*) FROM corpus_segment GROUP BY status
UNION ALL SELECT 'transcripts='||count(*) FROM corpus_transcript
UNION ALL SELECT 'words='||count(*) FROM corpus_transcriptword
UNION ALL SELECT 'chunks='||count(*) FROM corpus_chunk;"
```

The snapshot contains no Django users, sessions or admin log entries (the
dev database had none); create accounts on the target host. Before refreshing
it from a database that has accounts, add
`--exclude-table-data=auth_user --exclude-table-data=django_session` to the
`pg_dump` below so credentials never enter git history.

To refresh the snapshot after more of the corpus has been processed:

```bash
docker compose exec -T db pg_dump -U postgres -d "${DB_NAME:-postgres}" --format=custom --no-owner > db/shaarawy.dump
sha256sum db/shaarawy.dump > db/shaarawy.dump.sha256
```
