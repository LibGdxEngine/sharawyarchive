"""Tests for the run_pipeline management command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

_MODULE = "corpus.management.commands.run_pipeline.celery_app"


@pytest.mark.django_db
def test_run_pipeline_dispatches_correct_task_name_and_kwargs(tmp_path: Path) -> None:
    """send_task is called with the pipeline.ingest task name and the CLI kwargs."""
    mock_result = MagicMock()
    mock_result.id = "test-task-abc-123"

    with patch(_MODULE) as mock_celery:
        mock_celery.send_task.return_value = mock_result
        call_command(
            "run_pipeline",
            folder=str(tmp_path),
            source_title="Sheikh Test",
            kind="khawatir",
            limit=5,
            surah=2,
        )

    mock_celery.send_task.assert_called_once_with(
        "pipeline.ingest",
        kwargs={
            "folder": str(tmp_path),
            "source_title": "Sheikh Test",
            "kind": "khawatir",
            "limit": 5,
            "surah": 2,
        },
    )


@pytest.mark.django_db
def test_run_pipeline_dispatches_with_none_limit_and_surah(tmp_path: Path) -> None:
    """Omitted optional args are forwarded as None (not omitted from kwargs)."""
    mock_result = MagicMock()
    mock_result.id = "test-task-xyz"

    with patch(_MODULE) as mock_celery:
        mock_celery.send_task.return_value = mock_result
        call_command(
            "run_pipeline",
            folder=str(tmp_path),
            source_title="Sheikh Test",
        )

    actual = mock_celery.send_task.call_args
    task_name = actual.args[0]
    dispatched = actual.kwargs["kwargs"]

    assert task_name == "pipeline.ingest"
    assert dispatched["limit"] is None
    assert dispatched["surah"] is None


@pytest.mark.django_db
def test_run_pipeline_exits_with_error_on_missing_folder(tmp_path: Path) -> None:
    """A folder that does not exist raises CommandError before send_task is called."""
    missing = str(tmp_path / "does_not_exist")

    with patch(_MODULE) as mock_celery:
        with pytest.raises(CommandError, match="does not exist or is not a directory"):
            call_command("run_pipeline", folder=missing, source_title="x")
        mock_celery.send_task.assert_not_called()


@pytest.mark.django_db
def test_run_pipeline_exits_with_error_on_file_path(tmp_path: Path) -> None:
    """A path pointing to a file (not a directory) is rejected before dispatch."""
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello")

    with patch(_MODULE) as mock_celery:
        with pytest.raises(CommandError, match="does not exist or is not a directory"):
            call_command("run_pipeline", folder=str(file_path), source_title="x")
        mock_celery.send_task.assert_not_called()
