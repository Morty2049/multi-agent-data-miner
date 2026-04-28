# Phase 6 — Skill ontology + search-based match scoring

**Status:** Draft (planning only — not yet greenlit)
**Predecessor:** Phase 3 LLM match-scoring (`chrome_plugin/scoring.py`, ADR 0002)
**Author/owner:** Aleksei Petrov
**Date:** 2026-04-27

## 1. Goals & non-goals

### Goals
- Build a **shared skill ontology** mined from the vault's accumulated job descriptions — one canonical entry per atomic skill, with synonyms, parents, and per-corpus rarity.
- Link **per-vacancy skill atoms** back to that ontology so every JD knows "which of the canonical skills it asks for."
- Replace the **default match score** with a deterministic set/graph-similarity computation over those atoms — instant, free, reproducible, explainable as `you have 7/10 listed skills`.
- **Demote** the LLM scoring path (Phase 3) to an opt-in second pass: a "Get LLM analysis" button next to the search score, used for the qualitative narrative + non-skill considerations (seniority, soft skills, geographic/language fit) that a set-overlap can't see.
- Keep all storage **append-only / regenerable** so a bad ontology build never corrupts the vault.

### Non-goals (deferred / out of scope)
- **Replacing Phase 3.** The Gemini-Flash engine, prompt, cache, and threshold UI all stay. Phase 6 sits *before* it in the call graph and turns Phase 3 into a button instead of an automatic call.
- **Re-running ontology on every settings change.** Build is offline (script or button), query is live. The query path never blocks on a rebuild.
- **Multi-language ontology.** ~5% of the vault is Portuguese / Spanish / French JDs (LinkedIn-Lisbon reality). v1 indexes English-language descriptions only; non-English JDs fall through to the LLM path unchanged.
- **Ontology as a UX surface in v1.** Skills in Obsidian get markdown files but no in-extension browser. The Phase 6 sidebar shows a list of matched + missing atoms only.
- **Cross-user / shared ontology.** Each Tally checkout owns its own ontology, the same way each owns its own vault.

---

## 2. Empirical pre-flight (Slice 6.1, gate)

Before any code that lives in `chrome_plugin/`, prove that the corpus is dense enough for clustering to converge. The earlier (retired) `legacy/skills_miner_adk.py` attempt failed on too few JDs; `obsidian_vault/Vacancies/` now has 1576 markdown files, which is the threshold worth re-testing.

**Script (one-off):** `scripts/skill_extraction_feasibility.py` (or a Jupyter notebook under `notebooks/`, either is fine; the output matters, not the format).

### Inputs
- All `obsidian_vault/Vacancies/*.md` `description_text` blocks, joined.
- Aleksei's profile from `code-references/career-ops-ref/config/profile.yml` (or `data/profile.yml` if present — `config.load_profile()` already encodes the fallback).

### Pipeline
1. Strip frontmatter, lowercase, drop boilerplate ("we offer", "what you'll do", etc.) using a small stop-phrase list.
2. **Noun-phrase extraction** with spaCy `en_core_web_sm` (already a transitive dep via existing parsers; if not, add — it's small).
3. TF-IDF over the corpus to weight phrases by rarity.
4. Embed the top ~2000 phrases with **`sentence-transformers/all-MiniLM-L6-v2`** — runs on CPU in <2 min, no API.
5. Cluster (HDBSCAN on the embedding space — better than k-means for variable-density skill clouds).

### Outputs (deterministic, dropped into git)
- `docs/research/skill-extraction-feasibility.md` — short prose report.
- `docs/research/skill-extraction-feasibility.json` — top 200 candidate atoms with cluster id, member phrases, and corpus frequency.
- A **profile-roundtrip table**: for each skill the script can plausibly extract from `profile.yml.narrative.superpowers + proof_points`, does it surface in the discovered atom list? Hit / miss / partial.

### Decision gate
- **Proceed to Slice 6.2** if ≥ 60% of profile skills surface from the data AND ≥ 70% of the top 200 clusters are coherent on a 5-minute manual scan.
- **Defer Phase 6** otherwise — write the negative result into the same file and stop. Phase 3 alone keeps shipping. The pre-flight cost is half a day; we accept a "no" as a valid outcome.

Why this gate: Aleksei was burned once by building skill extraction prematurely. Half a day of analysis is cheap insurance against a week of building on a corpus that isn't dense enough yet.

---

## 3. Storage decision: ontology

**Decision: Option C — hybrid. Obsidian markdown is source-of-truth, runtime cache as JSON.**

### The three options considered

- **A. Obsidian-only.** One `obsidian_vault/Skills/<slug>.md` per atom, frontmatter holds `synonyms`, `parent_skill`, `category`, `source_count`. Plays with Obsidian's graph view, hand-curatable.
- **B. JSONL-only.** `data/skills_ontology.jsonl`, flat machine-friendly, one line per atom. Fast, easy to version, but no curation surface.
- **C. Hybrid.** Markdown is canonical (humans edit it, Obsidian links it, Git tracks renames). A `data/skills_ontology.json` cache is rebuilt from the markdown on demand; everything in `chrome_plugin/` reads the cache.

### Why C
- The **2016 legacy `obsidian_vault/Skills/*.md`** files already exist from the abandoned attempt. Throwing them away is wasteful; treating them as the storage substrate (after a re-bootstrap pass) costs nothing and reuses Aleksei's existing manual curation if he ever does any.
- Obsidian graph view becomes a free debugging tool — "show me everything that links to `[[Python]]`" is one click.
- The JSON cache decouples query latency from filesystem walks: a Match-section render hits one `json.load` instead of 2000 file reads.
- Cache is fully derivable. If it's stale, delete and rebuild. There's no two-source-of-truth divergence risk because the markdown always wins.

### Schema

`obsidian_vault/Skills/<slug>.md`:
```yaml
---
type: skill
slug: rag-observability
synonyms: [llm tracing, rag eval, llm observability]
parents: [observability, llm-engineering]
category: tooling
source_count: 23      # how many JDs in the current corpus mention this atom
last_built: 2026-04-27
---
# RAG observability

## About
Tooling and practices for tracing retrieval-augmented generation pipelines …

## Mentions
- [[Company_X_-_Senior_AI_Engineer_(123…)]]
…
```

`data/skills_ontology.json` (rebuilt from above):
```json
{
  "built_at": "2026-04-27T10:00:00+00:00",
  "atoms": {
    "rag-observability": {
      "synonyms": ["llm tracing", "rag eval", "llm observability"],
      "parents": ["observability", "llm-engineering"],
      "category": "tooling",
      "source_count": 23,
      "idf": 4.21
    },
    …
  }
}
```

### New paths in `config.py`
```python
SKILLS_DIR        = VAULT_DIR / "Skills"               # markdown source
ONTOLOGY_CACHE    = DATA_DIR / "skills_ontology.json"  # built artefact
VACANCY_SKILLS    = DATA_DIR / "vacancy_skills.jsonl"  # see §4 below
```

### New helpers (added to `chrome_plugin/skill_ontology.py`, new module)
- `build_ontology() -> dict` — walks `SKILLS_DIR`, computes IDF over the current vacancy corpus, writes `ONTOLOGY_CACHE`.
- `load_ontology() -> dict` — reads the cache; rebuilds if missing.
- `find_skill(name: str) -> str | None` — resolves a raw phrase ("Pythn") to a canonical slug ("python") via synonym map + fuzzy match (rapidfuzz, ≥ 90).
- `linked_skills(slug: str) -> list[str]` — graph neighbours (parents + children).

---

## 4. Storage decision: per-vacancy skill links

**Decision: Option A — store `skills:` in each vacancy's frontmatter. With a side `data/vacancy_skills.jsonl` audit log of extraction events.**

### Two options considered
- **A. Vacancy frontmatter.** `skills: [python, fastapi, rag-observability]` written into the YAML at the top of each `obsidian_vault/Vacancies/*.md`. Plays with Obsidian's graph (vacancy ↔ skill ↔ vacancy), human-readable, survives outside Tally.
- **B. Side file `data/vacancy_skills.jsonl`.** `{"job_id": "…", "skills": [...], "extracted_at": "..."}`. Doesn't touch existing markdown.

### Why A (with B as audit log, not as primary store)
- Obsidian graph view becomes useful: clicking `[[Python]]` shows every JD that wants Python, no extension needed.
- The extension already roundtrips frontmatter through `parse_job` / `update_vacancy_md` — adding one key is a 10-line YAML-dump change, not a new persistence layer.
- We **also** append to `data/vacancy_skills.jsonl` on every extraction (`{job_id, skills, extracted_at, ontology_version}`) so re-builds of the ontology can detect "this JD was tagged against an older ontology, retag." That JSONL is the audit / cache invalidation layer, not the source of truth.

### Migration is one-time and idempotent
A script walks `obsidian_vault/Vacancies/*.md`, runs `extract_skills(description_text)`, writes `skills: [...]` into the frontmatter if absent. Re-running is a no-op (skip if `skills:` already present and ontology version matches).

The **`skills:` frontmatter mutation** is a real change to existing markdown — that needs to be landed once, after Slice 6.2 has stabilised the ontology. We use the same YAML-quoting safety the recent `fef46e2 fix(parse): YAML-quote free-text fields` commit established.

---

## 5. Profile → skill atoms

The candidate side needs the same treatment, or set-overlap is undefined.

### Approach
- New helper `extract_profile_skills(profile)` that runs the same NP-extraction + `find_skill()` pipeline over `narrative.superpowers` + `narrative.proof_points` (the same fields Phase 3 already feeds into the prompt — see `_build_prompt` in `scoring.py`).
- Result is stored as a derived field `profile.skills_resolved: [...]` and persisted into `data/profile.yml` so the user sees what scoring actually uses.
- Stored at the top level (not under `narrative`) to mirror the "computed cache, not user input" pattern.
- Regenerated on:
  - first ontology build,
  - every `POST /api/profile` save (new hook in `save_profile`),
  - explicit "Re-extract my skills" button in the settings panel.

### Why a button and not pure-derived
The auto-extraction will mistake "stakeholder workshops" for an atom; a one-time human review pass is necessary. The settings panel surfaces `skills_resolved` as an editable list (add / remove / pin). The pin is durable — pinned atoms survive future re-extractions.

---

## 6. Search-based scoring algorithm

**Decision: weighted Jaccard with optional 1-hop graph fallback. No ML at query time.**

### Inputs
- `profile_atoms: set[str]` (slugs) — from `profile.skills_resolved`.
- `vacancy_atoms: set[str]` (slugs) — from the JD's `skills:` frontmatter.
- `idf: dict[str, float]` — from `ontology.atoms[slug].idf` in the cache.

### Score
```python
def score(profile_atoms, vacancy_atoms, idf, ontology):
    if not vacancy_atoms:
        return None  # fall through to LLM path
    matched = profile_atoms & vacancy_atoms
    # Graph fallback: 1-hop credit for siblings (shared parent)
    near_matched = {
        v for v in (vacancy_atoms - matched)
        if any(p in profile_atoms for p in linked_skills(v, ontology))
    }
    weight_v = sum(idf[a] for a in vacancy_atoms)
    weight_m = sum(idf[a] for a in matched) + 0.5 * sum(idf[a] for a in near_matched)
    return round(100 * weight_m / weight_v)
```

- **Weighted by rarity (IDF).** "Python" matched is worth less than "RAG observability" matched — the latter is a real signal, the former is a common-noun mention.
- **Graph fallback at 0.5 weight.** Vacancy wants Pandas, profile has NumPy → both share parent `python-data-stack` → 0.5 × Pandas's IDF credited.
- **`None` when vacancy has no atoms.** Empty `vacancy.skills` (extraction failed, JD too short, foreign-language) — return `None` and let the existing LLM path handle it.

### Output shape — same as Phase 3
The Match section UI is unchanged. `score_search()` returns:
```json
{
  "match_pct": 73,
  "summary": "You match 7/10 listed skills (Python, FastAPI, RAG, observability, Docker, AWS, agent frameworks).",
  "skills":  [{"name": "Python", "weight": 0.78, "evidence": "from profile.skills_resolved"}, ...],
  "gaps":    [{"name": "Kubernetes", "severity": "soft", "mitigation": "adjacent: Docker, ECS"}, ...],
  "engine":  "search"
}
```

The `summary` is generated deterministically: "You match {len(matched)}/{len(vacancy_atoms)} listed skills: {top 8 by IDF}". No prose. The LLM path (when invoked) overwrites `summary` with its richer narrative and bumps `engine` to `gemini-flash`.

### Why weighted Jaccard, not embeddings cosine
- Reproducible. A user re-checking yesterday's score sees the same number today; an embedding cosine would drift if we ever swap models.
- Explainable. "73% because you have these 7 of 10" beats "73% because the vectors point in similar directions."
- Free at query time. Embedding cosine needs vectors loaded; weighted Jaccard is `set.intersection` over a few dozen strings.

---

## 7. Slicing breakdown

Each slice ships something visible (or, for 6.1, decides whether to ship at all).

### Slice 6.1 — Empirical pre-flight (~½ day)
- **Files touched:**
  - `scripts/skill_extraction_feasibility.py` — new, one-off.
  - `docs/research/skill-extraction-feasibility.md` + `.json` — new, the actual decision artefact.
- **User-visible after this slice:** none directly. Decision: proceed to 6.2 or stop.

### Slice 6.2 — Build ontology, store as Obsidian + JSON cache (~1 day)
- **Files touched:**
  - `chrome_plugin/skill_ontology.py` — new module: `build_ontology`, `load_ontology`, `find_skill`, `linked_skills`.
  - `config.py` — add `SKILLS_DIR`, `ONTOLOGY_CACHE`, `VACANCY_SKILLS` paths.
  - `scripts/bootstrap_ontology.py` — one-off: takes the 6.1 output, re-bootstraps `obsidian_vault/Skills/` (the legacy 2016 files become the manual-curation seed; we **don't** delete them, we re-index them).
  - `tests/test_skill_ontology.py` — new: cache build determinism, synonym resolution, fuzzy match boundary cases, graph traversal.
- **User-visible:** running `python -m scripts.bootstrap_ontology` produces `data/skills_ontology.json`. Match section is still on Phase 3.

### Slice 6.3 — Per-vacancy skill extraction (~1 day)
- **Files touched:**
  - `chrome_plugin/skill_ontology.py` — add `extract_skills(description_text) -> list[str]`.
  - `chrome_plugin/api_server.py` — add `POST /api/extract-skills/{job_id}`; wire into the existing parse path so newly-saved vacancies get tagged immediately.
  - `scripts/migrate_vacancy_skills.py` — one-off, idempotent: walks all `obsidian_vault/Vacancies/*.md`, adds `skills:` frontmatter where absent, appends to `data/vacancy_skills.jsonl`.
  - `tests/test_skill_extraction.py` — golden-string tests for a known JD → expected atoms.
- **User-visible:** Obsidian graph view shows JDs linking to Skills. The migration runs once, takes ~5 min, and is reversible (the YAML field is removable; no other state changes).

### Slice 6.4 — Search scoring + sidebar wiring (~1 day)
- **Files touched:**
  - `chrome_plugin/scoring_search.py` — new: `score_search(profile, vacancy, ontology) -> dict`, mirrors `scoring.score_vacancy` shape. Same `{match_pct, summary, skills, gaps, engine}` contract.
  - `chrome_plugin/api_server.py::score_job` — try search first, fall through to LLM only on `None` (no atoms) or `?force_llm=1` query param.
  - `chrome_plugin/sidebar.html` + `sidebar.js` — Match section adds matched/missing atom chips below the percentage; LLM-call-button labelled `Get LLM analysis` (replaces the auto-trigger).
  - `chrome_plugin/sidebar.css` — chip styling consistent with existing tier colours.
  - `config.py::append_score` — record the `engine` field in `data/scores.jsonl` (additive; Phase 3 entries get backfilled with `engine: "gemini-flash"` only if `engine` is missing — non-destructive).
  - `tests/test_scoring_search.py` — overlap math, IDF weighting, graph fallback, `None`-when-empty.
- **User-visible:** opening any saved JD shows an instant percentage + chips. The "Get LLM analysis" button is opt-in and uses the existing Phase 3 path verbatim.

---

## 8. Migration plan

### `obsidian_vault/Skills/` (legacy, 2016 files)
- Treated as **seed**, not blocker. The pre-flight (6.1) discovers atoms; the bootstrap (6.2) creates / updates markdown for each discovered atom. Existing files with the same slug get their `synonyms`/`parents` merged, not overwritten — manual curation survives.
- Files for atoms that the new pipeline doesn't surface (probably hundreds) are left in place but get a `source_count: 0` and `stale: true` in frontmatter. The user can prune by hand later if they care; the runtime ignores them.

### `obsidian_vault/Vacancies/` (1576 files in main vault)
- Migration script writes `skills: [...]` into frontmatter once, only where absent. Idempotent.
- The script uses the same YAML-quoting fix that `fef46e2` introduced — `skills` is a list of slugs (no quotes needed), but the script must not disturb already-quoted free-text fields.
- Reversibility: a one-line `awk` removes the `skills:` field if we ever want to back out.

### `data/scores.jsonl`
- Existing rows are **kept**. We only add `engine` to **new** rows. A backfill helper `_backfill_engine_field()` runs once on first read after Phase 6 ships and stamps `engine: "gemini-flash"` on rows that lack it. Append-only safety: backfill writes to a temp file then atomic-renames, never partial-overwrites.
- Schema is forward-compatible: ADR 0002 explicitly didn't pre-commit the cache contract to LLM-only.

### `data/profile.yml`
- Add `skills_resolved: [...]` derived field. Regenerated whenever:
  - the user `POST /api/profile` (new hook),
  - the ontology is rebuilt (new hook),
  - the user clicks "Re-extract my skills" in the settings panel (new endpoint).
- Pinned atoms (user-flagged) are preserved across regenerations via a sibling `skills_pinned: [...]` array that the regeneration path unions in.

---

## 9. Open questions / risks

1. **Skill granularity drift.** "Python" vs "Python 3" vs "Python 3.10" — where to draw the line? **Proposal:** the bootstrap merges anything that shares ≥ 0.85 cosine in MiniLM space. Versioned variants get folded into the parent. Re-evaluated only if a user reports false negatives.
2. **Hallucinated buzzword skills in JDs.** Recruiters list "AI/ML" on roles that are CRUD work; clustering may amplify that noise. **Mitigation:** weight extraction by repetition across JDs; an atom that appears in 1 JD with low TF-IDF weight is a candidate for the `stale: true` flag in Skills frontmatter. Phase 3's LLM path is still available for JDs the user feels search misjudged.
3. **Profile ground-truth is squishy.** `profile.yml.narrative` is prose, not a skills list. The auto-extraction will miss tacit skills ("led cross-functional rollouts" → people-management isn't in the ontology). **Mitigation:** the settings-panel review pass + pinned atoms. Document this as a one-time chore.
4. **Multi-language vault subset (~5%).** Portuguese/Spanish JDs won't get tagged. **Behaviour:** `vacancy_atoms == set()` → `score_search` returns `None` → sidebar falls through to "Get LLM analysis" automatically. No user-visible regression vs Phase 3.
5. **When does ontology rebuild fire?** **Proposal:** weekly cron (the user already runs the dev server daily; a `--rebuild-ontology-if-stale` flag on startup, plus an explicit "Rebuild ontology" button in the settings panel). Per-save rebuild is too expensive (5 min); never-rebuild lets IDF weights drift.
6. **`legacy/skills_miner_adk.py` resurrection?** No. The clustering approach in 6.1 is incompatible with the ADK-agent pattern that file used. Delete after 6.4 lands and the new pipeline is stable for two weeks. Until then, leave it as-is — the worst it can do is sit on disk.
7. **Engine field in `data/scores.jsonl` consistency.** What if a user re-scores a JD with `?force_llm=1` after a search-engine score is cached? **Proposal:** both rows persist. `load_score(job_id)` already takes the latest, so the LLM result wins for that JD until the next search-engine re-tag. Distinguishable by `engine` field for debugging.
8. **Sidebar chip overflow.** A JD with 25 listed atoms blows out the layout. **Proposal:** show top 8 by IDF, "+ N more" toggle. Same pattern as the existing skills/gaps lists.
