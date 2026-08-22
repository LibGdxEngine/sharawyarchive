"""Refuse to boot production on the stub ASR engine.

``core.settings.base`` defaults ``ASR_BACKEND`` to ``stub`` so that tests and
a bare dev checkout need no models. The stub ASR
does not transcribe anything — it emits deterministic filler — so a production
deploy that inherits the default would fill the archive with invented sentences
presented as the Sheikh's words, which is precisely what ``CLAUDE.md`` rule 1
forbids. Silence is the dangerous failure here, so prod settings call
:func:`check_engines` at import time and the process refuses to start.

Kept out of the settings modules so it can be unit-tested against a plain
mapping instead of a real production environment.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

__all__ = ["ALLOW_VAR", "ENGINE_VARS", "STUB", "check_engines"]

STUB = "stub"
"""The value that means "no real model behind this backend"."""

ENGINE_VARS = ("ASR_BACKEND",)
"""Read by ``core.settings.base``; unset means ``stub``."""

ALLOW_VAR = "ALLOW_STUB_ENGINES"
"""Escape hatch for a staging box that deliberately runs without models.
``true`` (case-insensitive) is the only value that opens the gate."""


def check_engines(env: Mapping[str, str]) -> None:
    """Raise :class:`~django.core.exceptions.ImproperlyConfigured` when a real
    deployment would run on a stub engine.

    ``env`` is normally ``os.environ``. Passing the mapping in is what makes
    this testable without importing production settings.
    """
    if env.get(ALLOW_VAR, "").strip().lower() == "true":
        return
    stubbed = [name for name in ENGINE_VARS if (env.get(name) or STUB).strip() == STUB]
    if not stubbed:
        return
    raise ImproperlyConfigured(
        f"{' and '.join(stubbed)} would run on the {STUB!r} engine in production. "
        "The stub engines fabricate output, and indexing invented speech as the "
        "Sheikh's words is the one thing this archive must never do. Set "
        "ASR_BACKEND=cohere (or faster-whisper), "
        f"or set {ALLOW_VAR}=true if this deployment really is a "
        "model-free staging box."
    )
