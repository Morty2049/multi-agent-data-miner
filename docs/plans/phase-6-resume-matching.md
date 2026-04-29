# Phase 6 — Resume matching + first real backend

**Status:** Draft (planning only — not yet greenlit)
**Predecessor:** Phase 5 (skill library; provides the atom ontology this phase scores against)
**Author/owner:** Aleksei Petrov
**Date:** 2026-04-28

## 1. Goals & non-goals

### Goals
- **Multiple resume "personas" per user.** Today there's one `data/profile.yml`. After Phase 6 the user can keep e.g. *Solutions Engineer (pre-sales heavy)* + *Solutions Engineer (post-sales architect)* + *AI Solutions Architect (writer-leaning)*. Each persona has its own atom set, narrative, proof points, and target archetype.
- **Per-vacancy multi-persona scoring.** Sidebar shows match per persona; recommends which one to apply with.
- **First multi-tenant-shaped data layout.** Migrate from flat `data/*` to `data/users/<user_id>/*`. Single tenant for now (`<user_id> = default`), but Phase 7 can drop in real auth without re-shaping.
- **Telemetry pipeline.** Append-only `telemetry.jsonl` per user. Events: `score_shown`, `persona_picked`, `applied_with_persona`, `dismissed_vacancy`, `feedback_thumbs_up/down`, `outcome_offer/rejected/ghosted`.
- **Feedback-aware atom reweighting.** Once enough telemetry exists, atoms that predict positive outcomes (applied, offer) get a small weight boost; atoms that predict dismissal get a small penalty. Bounded so no single signal can dominate the deterministic baseline.
- **Persona-pick UI** in the sidebar Match section, plus an "Apply with this persona" button on `/jobs/view/`.

### Non-goals
- **Real auth.** That's Phase 7. v1 hardcodes `user_id = "default"` (or reads from env `JOB_MINER_USER_ID`).
- **Cross-user features.** No data sharing between users; that's Phase 7.
- **Cover-letter generation as a v1 must-have.** Lives behind the BYO LLM seam, ships as Slice 6.5 stretch.
- **Live retraining loops.** Reweighting recomputes only on explicit "Rebuild weights" button or weekly cron — never per-event.
- **Replacing Phase 5's deterministic baseline.** Reweighting is *additive*; the search-overlap score is always the floor.

---

## 2. Persona schema decision

**Decision: hybrid — Obsidian markdown for human curation, YAML cache for runtime.**

Same pattern as Phase 5's ontology storage. Source of truth is `obsidian_vault/Personas/<slug>.md`; runtime cache is `data/users/<uid>/personas/<slug>.yml` (regenerated from markdown on demand).

```markdown
---
slug: solutions-engineer-presales
name: Solutions Engineer (pre-sales heavy)
target_archetypes:
  - "Pre-sales / Solutions Engineer"
  - "Sales Engineer (technical)"
  - "AI Solutions Consultant"
atoms:                       # link to Phase 5 ontology slugs
  - python
  - fastapi
  - rag
  - llm-apis
  - presales-cycle
  - demo-engineering
narrative: |
  8 years owning the full pre-sales cycle for B2B AI…
proof_points:
  - "30+ enterprise AI projects at Just AI (avg $100K)"
  - "12x cost reduction via LLM at one logistics customer"
compensation:
  target_eur: 70000
  acceptable_min_eur: 55000
---

## About
[Free-form Obsidian content — links to projects, demos, etc.]
```

### Why hybrid over either pure
- **Pure markdown**: Obsidian-native, easy to curate, but slow to query (re-parse YAML per request) and atom slugs are easy to typo.
- **Pure YAML in `data/`**: fast, validated, but the user can't see/edit personas in their daily Obsidian workflow.
- **Hybrid**: markdown is canonical (Aleksei edits there), YAML cache is what `score_persona()` reads. Cache rebuild on file mtime change. Same trick Phase 5 uses for skills.

### Validation rule (in `_validate_persona`)
- `slug` is filename-safe and unique within the user.
- All `atoms` exist in the user's resolved skill graph (Phase 5 ontology slugs).
- `target_archetypes` is a non-empty list of strings.
- Narrative + proof points: free text, length-bounded (10KB total).

---

## 3. Multi-tenant data layout

**Decision: introduce `data/users/<user_id>/` subtree; default user is `default`.**

```
data/
├── users/
│   └── default/
│       ├── personas/         # YAML cache, source = obsidian_vault/Personas/
│       ├── settings.json
│       ├── events.jsonl
│       ├── scores.jsonl
│       ├── telemetry.jsonl   # NEW in Phase 6
│       └── scoring_weights.json  # NEW in Phase 6
├── debug-log.jsonl           # global; not per-user
└── rate_limit.json           # global; LinkedIn rate limits don't fork by user
```

### Migration helper (one-time, idempotent)

`scripts/migrate_to_user_dirs.py`:
1. Detect old layout (flat `data/{events,scores,settings}.jsonl`).
2. `mkdir -p data/users/default/`, move files in.
3. Stamp `data/.migration_v6` with timestamp so re-runs are no-ops.

The vault doesn't move — `obsidian_vault/` stays at its existing path. `obsidian_vault/Personas/` is new.

### `config.py` API additions

```python
def user_dir(user_id: str = None) -> Path:
    """Resolve user-scoped data directory. Reads JOB_MINER_USER_ID
    env if user_id is None. Falls back to 'default'."""
def load_personas(user_id: str = None) -> list[dict]: ...
def load_persona(slug: str, user_id: str = None) -> dict: ...
def save_persona(persona: dict, user_id: str = None) -> dict: ...
def load_telemetry(user_id: str = None, since: str = None) -> list[dict]: ...
def append_telemetry(event: dict, user_id: str = None) -> None: ...
```

All existing helpers (`load_events`, `load_settings`, etc.) gain an optional `user_id` parameter that defaults via `user_dir()`. Backward-compatible: callers that pass nothing still work.

### Endpoint changes

Every existing endpoint that touches per-user data (`/api/events`, `/api/settings`, `/api/score/*`, `/api/profile`, `/api/applications`) accepts an optional `?user_id=…` query param defaulting to the env-resolved user. v1 only ever sees `default`; v7 swaps the default for an auth-derived user.

---

## 4. Telemetry events + pipeline

### Event kinds

| Kind | Fired when | Payload (in addition to `kind`, `user_id`, `at`) |
|---|---|---|
| `score_shown` | sidebar Match section renders | `job_id`, `persona_slug`, `match_pct`, `engine` |
| `persona_picked` | user clicks a persona row in Match | `job_id`, `persona_slug` |
| `applied_with_persona` | user clicks "Apply with this persona" or LinkedIn Easy Apply | `job_id`, `persona_slug` |
| `dismissed_vacancy` | user clicks 👎 / "Not interested" | `job_id`, `reason?` |
| `feedback_thumbs_up` | user clicks 👍 on a score | `job_id`, `persona_slug`, `match_pct` |
| `feedback_thumbs_down` | user clicks 👎 on a score | `job_id`, `persona_slug`, `match_pct`, `reason?` |
| `outcome_offer` | user logs offer event in timeline | `job_id`, `persona_slug` (last applied-with) |
| `outcome_rejected` | user logs rejected event | same |
| `outcome_ghosted` | user logs ghosted event | same |

All written to `data/users/<uid>/telemetry.jsonl` via `append_telemetry()`. Endpoint: `POST /api/telemetry { kind, ...payload }`.

### Privacy posture

- Telemetry stays **local** in v1. No upload. Aleksei can `cat telemetry.jsonl` to see exactly what's recorded.
- Phase 7 introduces opt-in cloud sync with k-anonymity gates. Until then, no network traffic from telemetry.

---

## 5. Matching algorithm refinement

### Multi-persona scoring

For a given vacancy and N personas, compute Phase 5's `score_search(persona, vacancy)` for each. Return the full list, sorted descending by match_pct. The sidebar shows the top result by default with a "+ N alternatives" disclosure.

### Feedback-aware reweighting

Atom weight in the search engine is normally `IDF(atom)`. After Phase 6:

```python
weight(atom) = IDF(atom) * (1 + α*P(applied|atom) - β*P(dismissed|atom))
```

Where:
- `P(applied|atom)` = ratio of `applied_with_persona` events on JDs containing this atom, over all `score_shown` events on JDs containing this atom.
- `P(dismissed|atom)` = same for `dismissed_vacancy`.
- `α = 0.3`, `β = 0.5` defaults; user can tune in settings panel.

**Cold start**: until ≥50 telemetry events exist for a user, both probabilities are treated as 0 (pure baseline). Avoids over-reacting to noise.

**Bounding**: the multiplier is clipped to `[0.5, 1.8]` so no single feedback signal can override a strong baseline IDF.

**Recompute trigger**: weights stored in `data/users/<uid>/scoring_weights.json`. Recomputed on:
1. Explicit "Rebuild weights" button in settings panel.
2. Daily cron (when API server starts and last rebuild was > 24h ago).
3. Never per-event — would thrash the cache.

### Explainability

Sidebar Match section gains a "Why this score?" disclosure that lists:
- Top 3 matched atoms with their (IDF × multiplier) contribution
- Top 3 missing atoms with their lost contribution
- Whether feedback weights were active or pure baseline (cold-start indicator)

---

## 6. Persona-pick UI

```
┌─ Match ──────────────────────────────── 87% ─┐
│  Solutions Engineer (pre-sales)        87% ✓ │
│  ───────────────                             │
│  AI Solutions Architect                71%   │
│  Technical Writer                      64%   │
│                                              │
│  [ Apply with Solutions Engineer (pre-sales) ]│
│  [ Why? ]   [ Get LLM analysis ]   [ 👍 👎 ] │
└──────────────────────────────────────────────┘
```

- The 87%-row is the active persona for this vacancy. Clicking another row promotes it (logs `persona_picked`).
- "Apply with X" — when clicked, logs `applied_with_persona`, then opens the LinkedIn apply modal (whatever Tally already does for click-through). Auto-detect of LinkedIn Easy Apply (Phase A leftover A5) eventually fires the same telemetry.
- 👍/👎 — logs feedback events.
- "Get LLM analysis" — kept from Phase 5; routes through the BYO LLM backend dropdown (whichever the user picked).

---

## 7. BYO LLM backends

Inherits the `chrome_plugin/llm_backends.py` module from Phase 5 (Gemini / Claude Desktop via MCP / Ollama / OpenAI / none). The settings dropdown is the same; what's new in Phase 6 is **two LLM-using paths route through it**:

1. **"Get LLM analysis"** button — same as in Phase 5; produces qualitative narrative.
2. **Cover-letter draft** (Slice 6.5 stretch) — when user clicks "Draft cover letter" on a top-scoring vacancy, builds a prompt from `(active_persona, vacancy)` and routes through the picked backend. Result opens in a modal the user can edit and copy.

If Phase 5 ships first, Phase 6 inherits the dropdown. If Phase 6 ships first, the dropdown lives here. Either order is fine.

---

## 8. Slicing breakdown

### Slice 6.1 — Multi-tenant data migration (~½ day)
- **Files:** `chrome_plugin/config.py` (`user_dir`, optional `user_id` on every helper), `chrome_plugin/api_server.py` (`?user_id=…` query param defaulting to env), `scripts/migrate_to_user_dirs.py` (one-off, idempotent).
- **Tests:** round-trip migration, idempotent re-run, env override `JOB_MINER_USER_ID=alt` writes to a different subtree.
- **User-visible:** none directly. All existing flows still work; data lives one level deeper now.

### Slice 6.2 — Persona schema + CRUD (~1 day)
- **Files:** `chrome_plugin/personas.py` (load/save/validate, Obsidian↔YAML sync), `api_server.py` (`GET/POST/PUT/DELETE /api/personas`), `chrome_plugin/sidebar.html` + `sidebar.js` (Settings panel "Personas" section: list + Add/Edit/Delete + form for atoms/narrative/proof_points).
- **Tests:** validation rejects unknown atoms, name uniqueness, atomic writes (temp + rename).
- **User-visible:** can manage 1–N personas in the gear panel; existing single profile auto-migrates to a `main` persona on first load.

### Slice 6.3 — Multi-persona scoring in sidebar (~1 day)
- **Files:** `chrome_plugin/scoring.py` (extend to score per persona; return ordered list), `chrome_plugin/scoring_search.py` (same), `sidebar.html`/`.js` (Match section renders multi-persona list, supports clicking to promote).
- **Tests:** scoring shape (list of N), tie-breaking, single-persona back-compat (legacy data/profile.yml only personality).
- **User-visible:** sidebar Match shows scores against every persona, sorted; click to switch active.

### Slice 6.4 — Telemetry + feedback-aware reweighting (~1 day)
- **Files:** `config.py` (`append_telemetry`, `load_telemetry`), `api_server.py` (`POST /api/telemetry`, `POST /api/scoring-weights/rebuild`), `scoring_search.py` (read `scoring_weights.json`, apply multiplier), `sidebar.html`/`.js` (👍/👎 buttons, "Apply with X" button, "Why this score?" disclosure, "Rebuild weights" in settings).
- **Tests:** cold-start (no weights), reweighting math (clipped, bounded), telemetry append non-blocking, atomic weight-file writes.
- **User-visible:** thumbs-up/down + Apply-with-X buttons; "Why?" pop-over; weights kick in after 50 events.

### Slice 6.5 — Cover-letter draft (stretch, ~1 day)
- **Files:** `chrome_plugin/cover_letter.py` (new; prompt builder + parser), `api_server.py` (`POST /api/cover-letter/{job_id}` with `persona_slug` body), `sidebar.html`/`.js` (modal with editable draft).
- **Tests:** prompt shape, fallback when backend offline, modal-open→close→re-open preserves draft.
- **User-visible:** "Draft cover letter" button on top-scoring vacancies; result in a modal; backend honoured by current scoring engine setting.

---

## 9. Migration plan

- **`data/profile.yml` → `obsidian_vault/Personas/main.md` + `data/users/default/personas/main.yml`** on first read after Phase 6 ships. Idempotent. Source profile.yml stays in place as a backup until the user manually deletes it.
- **`data/events.jsonl`, `data/scores.jsonl`, `data/settings.json`** → `data/users/default/*` on first load. Migration helper marks completion via `data/.migration_v6` so re-runs are no-ops.
- **No vault structure changes** beyond adding `obsidian_vault/Personas/`. Existing Vacancies/Companies/Skills directories untouched.
- **Backward-compat for `JOB_MINER_DATA_DIR`**: env override still works; `users/default/` lives inside whatever DATA_DIR points to.

---

## 10. Open questions / risks

1. **How does the user pick a persona quickly?** Sidebar dropdown is fine for ≤3 personas; a list-card pattern handles more. Don't optimize for >5 — if a user has that many, the curation is already off-rails.
2. **Cold-start telemetry threshold.** 50 events is a guess. If reweighting feels random until 200, raise it. Track in open issues post-6.4.
3. **Cover-letter privacy.** LLM sees the full persona narrative + JD. Backend choice matters (Ollama = local, OpenAI = cloud). Document this clearly in the Cover-letter modal: "This will be sent to {Gemini API | Claude Desktop | …}".
4. **Spurious atom→outcome correlations** in small samples. Mitigation: clip multiplier to [0.5, 1.8]; never let one feedback override a strong baseline IDF.
5. **User_id provisioning for Phase 7.** v1 hardcodes `default`. Phase 7 needs to migrate `default` → real auth-derived user_id. Plan: keep `migrate_to_user_dirs.py` reusable with a `--from default --to <new-uid>` mode.
6. **Persona drift over time.** Skills atoms in personas re-link to Phase 5 ontology automatically when ontology rebuilds — slugs are stable, atom graph metadata changes underneath. Document this.
7. **Multi-persona scoring perf.** N personas × M vacancies = N*M scores. With 5 personas and a list of 25 cards, that's 125 score computations per list-page render. The Phase 5 search engine is fast (<5ms per call); should be fine. If it isn't, cache per-(vacancy_atom_set, persona_atom_set) hashes.
8. **Telemetry retention.** `telemetry.jsonl` grows indefinitely. After 6 months: rotate to a `_archive` file with a header summary. Cron-driven.
