"""
Minimal API server for the Chrome plugin.

Purpose: be the local "Saved" vault behind LinkedIn's UI.

Endpoints:
  GET  /api/health       — ping
  GET  /api/dashboard    — total vacancies/companies, parsed today, freshness
  GET  /api/rate         — daily cap counter
  GET  /api/parsed-ids   — set of job_ids already in the vault (for the
                           "already saved" badge on list pages)
  POST /api/parse        — save a single vacancy (from content script)

Run from project root:
    venv/bin/uvicorn chrome_plugin.api_server:app --reload --port 8000
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure project root is on sys.path so `import config` works
# regardless of where uvicorn was started.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config  # noqa: E402

VAULT = config.VAULT_DIR
DATA = config.DATA_DIR

VACANCIES_DIR = VAULT / "Vacancies"
COMPANIES_DIR = VAULT / "Companies"

app = FastAPI(title="Tally API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ──────────────────────────────────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.+?)\n---", re.DOTALL)
_JOB_ID_RE = re.compile(r"\((\d+)\)\.md$")


def _parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _safe_filename(text: str) -> str:
    return re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE).strip()


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _yaml_str(value: str) -> str:
    """Serialise an arbitrary string as a double-quoted YAML scalar.
    JSON strings are a strict subset of YAML double-quoted scalars, so
    json.dumps gives us proper escaping (\\", \\\\, \\n, \\uXXXX, and
    — critically for company names like "JTA: The Data Scientists" —
    keeps the embedded colon from being parsed as a YAML key separator.
    """
    return json.dumps(value or "", ensure_ascii=False)


def _html_to_markdown(html: str) -> str:
    if not html:
        return ""
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n## \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1", text, flags=re.DOTALL)
    text = re.sub(r"</?[ou]l[^>]*>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<p[^>]*>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"')
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── cached loaders ───────────────────────────────────────────────────

_cache: dict = {}


def _scan_vacancies() -> list[dict]:
    """Lightweight scan — just job_id + date. Used by dashboard and
    parsed-ids. Cached; cleared on every POST /api/parse."""
    if "vacancies" in _cache:
        return _cache["vacancies"]
    result = []
    if VACANCIES_DIR.exists():
        for p in VACANCIES_DIR.glob("*.md"):
            fm_match = _FM_RE.match(p.read_text(encoding="utf-8", errors="replace"))
            fm = _parse_frontmatter(fm_match.group(0)) if fm_match else {}
            # Prefer frontmatter job_id, fallback to filename (123456789).md
            job_id = str(fm.get("job_id", "")).strip('"') or ""
            if not job_id:
                m = _JOB_ID_RE.search(p.name)
                if m:
                    job_id = m.group(1)
            # Company is stored as "[[Name]]" wiki-link in frontmatter;
            # strip the brackets so event-log / Applications panel can
            # use it as a plain key.
            raw_company = str(fm.get("company", "")).strip()
            company = raw_company.strip("[]").strip('"').strip() or ""
            # Title isn't in the frontmatter — recover it from the filename
            # stem "<Company>_-_<Title>_(<job_id>)" so Company History can
            # show a readable "Senior Product Designer" next to each row.
            title_match = re.match(r"^(.+?)_-_(.+?)_\(\d+\)$", p.stem)
            title = title_match.group(2).replace("_", " ").strip() if title_match else ""
            result.append({
                "file": p.stem,
                "job_id": job_id,
                "date": str(fm.get("date", "")),
                "company": company,
                "title": title,
            })
    _cache["vacancies"] = result
    return result


def _count_companies() -> int:
    if not COMPANIES_DIR.exists():
        return 0
    return sum(1 for _ in COMPANIES_DIR.glob("*.md"))


# ── endpoints ────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "vault": str(VAULT), "data": str(DATA)}


@app.get("/api/rate")
def rate_status():
    return {
        "parsed_today": config.parsed_today(),
        "daily_cap": config.effective_cap(),
        "remaining": config.remaining_today(),
    }


@app.get("/api/dashboard")
def dashboard():
    vacancies = _scan_vacancies()
    dates = [v["date"] for v in vacancies if v["date"]]
    last_parsed = max(dates) if dates else ""
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(last_parsed)).days
    except (ValueError, TypeError):
        age = -1
    return {
        "total_vacancies": len(vacancies),
        "total_companies": _count_companies(),
        "parsed_today": config.parsed_today(),
        "daily_cap": config.effective_cap(),
        "remaining_today": config.remaining_today(),
        "last_parsed_date": last_parsed,
        "data_age_days": age,
    }


@app.get("/api/settings")
def get_settings():
    return config.load_settings()


@app.put("/api/settings")
def update_settings(payload: dict):
    """Merge-patch user settings. Accepts any subset of the settings
    schema. Returns the full merged state after write, or a 400-like
    JSON error (no HTTPException to stay consistent with the rest of
    the error surface which returns {"error": ..., "message": ...})."""
    try:
        return config.save_settings(payload)
    except ValueError as e:
        return {"error": "invalid_settings", "message": str(e)}


@app.post("/api/settings/preset/{name}")
def apply_settings_preset(name: str):
    try:
        return config.apply_preset(name)
    except ValueError as e:
        return {"error": "invalid_preset", "message": str(e)}


@app.get("/api/parsed-ids")
def parsed_ids():
    """Set of job_ids already saved to the vault. Content script calls this
    to put a green badge on list cards and let autopilot skip them."""
    ids = [v["job_id"] for v in _scan_vacancies() if v["job_id"]]
    return {"ids": ids, "count": len(ids)}


# ── /api/parse (content-script → vault) ──────────────────────────────


class ParseRequest(BaseModel):
    url: str
    job_id: str
    title: str
    company: str
    company_url: str = ""
    location: str = ""
    employment: str = "Full-time"
    applies: str = ""
    reposted: str = ""
    description_html: str = ""
    description_text: str = ""


@app.post("/api/parse")
def parse_from_browser(req: ParseRequest):
    if not config.can_parse_more():
        return {
            "error": "daily_cap",
            "message": f"Daily cap reached ({config.effective_cap()})",
        }

    job_id = req.job_id
    if not job_id:
        return {"error": "missing_job_id"}

    if req.description_html:
        description = _html_to_markdown(req.description_html)
    elif req.description_text:
        description = _sanitize_text(req.description_text)
    else:
        description = "_No description extracted_"

    today = datetime.date.today().isoformat()
    company = _sanitize_text(req.company) or "Unknown Company"
    title = _sanitize_text(req.title) or "Unknown Role"

    VACANCIES_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = _safe_filename(company)[:40]
    safe_title = _safe_filename(title)[:60]
    vac_filename = f"{safe_company}_-_{safe_title}_({job_id}).md".replace(" ", "_")
    vac_path = VACANCIES_DIR / vac_filename

    if vac_path.exists():
        return {"status": "exists", "job_id": job_id, "file": vac_filename}

    # Every free-text value goes through _yaml_str so a colon, a stray
    # quote, or a unicode edge case in the company / location / applies
    # string can't break the frontmatter. company is wrapped in [[...]]
    # INSIDE the quoted scalar so Obsidian still treats it as a wikilink.
    wiki_company = _yaml_str(f"[[{company}]]")
    vacancy_md = f"""---
date: {today}
type: vacancy
source: chrome_extension
job_id: "{job_id}"
company: {wiki_company}
location: {_yaml_str(req.location)}
reposted: {_yaml_str(req.reposted)}
applies: {_yaml_str(req.applies)}
employment: {_yaml_str(req.employment)}
job_url: {_yaml_str(req.url)}
apply_url: "Easy Apply (LinkedIn)"
company_url: {_yaml_str(req.company_url)}
tags:
  - vacancy
  - chrome_parsed
---
# {title}

**Company:** [[{company}]]
**Location:** {req.location}
**Employment:** {req.employment}

## Job Description

{description}
"""
    vac_path.write_text(vacancy_md, encoding="utf-8")

    # Company file
    COMPANIES_DIR.mkdir(parents=True, exist_ok=True)
    comp_filename = f"{safe_company}.md"
    comp_path = COMPANIES_DIR / comp_filename

    if not comp_path.exists():
        company_md = f"""---
type: "[[Company]]"
name: {_yaml_str(company)}
industry: Unknown
headquarters: Unknown
link: {_yaml_str(req.company_url)}
website: Unknown
company_size: Unknown
---
## Overview

_Parsed via Chrome extension._

## Jobs

"""
        comp_path.write_text(company_md, encoding="utf-8")

    vac_stem = vac_path.stem
    comp_text = comp_path.read_text(encoding="utf-8")
    if f"({job_id})" not in comp_text:
        link_line = f"- [[{vac_stem}]] — {title} | {req.location}\n"
        if "## Jobs" in comp_text:
            comp_text = comp_text.rstrip() + "\n" + link_line
        else:
            comp_text = comp_text.rstrip() + "\n\n## Jobs\n\n" + link_line
        comp_path.write_text(comp_text, encoding="utf-8")

    config.register_parse()
    # Seed the application timeline with the initial "saved" event.
    # Subsequent transitions (applied, screening, …) land here too via
    # /api/events. Latest non-note event's kind is the vacancy's status.
    try:
        config.append_event({
            "job_id": job_id,
            "kind":   "saved",
            "note":   "Saved via Chrome extension",
            "company": company,
        })
    except ValueError:
        pass  # never block a save on a bad event payload
    _cache.clear()  # dashboard + parsed-ids must see the new file

    return {
        "status": "saved",
        "job_id": job_id,
        "file": vac_filename,
        "parsed_today": config.parsed_today(),
        "remaining_today": config.remaining_today(),
    }


# ── /api/events (application timeline + status transitions) ──────────


class EventRequest(BaseModel):
    job_id: str
    kind: str
    note: str | None = None
    at: str | None = None
    company: str | None = None


@app.post("/api/events")
def append_event(event: EventRequest):
    """Append one timeline event. 400-style error-dict on validation fail."""
    try:
        return config.append_event(event.model_dump(exclude_none=True))
    except ValueError as e:
        return {"error": "invalid_event", "message": str(e)}


def _event_matches(event: dict, job_id: str | None, company: str | None) -> bool:
    if job_id is not None and event.get("job_id") != job_id:
        return False
    if company is not None and event.get("company") != company:
        return False
    return True


@app.get("/api/events")
def list_events(job_id: str | None = None, company: str | None = None):
    """Events filtered by job_id and/or company. No filter returns all.
    `company` matches the stamped-at-save-time company name (case sensitive).
    """
    all_events = config.load_events()
    filtered = [e for e in all_events if _event_matches(e, job_id, company)]
    return {"events": filtered, "count": len(filtered)}


@app.get("/api/applications")
def list_applications():
    """Latest status per job_id plus per-status counts, for the
    Applications panel. Does not look inside vault files — relies solely
    on what's in events.jsonl, so a vacancy missing a "saved" event
    will simply not appear here. In practice every vacancy saved via
    /api/parse gets its "saved" event auto-stamped; the bulk-migration
    endpoint covers the pre-events backlog."""
    all_events = config.load_events()
    # Latest status per job_id, plus all events per job_id for metadata
    latest_by_job: dict[str, dict] = {}
    all_by_job: dict[str, list[dict]] = {}
    for ev in all_events:
        jid = ev.get("job_id")
        if not jid:
            continue
        all_by_job.setdefault(jid, []).append(ev)
        if ev.get("kind") in config.STATUS_KINDS:
            latest_by_job[jid] = ev

    counts: dict[str, int] = {k: 0 for k in config.STATUS_KINDS}
    items: list[dict] = []
    for jid, latest in latest_by_job.items():
        kind = latest["kind"]
        counts[kind] += 1
        # Company/title from the earliest saved event if present
        company = None
        for e in all_by_job.get(jid, []):
            if e.get("company"):
                company = e["company"]
                break
        items.append({
            "job_id":     jid,
            "status":     kind,
            "last_at":    latest.get("at"),
            "last_note":  latest.get("note"),
            "company":    company,
            "event_count": len(all_by_job.get(jid, [])),
        })
    # Stable ordering: most recently touched first
    items.sort(key=lambda it: it.get("last_at") or "", reverse=True)
    return {"counts": counts, "items": items, "total": len(items)}


@app.get("/api/company-history")
def company_history(company: str):
    """Aggregated per-vacancy summary of every touch at this company:
    one row per job_id with its latest status, timestamp, and title.
    Drives the sidebar's Company History section on /company/<slug>.
    Company name is matched exactly against the `company` field
    stamped onto events (either at save time or during migration)."""
    if not company:
        return {"company": "", "counts": {}, "items": [], "total": 0}
    events = config.load_events()
    relevant = [e for e in events if e.get("company") == company]
    by_job: dict[str, list[dict]] = {}
    for e in relevant:
        jid = e.get("job_id")
        if jid:
            by_job.setdefault(jid, []).append(e)

    # Title lookup from vault. One scan, not per-job, to stay cheap.
    title_by_job = {
        v["job_id"]: v.get("title") or v.get("file") or v["job_id"]
        for v in _scan_vacancies()
        if v.get("job_id")
    }

    items = []
    for jid, evs in by_job.items():
        latest = None
        for ev in evs:
            if ev.get("kind") not in config.STATUS_KINDS:
                continue
            if latest is None or (ev.get("at") or "") > (latest.get("at") or ""):
                latest = ev
        if latest is None:
            # Only "note" events so far — fall back to the first event as anchor
            latest = evs[0]
        items.append({
            "job_id":      jid,
            "title":       title_by_job.get(jid, ""),
            "status":      latest.get("kind") if latest.get("kind") in config.STATUS_KINDS else "saved",
            "last_at":     latest.get("at"),
            "event_count": len(evs),
        })
    items.sort(key=lambda it: it.get("last_at") or "", reverse=True)
    counts: dict[str, int] = {k: 0 for k in config.STATUS_KINDS}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {"company": company, "counts": counts, "items": items, "total": len(items)}


@app.post("/api/events/migrate-existing")
def migrate_existing_vacancies():
    """One-shot: seed a "saved" event for every vacancy file in the vault
    that doesn't already have any event. Idempotent — safe to re-run.
    Uses the vacancy's `date` frontmatter field as the timestamp, falling
    back to the file's mtime. Intended for the first Phase-A rollout
    where 500+ pre-existing vacancies were saved before the event log
    existed."""
    existing_job_ids = {e.get("job_id") for e in config.load_events()}
    seeded = 0
    skipped = 0
    errors: list[str] = []
    for vac in _scan_vacancies():
        jid = vac.get("job_id")
        if not jid or jid in existing_job_ids:
            skipped += 1
            continue
        date_str = vac.get("date") or ""
        # Frontmatter date is YYYY-MM-DD; pin the time at noon UTC for
        # a reasonable sort key. Fall back to file mtime if date is bad.
        at_iso = None
        if date_str:
            try:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=12, tzinfo=datetime.timezone.utc
                )
                at_iso = dt.isoformat()
            except ValueError:
                pass
        if at_iso is None:
            vac_path = VACANCIES_DIR / ((vac.get("file") or "") + ".md")
            if vac_path.exists():
                at_iso = datetime.datetime.fromtimestamp(
                    vac_path.stat().st_mtime, tz=datetime.timezone.utc
                ).isoformat()
            else:
                at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        company = vac.get("company") or None
        try:
            config.append_event({
                "job_id": jid,
                "kind":   "saved",
                "at":     at_iso,
                "note":   "Backfilled from vault on migration",
                **({"company": company} if company else {}),
            })
            seeded += 1
            existing_job_ids.add(jid)
        except ValueError as e:
            errors.append(f"{jid}: {e}")
    return {"seeded": seeded, "skipped": skipped, "errors": errors}
