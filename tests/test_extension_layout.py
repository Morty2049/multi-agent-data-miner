"""Regression tests for the Chrome-extension layout.

Chrome refuses to load any extension whose root contains files or
directories whose names start with `_` (per Chrome docs:
https://developer.chrome.com/docs/extensions/reference/api/extension —
"Filenames starting with '_' are reserved for use by the system.").

Aleksei has hit this 5+ times via stray `__pycache__/` dirs created by
ad-hoc `python -c "import chrome_plugin.api_server"` invocations or by
uvicorn running without PYTHONDONTWRITEBYTECODE. Each time the only
symptom is a Chrome dialog: "Cannot load extension with file or
directory name __pycache__."

These tests run in `pytest`, so a misconfigured local dev environment
fails fast in CI / on `pytest tests/`, before the user wastes another
reload cycle finding the broken state by hand.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Resolve repo root from this file's location, not from cwd, so the
# tests behave the same when run from any directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_DIR = REPO_ROOT / "chrome_plugin"


def _underscore_prefixed_paths(root: Path) -> list[Path]:
    """All files and directories under `root` whose name starts with `_`.

    Walks the entire tree (not just top-level) because Chrome's loader
    scans deep — a `chrome_plugin/icons/__pycache__/` would also fail
    to load.
    """
    hits: list[Path] = []
    for p in root.rglob("*"):
        # Skip the symlink target if root itself is a symlink — we want
        # the canonical layout the user actually ships.
        try:
            relative = p.relative_to(root)
        except ValueError:
            continue
        if any(part.startswith("_") for part in relative.parts):
            hits.append(relative)
    return hits


def test_extension_dir_exists():
    assert EXTENSION_DIR.is_dir(), (
        f"chrome_plugin/ not found at {EXTENSION_DIR}. "
        "If the repo layout changed, update REPO_ROOT in this test."
    )


def test_no_underscore_prefixed_files_or_dirs():
    """Chrome rejects any file or directory whose name starts with `_`.

    The most common offender is `__pycache__/`, created when Python
    imports chrome_plugin.api_server without PYTHONDONTWRITEBYTECODE.
    Use scripts/run-server.sh, which sets that env var before uvicorn.
    """
    offenders = _underscore_prefixed_paths(EXTENSION_DIR)
    assert offenders == [], (
        "Chrome will refuse to load chrome_plugin/ because these "
        "underscore-prefixed paths exist:\n  "
        + "\n  ".join(str(p) for p in offenders)
        + "\n\nFix: rm -rf the offenders, then run the API server via "
        "scripts/run-server.sh (sets PYTHONDONTWRITEBYTECODE=1)."
    )


def test_manifest_json_present_and_parseable():
    """Sanity: the extension's entry point must exist + be valid JSON."""
    import json

    manifest = EXTENSION_DIR / "manifest.json"
    assert manifest.is_file(), f"missing {manifest}"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("manifest_version") == 3, (
        f"expected manifest_version: 3, got {data.get('manifest_version')!r}"
    )
    assert data.get("name"), "manifest.json missing 'name'"
    assert data.get("version"), "manifest.json missing 'version'"


def test_run_server_script_exists_and_executable():
    """The launcher script is the documented way to start the server.

    If the wrapper is removed, future devs revert to `uvicorn ...` bare
    and lose the PYTHONDONTWRITEBYTECODE guard. Lock it in.
    """
    script = REPO_ROOT / "scripts" / "run-server.sh"
    assert script.is_file(), f"missing {script}"
    import os
    import stat

    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR, f"{script} is not executable (chmod +x)"
    body = script.read_text(encoding="utf-8")
    assert "PYTHONDONTWRITEBYTECODE" in body, (
        "scripts/run-server.sh must export PYTHONDONTWRITEBYTECODE — "
        "that's the whole reason it exists."
    )
