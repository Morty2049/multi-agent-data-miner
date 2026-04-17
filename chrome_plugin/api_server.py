"""
Local API server — reads the Obsidian vault and serves data to the
Chrome extension popup and content script.

Run from project root:
    venv/bin/uvicorn chrome_plugin.api_server:app --reload --port 8000

Or from inside chrome_plugin/:
    ../venv/bin/uvicorn api_server:app --reload --port 8000
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

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
SKILLS_DIR = VAULT / "Skills"
GRAPH_PATH = DATA / "skills_graph.json"
SYNONYMS_PATH = DATA / "skill_synonyms.json"

app = FastAPI(title="Job Miner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ──────────────────────────────────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.+?)\n---", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


def _parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _read_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    body = _FM_RE.sub("", text).strip()
    return fm, body


def _extract_wikilinks(text: str) -> list[str]:
    return _WIKILINK.findall(text)


# ── cached data loaders ─────────────────────────────────────────────

_cache: dict = {}


def _load_graph() -> dict:
    if "graph" not in _cache:
        _cache["graph"] = json.loads(GRAPH_PATH.read_text())["skills"]
    return _cache["graph"]


def _load_synonyms() -> dict:
    if "synonyms" not in _cache:
        _cache["synonyms"] = json.loads(SYNONYMS_PATH.read_text())
    return _cache["synonyms"]


def _load_vacancies() -> list[dict]:
    if "vacancies" in _cache:
        return _cache["vacancies"]
    result = []
    for p in sorted(VACANCIES_DIR.glob("*.md")):
        fm, body = _read_md(p)
        skills = [
            s for s in _extract_wikilinks(body)
            if (SKILLS_DIR / f"{s}.md").exists()
        ]
        company_raw = fm.get("company", "")
        company = _WIKILINK.findall(company_raw)[0] if _WIKILINK.search(str(company_raw)) else str(company_raw)
        result.append({
            "file": p.stem,
            "title": _WIKILINK.sub(r"\1", body.split("\n")[0].lstrip("# ").strip()) if body else p.stem,
            "company": company,
            "location": fm.get("location", ""),
            "employment": fm.get("employment", ""),
            "date": str(fm.get("date", "")),
            "job_id": fm.get("job_id", ""),
            "job_url": fm.get("job_url", ""),
            "applies": fm.get("applies", ""),
            "skills": skills,
        })
    _cache["vacancies"] = result
    return result


def _load_companies() -> list[dict]:
    if "companies" in _cache:
        return _cache["companies"]
    result = []
    for p in sorted(COMPANIES_DIR.glob("*.md")):
        fm, body = _read_md(p)
        jobs_section = body.split("## Jobs")[-1] if "## Jobs" in body else ""
        job_links = _extract_wikilinks(jobs_section)
        result.append({
            "name": fm.get("name", p.stem),
            "industry": fm.get("industry", ""),
            "headquarters": fm.get("headquarters", ""),
            "website": fm.get("website", ""),
            "size": fm.get("Company size", fm.get("company_size", "")),
            "jobs_count": len(job_links),
        })
    _cache["companies"] = result
    return result


# ── endpoints ────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard():
    graph = _load_graph()
    vacancies = _load_vacancies()
    companies = _load_companies()

    skill_counts = Counter()
    for v in vacancies:
        for s in v["skills"]:
            skill_counts[s] += 1

    top_skills = skill_counts.most_common(25)

    location_counts = Counter()
    for v in vacancies:
        loc = v["location"]
        if loc:
            location_counts[loc] += 1
    top_locations = location_counts.most_common(10)

    employment_counts = Counter()
    for v in vacancies:
        emp = v["employment"]
        if emp:
            employment_counts[emp] += 1

    return {
        "total_vacancies": len(vacancies),
        "total_companies": len(companies),
        "total_skills": len(graph),
        "top_skills": [{"name": n, "count": c} for n, c in top_skills],
        "top_locations": [{"name": n, "count": c} for n, c in top_locations],
        "employment_types": dict(employment_counts),
    }


@app.get("/api/skills")
def list_skills(q: str = Query("", description="search query")):
    graph = _load_graph()
    results = []
    q_lower = q.lower()
    for name, data in graph.items():
        if q_lower and q_lower not in name.lower():
            continue
        results.append({
            "name": name,
            "about": data.get("about", ""),
            "parents": data.get("parent", []),
            "children": data.get("children", []),
            "mentions_count": len(data.get("mentions", [])),
        })
    results.sort(key=lambda x: x["mentions_count"], reverse=True)
    return results[:100]


@app.get("/api/skills/{name}")
def get_skill(name: str):
    graph = _load_graph()
    data = graph.get(name)
    if not data:
        for k, v in graph.items():
            if k.lower() == name.lower():
                data = v
                name = k
                break
    if not data:
        return {"error": "skill not found"}
    return {
        "name": name,
        "about": data.get("about", ""),
        "parents": data.get("parent", []),
        "children": data.get("children", []),
        "mentions": data.get("mentions", []),
    }


@app.get("/api/companies")
def list_companies(q: str = Query("", description="search query")):
    companies = _load_companies()
    q_lower = q.lower()
    results = [c for c in companies if q_lower in c["name"].lower()] if q_lower else companies
    results.sort(key=lambda x: x["jobs_count"], reverse=True)
    return results[:100]


@app.get("/api/jobs/match")
def match_jobs(skills: str = Query(..., description="comma-separated skill list")):
    user_skills_raw = [s.strip() for s in skills.split(",") if s.strip()]
    synonyms = _load_synonyms()
    user_skills = set()
    for s in user_skills_raw:
        canonical = synonyms.get(s, s)
        user_skills.add(canonical.lower())
        user_skills.add(s.lower())

    vacancies = _load_vacancies()
    scored = []
    for v in vacancies:
        job_skills_lower = {s.lower() for s in v["skills"]}
        overlap = user_skills & job_skills_lower
        if not overlap:
            continue
        total = len(job_skills_lower) or 1
        score = len(overlap) / total
        missing = job_skills_lower - user_skills
        scored.append({
            **v,
            "match_score": round(score, 3),
            "matched_skills": sorted(overlap),
            "missing_skills": sorted(missing),
        })
    scored.sort(key=lambda x: (-x["match_score"], -len(x["matched_skills"])))
    return scored[:50]


@app.get("/api/gaps")
def skill_gaps(skills: str = Query(..., description="comma-separated user skills")):
    user_skills_raw = [s.strip() for s in skills.split(",") if s.strip()]
    synonyms = _load_synonyms()
    user_skills = set()
    for s in user_skills_raw:
        user_skills.add(synonyms.get(s, s).lower())
        user_skills.add(s.lower())

    vacancies = _load_vacancies()
    gap_counter = Counter()
    for v in vacancies:
        job_skills_lower = {s.lower() for s in v["skills"]}
        if not (user_skills & job_skills_lower):
            continue
        missing = job_skills_lower - user_skills
        for m in missing:
            gap_counter[m] += 1

    graph = _load_graph()
    name_map = {k.lower(): k for k in graph}

    gaps = []
    for skill_lower, count in gap_counter.most_common(30):
        canonical = name_map.get(skill_lower, skill_lower)
        data = graph.get(canonical, {})
        gaps.append({
            "name": canonical,
            "demand": count,
            "about": data.get("about", ""),
            "parents": data.get("parent", []),
        })
    return gaps


@app.get("/api/detect")
def detect_skills(text: str = Query(..., description="job description text")):
    graph = _load_graph()
    synonyms = _load_synonyms()
    text_lower = text.lower()
    found = {}
    for name in graph:
        if _word_match(name.lower(), text_lower):
            found[name] = graph[name].get("about", "")
    for alias, canonical in synonyms.items():
        if _word_match(alias.lower(), text_lower) and canonical in graph:
            found[canonical] = graph[canonical].get("about", "")
    return {
        "detected": [
            {"name": n, "about": a, "mentions": len(graph.get(n, {}).get("mentions", []))}
            for n, a in sorted(found.items())
        ],
        "count": len(found),
    }


def _word_match(term: str, text: str) -> bool:
    try:
        return bool(re.search(r"\b" + re.escape(term) + r"\b", text))
    except re.error:
        return term in text


@app.post("/api/cache/clear")
def clear_cache():
    _cache.clear()
    return {"status": "cache cleared"}
