"""
End-to-end tests for chrome_plugin/api_server.py.

Each test uses an ISOLATED vault/data tree — real user data is never touched.
Run with:  venv/bin/pytest tests/ -v
"""
from __future__ import annotations


# ── basic wiring ──────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "vault" in body and "data" in body


def test_rate_initial_state(client):
    r = client.get("/api/rate")
    assert r.status_code == 200
    body = r.json()
    assert body["daily_cap"] == 600
    assert body["parsed_today"] == 0
    assert body["remaining"] == 600


# ── settings endpoints ────────────────────────────────────────────

def test_get_settings_returns_defaults_when_file_missing(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "regular"
    assert "delays_ms" in d and "click_min" in d["delays_ms"]


def test_put_settings_merges_and_persists(client):
    r = client.put("/api/settings", json={"daily_cap": 123})
    assert r.status_code == 200
    assert r.json()["daily_cap"] == 123
    # Reload via GET
    assert client.get("/api/settings").json()["daily_cap"] == 123


def test_put_settings_returns_error_on_invalid_cap(client):
    r = client.put("/api/settings", json={"daily_cap": 999999})
    assert r.json().get("error") == "invalid_settings"


def test_put_settings_null_cap_makes_parse_unlimited(client):
    client.put("/api/settings", json={"daily_cap": None})
    body = client.get("/api/rate").json()
    assert body["daily_cap"] >= 10**8  # unlimited sentinel


def test_apply_preset_endpoint_writes_preset(client):
    r = client.post("/api/settings/preset/fast")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "fast"
    assert d["daily_cap"] == 1500
    assert d["randomize_delays"] is False


def test_apply_preset_unknown_returns_error(client):
    r = client.post("/api/settings/preset/turbo")
    assert r.json().get("error") == "invalid_preset"


# ── dashboard ─────────────────────────────────────────────────────

def test_dashboard_minimal_fields(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    # Only the fields popup.js actually renders
    for key in ("total_vacancies", "total_companies", "parsed_today",
                "daily_cap", "remaining_today", "last_parsed_date", "data_age_days"):
        assert key in body


def test_dashboard_counts_fixture_vacancy(client):
    body = client.get("/api/dashboard").json()
    assert body["total_vacancies"] == 1
    assert body["total_companies"] == 1
    assert body["last_parsed_date"] == "2026-04-18"


# ── parsed-ids (drives the "already saved" badge) ─────────────────

def test_parsed_ids_returns_job_ids_from_vault(client):
    r = client.get("/api/parsed-ids")
    assert r.status_code == 200
    body = r.json()
    assert "111" in body["ids"]
    assert body["count"] == 1


def test_parsed_ids_updates_after_parse(client):
    before = client.get("/api/parsed-ids").json()
    assert "222" not in before["ids"]

    client.post("/api/parse", json=_payload(job_id="222"))

    after = client.get("/api/parsed-ids").json()
    assert "222" in after["ids"]
    assert after["count"] == before["count"] + 1


# ── parse endpoint ────────────────────────────────────────────────

def _payload(job_id="200100200", **overrides):
    base = {
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "job_id": job_id,
        "title": "Senior Engineer",
        "company": "ACME Corp",
        "company_url": "https://www.linkedin.com/company/acme/",
        "location": "Remote",
        "employment": "Full-time",
        "applies": "50 applicants",
        "reposted": "2 days ago",
        "description_html": "",
        "description_text": "We are hiring a Senior Engineer to work with Python.",
    }
    base.update(overrides)
    return base


def test_parse_creates_vacancy_and_company_files(client, isolated_vault):
    vault, _ = isolated_vault
    r = client.post("/api/parse", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "saved"
    assert body["parsed_today"] == 1
    assert body["remaining_today"] == 599

    vac_files = list((vault / "Vacancies").glob("ACME_Corp_-_*.md"))
    assert len(vac_files) == 1
    content = vac_files[0].read_text()
    assert 'job_id: "200100200"' in content
    assert 'company: "[[ACME Corp]]"' in content
    assert "Senior Engineer to work with Python" in content

    comp_file = vault / "Companies" / "ACME Corp.md"
    assert comp_file.exists()
    assert "(200100200)" in comp_file.read_text()


def test_parse_second_time_returns_exists(client):
    assert client.post("/api/parse", json=_payload()).json()["status"] == "saved"
    assert client.post("/api/parse", json=_payload()).json()["status"] == "exists"


def test_parse_without_job_id_errors(client):
    r = client.post("/api/parse", json=_payload(job_id=""))
    assert r.json()["error"] == "missing_job_id"


def test_parse_company_backlink_is_idempotent_across_jobs(client, isolated_vault):
    vault, _ = isolated_vault
    client.post("/api/parse", json=_payload(job_id="1001"))
    client.post("/api/parse", json=_payload(job_id="1002", title="Role Two"))
    comp = (vault / "Companies" / "ACME Corp.md").read_text()
    assert comp.count("(1001)") == 1
    assert comp.count("(1002)") == 1


def test_parse_respects_daily_cap(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "DAILY_PARSE_CAP", 1)

    assert client.post("/api/parse", json=_payload(job_id="500")).json()["status"] == "saved"
    assert client.post("/api/parse", json=_payload(job_id="501")).json()["error"] == "daily_cap"


def test_parse_uses_html_description_when_provided(client, isolated_vault):
    vault, _ = isolated_vault
    html = "<strong>Must have:</strong> <ul><li>Python</li><li>K8s</li></ul>"
    client.post("/api/parse", json=_payload(job_id="700", description_html=html))
    content = next((vault / "Vacancies").glob("*(700).md")).read_text()
    assert "**Must have:**" in content
    assert "- Python" in content


def test_parse_clears_cache_so_dashboard_sees_new_vacancy(client):
    before = client.get("/api/dashboard").json()["total_vacancies"]
    client.post("/api/parse", json=_payload(job_id="9001"))
    after = client.get("/api/dashboard").json()["total_vacancies"]
    assert after == before + 1
