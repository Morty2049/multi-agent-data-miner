"""
Shared pytest fixtures — build an isolated vault/data tree for each test run
so we never touch the real obsidian_vault/ or data/ folders.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Don't write .pyc / __pycache__ next to source during tests. Chrome refuses
# to load unpacked extensions that contain a __pycache__ directory (filename
# starts with "_"), and chrome_plugin/ is both a Python package AND the
# extension root — so any pytest run that imports chrome_plugin.api_server
# would otherwise create chrome_plugin/__pycache__/ and brick the next
# `Load unpacked`.
sys.dont_write_bytecode = True

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """Build a throwaway vault + data tree and point config/api_server at it."""
    vault = tmp_path / "obsidian_vault"
    data = tmp_path / "data"
    (vault / "Vacancies").mkdir(parents=True)
    (vault / "Companies").mkdir(parents=True)
    data.mkdir(parents=True)

    # One sample vacancy so dashboard + parsed-ids have something to count
    (vault / "Vacancies" / "Sample_-_Python_Engineer_(111).md").write_text(
        "---\n"
        "date: 2026-04-18\n"
        "type: vacancy\n"
        'job_id: "111"\n'
        'company: "[[Sample]]"\n'
        "location: Lisbon\n"
        "employment: Full-time\n"
        "---\n"
        "# Python Engineer\n\n"
        "Work with Python and Kubernetes.\n"
    )
    (vault / "Companies" / "Sample.md").write_text(
        "---\ntype: \"[[Company]]\"\nname: Sample\n---\n## Overview\n_x_\n\n## Jobs\n\n"
    )

    import config
    from chrome_plugin import api_server as srv

    monkeypatch.setattr(config, "VAULT_DIR", vault)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", data / "rate_limit.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", data / "settings.json")
    monkeypatch.setattr(config, "EVENTS_FILE", data / "events.jsonl")

    monkeypatch.setattr(srv, "VAULT", vault)
    monkeypatch.setattr(srv, "DATA", data)
    monkeypatch.setattr(srv, "VACANCIES_DIR", vault / "Vacancies")
    monkeypatch.setattr(srv, "COMPANIES_DIR", vault / "Companies")
    srv._cache.clear()

    return vault, data


@pytest.fixture
def client(isolated_vault):
    from chrome_plugin import api_server as srv
    from fastapi.testclient import TestClient
    return TestClient(srv.app)
