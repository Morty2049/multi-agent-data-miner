"""
Shared pytest fixtures — build an isolated vault/data tree for each test run
so we never touch the real obsidian_vault/ or data/ folders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """Build a throwaway vault + data tree and point config/api_server at it.

    Returns (vault_dir, data_dir) — both pathlib.Path.
    """
    vault = tmp_path / "obsidian_vault"
    data = tmp_path / "data"
    (vault / "Vacancies").mkdir(parents=True)
    (vault / "Companies").mkdir(parents=True)
    (vault / "Skills").mkdir(parents=True)
    data.mkdir(parents=True)

    (data / "skills_graph.json").write_text(json.dumps({
        "skills": {
            "Python": {
                "about": "Python programming language",
                "parent": ["Programming languages"],
                "children": ["Django", "FastAPI"],
                "mentions": [],
            },
            "Kubernetes": {
                "about": "Container orchestration",
                "parent": ["Containers"],
                "children": [],
                "mentions": [],
            },
        }
    }))
    (data / "skill_synonyms.json").write_text(json.dumps({"K8s": "Kubernetes"}))

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
        "Work with [[Python]] and [[Kubernetes]].\n"
    )
    (vault / "Skills" / "Python.md").write_text("# Python\n")
    (vault / "Skills" / "Kubernetes.md").write_text("# Kubernetes\n")
    (vault / "Companies" / "Sample.md").write_text(
        "---\ntype: \"[[Company]]\"\nname: Sample\n---\n## Overview\n_x_\n\n## Jobs\n\n"
    )

    # Import both modules (already imported in previous tests is fine — we
    # just re-bind their path attributes). DO NOT pop from sys.modules —
    # that decouples api_server.config from our test's config.
    import config
    from chrome_plugin import api_server as srv

    monkeypatch.setattr(config, "VAULT_DIR", vault)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", data / "rate_limit.json")

    monkeypatch.setattr(srv, "VAULT", vault)
    monkeypatch.setattr(srv, "DATA", data)
    monkeypatch.setattr(srv, "VACANCIES_DIR", vault / "Vacancies")
    monkeypatch.setattr(srv, "COMPANIES_DIR", vault / "Companies")
    monkeypatch.setattr(srv, "SKILLS_DIR", vault / "Skills")
    monkeypatch.setattr(srv, "GRAPH_PATH", data / "skills_graph.json")
    monkeypatch.setattr(srv, "SYNONYMS_PATH", data / "skill_synonyms.json")
    srv._cache.clear()

    return vault, data


@pytest.fixture
def client(isolated_vault):
    """Return a TestClient bound to api_server with the isolated vault."""
    from chrome_plugin import api_server as srv
    from fastapi.testclient import TestClient
    return TestClient(srv.app)
