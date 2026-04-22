# Tally — LinkedIn → Obsidian via Chrome extension

<img width="761" height="416" alt="image" src="https://github.com/user-attachments/assets/afbb84f7-56d1-4540-ab8d-ff125e129f1f" />

A Chrome extension that saves LinkedIn vacancies and companies into an
Obsidian knowledge graph as you browse. Your own logged-in session, no
separate accounts or Playwright headless crawlers — the extension reads
the DOM LinkedIn already rendered for you.

## Architecture

```
    Chrome (you, logged into your own LinkedIn)
                │
                │  DOM → {title, company, description, …}
                ▼
    ┌────────────────────────┐
    │ Plugin                 │
    │  • content.js          │  Save / Autopilot buttons, skill highlight
    │  • popup.js            │  Dashboard, matcher, gaps
    │  • background.js       │  CORS proxy to the API
    └────────┬───────────────┘
             │  POST /api/parse
             ▼
    ┌────────────────────────┐
    │ API server (FastAPI)   │  chrome_plugin/api_server.py
    │  localhost:8000        │  — writes .md files, rate-limits,
    │                        │    serves dashboard queries
    └────────┬───────────────┘
             │ writes
             ▼
    ┌────────────────────────┐
    │ obsidian_vault/        │  Vacancies / Companies / Skills
    │  (your source of truth)│  (Skills graph built separately —
    └────────────────────────┘   see "Legacy skills enrichment" below)
```

## What the plugin does

| Where | What |
|---|---|
| `/jobs/view/*` | "Save to vault" button — single-click parse of the current vacancy |
| `/jobs/collections/*`, `/jobs/search/*` | "Autopilot" — walks the visible list, clicks each card, parses, paginates `?start=0,24,48…` with 8–20 s human-like delays. Stop button to abort. |
| Any `/jobs/*` page | Scans the description, highlights skills already in your graph, floating panel with skill counts |
| Popup | Dashboard (totals, top skills chart, freshness), Skills browser, multi-skill Matcher, Companies, Skill Gaps |

Writes nothing to LinkedIn — purely read-only scraping of the DOM you're
already viewing.

## Quick start

Prereqs: Python 3.11+, Google Chrome.

```bash
# 1. Install Python deps
python3 -m venv venv
source venv/bin/activate
pip install -r chrome_plugin/requirements.txt

# 2. (Optional) copy .env.example → .env if you want to change the daily cap
cp .env.example .env

# 3. Start the API server
venv/bin/uvicorn chrome_plugin.api_server:app --reload --port 8000

# 4. Load the extension
#    chrome://extensions → Developer mode → Load unpacked → select chrome_plugin/

# 5. Open LinkedIn, click the icon, browse / Save / Autopilot
```

## Tests

```bash
venv/bin/pytest tests/ -v
```

Covers the API server (parse endpoint, idempotency, daily cap, HTML→Markdown,
dashboard freshness, autocomplete, skill detection with synonyms, matcher,
gaps, cache invalidation) and the rate-limiter. Every test uses an isolated
throwaway vault — your real data is never touched.

## Daily cap

`JOB_MINER_DAILY_CAP` in `.env` (default 600) caps how many vacancies
`/api/parse` will accept per day, persisted in `data/rate_limit.json`.
Prevents a runaway autopilot from spamming the vault; resets at midnight
local time.

## Pre-commit hook

Optional safety net to keep sessions / cookies / `.env` files out of git:

```bash
git config core.hooksPath .githooks
```

## Legacy skills enrichment (offline, optional)

The plugin writes raw Vacancy + Company markdown. Turning those into a
linked skills graph is a separate LLM-powered step — it does not run
from the plugin and does not need the plugin to be running. All those
scripts live in [`legacy/`](legacy/) and are kept around for one-shot
maintenance, not active development. See [`legacy/README.md`](legacy/README.md)
for the full inventory and usage.

Quickest entry points (run from repo root so `obsidian_vault/` and
`data/` resolve correctly):

```bash
venv/bin/python legacy/skills_miner_adk.py --limit 5 --dry-run   # test extraction
venv/bin/python legacy/reorganize_vault.py --analyze              # LLM dedup manifest
venv/bin/python legacy/seed_graph.py                              # rebuild graph json
```

Set `GOOGLE_API_KEY` in `.env` before running anything that calls Gemini
(`skills_miner_adk.py`, `reorganize_vault.py`).

## Repository structure

```
├── chrome_plugin/           — ACTIVE: Chrome extension + FastAPI backend
│   ├── manifest.json, popup.{html,js,css}, content.{js,css}, background.js
│   ├── api_server.py        — FastAPI backend
│   ├── icons/
│   └── requirements.txt
│
├── config.py                — shared paths (with env overrides) + daily-cap rate limiter
├── tests/                   — pytest suite for backend + config
│
├── legacy/                  — offline one-shot scripts (skills enrichment, vault maintenance)
│   ├── skills_miner_adk.py, skills_tools.py
│   ├── reorganize_vault.py, merge_skills.py, seed_graph.py
│   ├── build_manifest.py, fix_company_backlinks.py, recover_parsed.py
│   └── README.md            — per-script purpose and usage
│
├── data/                    — runtime state (gitignored)
│   ├── rate_limit.json       — daily cap counter (auto-managed)
│   ├── skills_graph.json     — skills graph state (legacy)
│   ├── skill_synonyms.json   — abbreviation → canonical (legacy)
│   └── skills_mined.json     — processed-vacancy tracker for enrichment (legacy)
│
└── obsidian_vault/          — the source of truth (gitignored)
    ├── Vacancies/           — one .md per job (plugin-written)
    ├── Companies/           — one .md per company (plugin-written)
    └── Skills/              — one .md per skill (legacy enrichment step)
```

Active development focuses on `chrome_plugin/`, `config.py`, and `tests/`.
Everything under `legacy/` is frozen — kept for historical vault
maintenance, not rewritten to match the plugin's current design.

## Roadmap

- **Container** — wrap `api_server.py` in Docker so the backend can run anywhere
- **Obsidian sync endpoint** — `/api/updates?since=<ts>` so the vault can
  be pulled from anywhere instead of only written where the server runs
- **Sidebar UI** — embed the popup as a LinkedIn sidebar (`ADR-PLUGIN-001`)
  instead of a detached Chrome popup, matching LinkedIn's light/dark theme
