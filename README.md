# LinkedIn Data Miner
<img width="761" height="416" alt="image" src="https://github.com/user-attachments/assets/afbb84f7-56d1-4540-ab8d-ff125e129f1f" />

An autonomous pipeline that mines LinkedIn job vacancies into a structured Obsidian knowledge graph — with bi-directionally linked Vacancies, Companies, and Skills nodes.

---

## Pipeline Overview

```
LinkedIn (Playwright) ──► Vacancies/*.md  ──► Skills Miner (ADK)
                      ──► Companies/*.md        │
                                                ├─ Skills/*.md  ◄──► [[wikilinks]]
                                                └─ skills_graph.json

One-time cleanup:   reorganize_vault.py  (LLM dedup + cluster tags)
Maintenance:        merge_skills.py      (rule-based dedup + link repair)
```

The system runs in three main phases:

| Phase | Script | Description |
|---|---|---|
| 1. Collect | `collect_queue.py` | Scrape LinkedIn feed → `data/job_queue.json` |
| 2. Parse | `run_queue.py` | Process queue → `Vacancies/` + `Companies/` files |
| 3. Mine Skills | `skills_miner_adk.py` | Two-agent ADK pipeline → `Skills/` + wikilinks |

Plus two maintenance utilities:

| Script | Description |
|---|---|
| `reorganize_vault.py` | LLM-based vault reorganization (dedup, clustering, hierarchy) |
| `merge_skills.py` | Rule-based dedup and broken link repair |

---

## Chrome Extension — Job Miner

A local Chrome extension that turns your vault into a live intelligence layer
on top of LinkedIn:

- **Dashboard** — total vacancies/companies/skills, top skills bar chart,
  locations, employment types
- **Skills browser** — search the skill graph, see parents/children/mentions
- **Job Matcher** — enter your skills → ranked jobs with match score %
- **Company explorer** — search companies, see job counts
- **Skill Gap analysis** — shows skills you're missing from matching jobs
- **Content script** — auto-detects and highlights tracked skills on any
  LinkedIn `/jobs/*` page (floating panel + inline highlights)

### Quick start

```bash
# 1. Start the API server (reads obsidian_vault/ + data/)
venv/bin/uvicorn chrome_plugin.api_server:app --reload --port 8000

# 2. Load extension in Chrome
#    chrome://extensions → Developer mode → Load unpacked → select chrome_plugin/

# 3. Open any LinkedIn job page — skills are auto-highlighted
#    Click the extension icon for the full dashboard
```

### Tests

The API server and `config.py` have pytest coverage. Each test builds an
isolated throwaway vault in `tmp_path`, so real data is never touched.

```bash
venv/bin/pytest tests/ -v
```

29 tests cover: health, rate limiter (persist, reset, cap), dashboard
freshness, skill search + autocomplete, skill detail, skill detection
(with synonyms), POST /api/parse (creates files, idempotent, respects
daily cap, HTML→Markdown), matcher, gaps, companies, cache invalidation,
backoff math.

### Future: multi-user service

> The current architecture is local-first (vault on disk, localhost API).
> As the project grows toward a multi-user service:
> - Replace file-based vault reads with a centralized DB (Postgres + pgvector)
> - API server → cloud deployment (FastAPI on Railway / Fly.io / Supabase Edge)
> - Auth layer (API keys or OAuth) for per-user data isolation
> - Chrome extension communicates with the remote API instead of localhost
> - Shared skill graph across users; per-user vacancy/company data

---

## Safety & account hygiene

This repo scrapes LinkedIn from a secondary "market-research" account
(`linkedin_session_market/` — never the personal one). All rate-limiting and
ban-detection lives in [`config.py`](config.py):

- single source of truth for `SESSION_DIR` (defaults to `linkedin_session_market`)
- random per-job delays (8–20 s), random per-page delays (3–8 s)
- hard **daily parse cap of 600 vacancies** persisted in `data/rate_limit.json`
- exponential backoff (30 s → 10 min) on transient errors
- immediate halt when a `/checkpoint/`, `/authwall`, or "security verification"
  page is detected
- `.env` + `.env.example` for configuration; `.env` is gitignored
- pre-commit hook in `.githooks/pre-commit` blocks any staged session / cookie /
  `.env` file. Install once:

```bash
git config core.hooksPath .githooks
```

Any variant of `linkedin_session*/`, `sessions/`, `cookies/`, `*.session`,
`chrome_profile*`, `.env` and `.env.*` is in `.gitignore`.

---

## Quick Start

### Prerequisites

```bash
python3 -m venv venv
source venv/bin/activate
pip install playwright python-dotenv google-adk
playwright install chromium
```

Create a `.env` file:

```
GOOGLE_API_KEY=your_key_here
```

### Phase 1 — Collect vacancy URLs

```bash
venv/bin/python collect_queue.py
# Scrolls LinkedIn Recommended Jobs → data/job_queue.json
```

### Phase 2 — Parse vacancies

```bash
# Process all queued URLs
venv/bin/python run_queue.py data/job_queue.json

# Or parse a single URL
venv/bin/python parse_job.py https://www.linkedin.com/jobs/view/123456789/

# Limit for testing
venv/bin/python run_queue.py data/job_queue.json --limit 10
```

### Phase 3 — Mine skills

```bash
# Dry-run preview (no files changed)
venv/bin/python skills_miner_adk.py --limit 5 --dry-run

# Process all unprocessed vacancies (3 parallel workers by default)
venv/bin/python skills_miner_adk.py

# Adjust concurrency
venv/bin/python skills_miner_adk.py --concurrency 5
```

### Vault reorganization (run once, or after large batch)

```bash
# Step 1: Generate LLM-based reorganization plan
venv/bin/python reorganize_vault.py --analyze

# Review data/reorganize_manifest.json, then apply:
venv/bin/python reorganize_vault.py --apply

# Verify result
venv/bin/python reorganize_vault.py --verify

# Or all in one shot
venv/bin/python reorganize_vault.py --analyze --apply --verify
```

### Maintenance (rule-based cleanup)

```bash
# Dry-run report: duplicates + broken links
venv/bin/python merge_skills.py

# Apply fixes (creates backup automatically)
venv/bin/python merge_skills.py --apply

# Rollback
venv/bin/python merge_skills.py --restore
```

---

## Repository Structure

```
├── collect_queue.py        # Phase 1: Scrape LinkedIn feed → job_queue.json
├── run_queue.py            # Phase 2: Batch processor for job_queue.json
├── parse_job.py            # Core parser: single LinkedIn URL → Obsidian .md
├── skills_miner_adk.py     # Phase 3: Two-agent ADK skills extraction pipeline
├── skills_tools.py         # File I/O tools for the skills miner
├── reorganize_vault.py     # LLM-based vault reorganization (dedup + clustering)
├── merge_skills.py         # Rule-based dedup and broken link repair
├── seed_graph.py           # Utility: rebuild skills_graph.json from Skills/
├── fix_company_backlinks.py  # Utility: repair company → vacancy backlinks
├── recover_parsed.py       # Utility: recover already-parsed vacancy files
│
├── data/
│   ├── job_queue.json              # URLs to process (Phase 2 input)
│   ├── skills_graph.json           # Running skills graph state
│   ├── skill_synonyms.json         # Abbreviation → canonical name dictionary
│   ├── skills_mined.json           # Processed vacancy tracker (idempotency)
│   ├── reorganize_manifest.json    # LLM reorganization plan (inspect before apply)
│   └── checkpoints/                # Per-vacancy extraction checkpoints (crash recovery)
│
├── obsidian_vault/
│   ├── Vacancies/          # One .md per job vacancy
│   ├── Companies/          # One .md per company
│   └── Skills/             # One .md per technical skill
│
├── arch/
│   ├── ADR.md              # Architecture Decision Records
│   ├── ARCHITECTURE.md     # System architecture overview
│   ├── FUNCTIONAL_REQUIREMENTS.md
│   └── history.md          # Development history log
│
└── linkedin_session/       # Persistent Chromium session (gitignored)
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Collect                                            │
│   collect_queue.py → Playwright → LinkedIn Recommended      │
│   → data/job_queue.json                                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: Parse                                              │
│   run_queue.py → parse_job.py → Playwright                  │
│   → Vacancies/{Company}_{Title}_{ID}.md                     │
│   → Companies/{Company}.md                                  │
│   (bi-directional [[wikilinks]] between Vacancies ↔ Companies)│
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: Mine Skills (ADK)                                  │
│                                                             │
│  Vacancy .md                                                │
│      │                                                      │
│      ▼                                                      │
│  Agent 1 (Extractor)  → raw JSON skill list                 │
│      │                                                      │
│      ▼                                                      │
│  Agent 2 (Reviewer)   → normalized + validated skills       │
│      │                                                      │
│      ▼                                                      │
│  skills_tools.py (Python)                                   │
│      ├─ insert_wikilinks()   → Vacancy gets [[Skill]] links │
│      ├─ upsert_skill()       → Skills/{Skill}.md created    │
│      └─ mark_processed()     → added to skills_mined.json   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ (periodic / after batch)
┌─────────────────────────────────────────────────────────────┐
│ Maintenance                                                 │
│   reorganize_vault.py  → LLM groups semantically            │
│     equivalent skills, assigns cluster tags (#cloud, #ai…)  │
│   merge_skills.py      → rule-based dedup + link repair     │
│   seed_graph.py        → rebuild skills_graph.json          │
└─────────────────────────────────────────────────────────────┘
```


---

## Skills Knowledge Graph

Each skill file (`Skills/Kubernetes.md`) follows this structure:

```markdown
---
type: skill
tags: [skill, #containers, #devops]
---
# Kubernetes

## About
Container orchestration platform for automating deployment and scaling.

## Parent
- [[Container Orchestration]]
- [[DevOps]]

## Children
- [[GKE]]
- [[EKS]]
- [[AKS]]

## Mentions
- [[Acme_Corp_-_DevOps_Engineer_(4383250025)]]
- [[Nokia_-_Solutions_Architect_(4377793741)]]
```

Vacancy files link to skills via Obsidian aliases:

```markdown
Experience with [[Kubernetes|K8s]] orchestration and [[CI/CD|CI_CD]] pipelines.
```

This creates a navigable graph: **Vacancy → Skill → Category → Child Skills**.

---

## Configuration

| Constant | File | Default | Description |
|---|---|---|---|
| `SESSION_DIR` | `parse_job.py` | `linkedin_session/` | Persistent Chromium session |
| `VAULT_BASE` | `parse_job.py` | `obsidian_vault/` | Output root |
| `MODEL` | `skills_miner_adk.py` | `gemini-2.5-flash-lite` | ADK agent model |
| `CONCURRENCY` | `skills_miner_adk.py` | `3` | Parallel extraction workers |
| `MAX_RETRIES` | `skills_miner_adk.py` | `3` | JSON parse retries per agent |
| `BATCH_SIZE` | `reorganize_vault.py` | `120` | Skills per LLM batch |

---

## Architecture Decisions

See [arch/ADR.md](arch/ADR.md) for all Architecture Decision Records.

Key decisions:
- **Two-agent ADK pipeline** — Extractor + Reviewer prevents hallucinations from leaking into files
- **Obsidian alias wikilinks** — `[[Canonical|Original]]` keeps vault readable while graph resolves correctly
- **LLM-based reorganization** — `reorganize_vault.py` uses Gemini to detect semantic duplicates that rule-based normalization cannot (K8s = Kubernetes, CI_CD = CI/CD)
- **Parallel extraction, sequential apply** — LLM calls run concurrently; file writes are always sequential to prevent graph corruption
