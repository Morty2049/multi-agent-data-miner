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

app = FastAPI(title="Job Miner API", version="2.0.0")
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
            result.append({
                "file": p.stem,
                "job_id": job_id,
                "date": str(fm.get("date", "")),
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
        "daily_cap": config.DAILY_PARSE_CAP,
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
        "daily_cap": config.DAILY_PARSE_CAP,
        "remaining_today": config.remaining_today(),
        "last_parsed_date": last_parsed,
        "data_age_days": age,
    }


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
            "message": f"Daily cap reached ({config.DAILY_PARSE_CAP})",
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

    vacancy_md = f"""---
date: {today}
type: vacancy
source: chrome_extension
job_id: "{job_id}"
company: "[[{company}]]"
location: {req.location}
reposted: {req.reposted}
applies: {req.applies}
employment: {req.employment}
job_url: {req.url}
apply_url: Easy Apply (LinkedIn)
company_url: {req.company_url}
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
name: {company}
industry: Unknown
headquarters: Unknown
link: {req.company_url}
website: Unknown
Company size: Unknown
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
    _cache.clear()  # dashboard + parsed-ids must see the new file

    return {
        "status": "saved",
        "job_id": job_id,
        "file": vac_filename,
        "parsed_today": config.parsed_today(),
        "remaining_today": config.remaining_today(),
    }
