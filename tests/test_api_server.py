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


# ── events / applications endpoints ───────────────────────────────

def test_post_event_appends_and_returns_normalised(client):
    r = client.post("/api/events", json={
        "job_id": "42", "kind": "interview", "note": "Round 2 · 14:00",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "42"
    assert body["kind"] == "interview"
    assert body["at"]  # auto-stamped


def test_post_event_rejects_unknown_kind(client):
    r = client.post("/api/events", json={"job_id": "42", "kind": "hired"})
    assert r.json().get("error") == "invalid_event"


def test_get_events_filter_by_job_id(client):
    client.post("/api/events", json={"job_id": "A", "kind": "saved"})
    client.post("/api/events", json={"job_id": "A", "kind": "applied"})
    client.post("/api/events", json={"job_id": "B", "kind": "saved"})
    r = client.get("/api/events?job_id=A")
    body = r.json()
    assert body["count"] == 2
    assert {e["kind"] for e in body["events"]} == {"saved", "applied"}


def test_get_events_filter_by_company(client):
    client.post("/api/events", json={"job_id": "1", "kind": "saved", "company": "Acme"})
    client.post("/api/events", json={"job_id": "2", "kind": "saved", "company": "Other"})
    r = client.get("/api/events?company=Acme")
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["job_id"] == "1"


def test_applications_groups_latest_status_per_job(client):
    client.post("/api/events", json={"job_id": "1", "kind": "saved"})
    client.post("/api/events", json={"job_id": "1", "kind": "applied"})
    client.post("/api/events", json={"job_id": "2", "kind": "saved"})
    client.post("/api/events", json={"job_id": "2", "kind": "rejected"})
    client.post("/api/events", json={"job_id": "3", "kind": "saved"})

    r = client.get("/api/applications")
    body = r.json()
    assert body["counts"]["saved"]    == 1
    assert body["counts"]["applied"]  == 1
    assert body["counts"]["rejected"] == 1
    assert body["counts"]["interview"] == 0
    assert body["total"] == 3
    statuses = {item["job_id"]: item["status"] for item in body["items"]}
    assert statuses == {"1": "applied", "2": "rejected", "3": "saved"}


def test_applications_ignores_notes_in_status(client):
    client.post("/api/events", json={"job_id": "1", "kind": "saved"})
    client.post("/api/events", json={"job_id": "1", "kind": "applied"})
    client.post("/api/events", json={"job_id": "1", "kind": "note", "note": "followed up"})
    r = client.get("/api/applications")
    statuses = {item["job_id"]: item["status"] for item in r.json()["items"]}
    assert statuses["1"] == "applied"  # note did not shift the status


def test_parse_auto_seeds_saved_event(client):
    client.post("/api/parse", json={
        "url": "https://linkedin.com/jobs/view/999",
        "job_id": "999",
        "title": "Solutions Engineer",
        "company": "Acme",
        "description_text": "We're hiring a solutions engineer with Python and Kubernetes experience.",
    })
    r = client.get("/api/events?job_id=999")
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["kind"] == "saved"
    assert body["events"][0]["company"] == "Acme"


def test_migrate_existing_seeds_missing_and_is_idempotent(client, isolated_vault):
    # The conftest vault already has one sample vacancy (job_id=111)
    r1 = client.post("/api/events/migrate-existing")
    b1 = r1.json()
    assert b1["seeded"] >= 1  # at least the fixture vacancy
    assert b1["errors"] == []

    # Re-running doesn't double-seed
    r2 = client.post("/api/events/migrate-existing")
    b2 = r2.json()
    assert b2["seeded"] == 0
    assert b2["skipped"] >= 1


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
