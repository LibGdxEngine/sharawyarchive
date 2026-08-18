"""Regression: dev settings module must import cleanly."""

from __future__ import annotations


def test_dev_settings_import() -> None:
    """Importing core.settings.dev should never raise."""
    import importlib

    # Force a clean import in case it was already loaded.
    import sys

    for key in list(sys.modules):
        if "core.settings" in key:
            del sys.modules[key]

    mod = importlib.import_module("core.settings.dev")
    assert mod.DEBUG is True
