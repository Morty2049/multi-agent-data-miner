"""
End-to-end tests for chrome_plugin/api_server.py.

Each test uses an ISOLATED vault/data tree — real user data is never touched.
Run with:  venv/bin/pytest tests/ -v
"""
from __future__ import annotations

import json


# ── health / basic wiring ─────────────────────────────────────────

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


# ── dashboard ─────────────────────────────────────────────────────

def test_dashboard_has_freshness_fields(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    # Required new fields from the UX fix round
    assert "last_parsed_date" in body
    assert "data_age_days" in body
    # Core counts present
    assert body["total_vacancies"] >= 1
    assert body["total_skills"] >= 2


def test_dashboard_freshness_matches_fixture_vacancy(client):
    body = client.get("/api/dashboard").json()
    assert body["last_parsed_date"] == "2026-04-18"


# ── skills browser ─────────────────────────────────────────────────

def test_skills_search_returns_match(client):
    r = client.get("/api/skills", params={"q": "Python"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "Python" in names


def test_skills_search_empty_query_returns_all(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_skill_detail(client):
    r = client.get("/api/skills/Kubernetes")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Kubernetes"
    assert body["about"] == "Container orchestration"
    assert "Containers" in body["parents"]


def test_skill_detail_case_insensitive(client):
    r = client.get("/api/skills/kubernetes")
    assert r.status_code == 200
    assert r.json()["name"] == "Kubernetes"


# ── autocomplete (new for multi-select matcher) ────────────────────

def test_autocomplete_finds_prefix(client):
    r = client.get("/api/skills/autocomplete", params={"q": "kube"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "Kubernetes" in names


def test_autocomplete_empty_on_short_or_blank_query(client):
    # FastAPI's min_length=1 means blank triggers a 422
    r = client.get("/api/skills/autocomplete", params={"q": ""})
    assert r.status_code == 422


# ── skill detect ───────────────────────────────────────────────────

def test_detect_finds_tracked_skills_in_text(client):
    r = client.get("/api/detect", params={
        "text": "We work with Python and Kubernetes in production."
    })
    assert r.status_code == 200
    body = r.json()
    names = [d["name"] for d in body["detected"]]
    assert "Python" in names
    assert "Kubernetes" in names


def test_detect_uses_synonym_dict(client):
    # K8s → Kubernetes via skill_synonyms.json
    r = client.get("/api/detect", params={"text": "We run K8s in production"})
    body = r.json()
    assert any(d["name"] == "Kubernetes" for d in body["detected"])


# ── parse endpoint (Chrome save to vault) ──────────────────────────

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
    # Frontmatter shape
    assert "---\ndate: " in content
    assert 'job_id: "200100200"' in content
    assert 'company: "[[ACME Corp]]"' in content
    assert "location: Remote" in content
    # Description body present
    assert "Senior Engineer to work with Python" in content

    # api_server mirrors parse_job.py: spaces preserved in Company filename,
    # replaced in Vacancy filename. This is intentional for backward compat
    # with existing CLI-created vaults.
    comp_file = vault / "Companies" / "ACME Corp.md"
    assert comp_file.exists()
    comp_content = comp_file.read_text()
    # Vacancy wikilink was appended to ## Jobs
    assert "## Jobs" in comp_content
    assert "(200100200)" in comp_content


def test_parse_second_time_returns_exists(client):
    r1 = client.post("/api/parse", json=_payload())
    assert r1.json()["status"] == "saved"
    r2 = client.post("/api/parse", json=_payload())
    assert r2.json()["status"] == "exists"


def test_parse_without_job_id_errors(client):
    r = client.post("/api/parse", json=_payload(job_id=""))
    assert r.status_code == 200
    assert r.json()["error"] == "missing_job_id"


def test_parse_company_backlink_is_idempotent_across_jobs(client, isolated_vault):
    vault, _ = isolated_vault
    client.post("/api/parse", json=_payload(job_id="1001"))
    client.post("/api/parse", json=_payload(job_id="1002", title="Role Two"))
    comp = (vault / "Companies" / "ACME Corp.md").read_text()
    assert comp.count("(1001)") == 1
    assert comp.count("(1002)") == 1


def test_parse_respects_daily_cap(client, monkeypatch):
    # Drop the cap to 1 for this test only
    import config
    monkeypatch.setattr(config, "DAILY_PARSE_CAP", 1)

    r1 = client.post("/api/parse", json=_payload(job_id="500"))
    assert r1.json()["status"] == "saved"

    r2 = client.post("/api/parse", json=_payload(job_id="501"))
    assert r2.json()["error"] == "daily_cap"


def test_parse_uses_html_description_when_provided(client, isolated_vault):
    vault, _ = isolated_vault
    html = "<strong>Must have:</strong> <ul><li>Python</li><li>K8s</li></ul>"
    client.post("/api/parse", json=_payload(job_id="700", description_html=html))
    content = next((vault / "Vacancies").glob("*(700).md")).read_text()
    # html_to_markdown converts strong + list
    assert "**Must have:**" in content
    assert "- Python" in content


def test_parse_clears_cache_so_dashboard_sees_new_vacancy(client):
    # before
    r1 = client.get("/api/dashboard").json()
    before = r1["total_vacancies"]

    client.post("/api/parse", json=_payload(job_id="9001"))

    # after
    r2 = client.get("/api/dashboard").json()
    assert r2["total_vacancies"] == before + 1


# ── matcher / gaps ─────────────────────────────────────────────────

def test_match_returns_sample_vacancy_on_python(client):
    r = client.get("/api/jobs/match", params={"skills": "Python"})
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) >= 1
    j = jobs[0]
    assert j["match_score"] > 0
    assert "Python" in [s.lower().capitalize() for s in j["matched_skills"]] or \
           "python" in j["matched_skills"]


def test_gaps_reports_missing_skills(client):
    # Sample vacancy requires Python + Kubernetes. User has only Python.
    r = client.get("/api/gaps", params={"skills": "Python"})
    assert r.status_code == 200
    names = [g["name"].lower() for g in r.json()]
    assert "kubernetes" in names


# ── companies ──────────────────────────────────────────────────────

def test_companies_listed(client):
    r = client.get("/api/companies")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "Sample" in names


# ── cache invalidation ─────────────────────────────────────────────

def test_cache_clear_endpoint(client):
    r = client.post("/api/cache/clear")
    assert r.status_code == 200
    assert r.json()["status"] == "cache cleared"
