"""Standalone ingestion pipeline: audio files in, timestamped words out.

This package is deliberately **outside** the Django project. Django never
imports it (``grep -rn "import pipeline" backend/`` must stay empty); the two
halves talk through the database and the ``pipeline`` Celery queue only. That
keeps torch / faster-whisper / ctc-forced-aligner out of the web image.

The pipeline *does* import Django — it owns the writes to ``corpus`` models —
which is why every entry point calls :func:`pipeline.django_setup.setup_django`
before touching an ORM class.

Entry points
------------
``python -m pipeline.run --folder F --source-title T --kind khawatir``
    Synchronous in-process driver: the one command that ingests a folder.
``python -m pipeline.parsers --dry-run FOLDER``
    Filename parser preview; writes nothing, needs no database.
``python -m pipeline.upload_r2``
    Raw corpus MP3s → R2 + surah/ayah mapping JSON; needs no database.
``celery -A pipeline.celery_app worker -Q pipeline``
    Async worker for the stages dispatched by ``manage.py run_pipeline``.
"""
