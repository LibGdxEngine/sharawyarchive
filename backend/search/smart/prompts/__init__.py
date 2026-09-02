"""Versioned prompt files.

Each stage reads ``<name>.<PROMPT_VERSION>.md`` from this directory. Bumping
:data:`PROMPT_VERSION` is how a prompt change invalidates the response cache
(the version is part of every cache key) and how eval reports stay comparable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

__all__ = ["PROMPT_VERSION", "load"]

PROMPT_VERSION = "v1"

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=8)
def load(name: str) -> str:
    """The prompt text for ``name`` (``planner``, ``reranker``, ``generator``, ``judge``)."""
    path = _DIR / f"{name}.{PROMPT_VERSION}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt {name!r} has no {PROMPT_VERSION} file at {path}")
    return path.read_text(encoding="utf-8").strip()
