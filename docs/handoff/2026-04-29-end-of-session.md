# Handoff — 2026-04-29

This document is written for the **next Claude session** picking up this project cold. Read it first; everything else flows from here.

---

## Where things stand (sync point)

- **Branch:** `main` at `d22dd4e docs: add legal posture + technical advisory`
- **Origin:** `Morty2049/multi-agent-data-miner`, fully synced
- **Tests:** 77 pytest cases, all green (`venv/bin/pytest tests/ -q`)
- **Vault:** 1576+ vacancies, 528 companies in `obsidian_vault/`
- **PR #1:** merged 2026-04-28 (Phase 3 match scoring + UX/autopilot fixes + Phase 4/6 plans)
- **Worktree:** none active. The previous worktree at `.claude/worktrees/ecstatic-cori-275976/` was deleted post-merge. Operate in the main repo at `/Users/leks/codeRepo/my_projects/multi-agent-data-miner` directly, or create a new worktree if the user asks.

## Today's commits in main (newest first)

| SHA | What |
|---|---|
| `d22dd4e` | `docs/legal-posture.md` — proto-CRM framing, technical defenses, per-phase risk, pre-Phase-7 checklist, disclaimer |
| `ae8321f` | `scripts/run-server.sh` + `tests/test_extension_layout.py` — regression for the recurring `__pycache__` bug class |
| `0015504` | Renamed `phase-6-skill-ontology.md` → `phase-5-skill-library.md`; added `phase-6-resume-matching.md` + `phase-7-public-deployment.md`; added BYO-LLM section to Phase 5; cross-refs updated |

---

## Roadmap (post-renumber, locked 2026-04-28)

| Phase | What | Plan doc | Status |
|---|---|---|---|
| 1 | Sidebar shell + Tally rebrand | — | ✅ done |
| A | Event log + Timeline + Company History | — | ✅ done |
| 3 | Match scoring (Gemini-Flash) | `docs/adr/0002-match-scoring.md` | ✅ done (PR #1) |
| **4** | Calendar (`event_at` + Upcoming + .ics) | `docs/plans/phase-4-calendar.md` | 📋 planned |
| **5** | Skill library + BYO LLM (Gemini / Claude MCP / Ollama / OpenAI) | `docs/plans/phase-5-skill-library.md` | 📋 planned |
| **6** | Resume matching + multi-tenant data layout + telemetry | `docs/plans/phase-6-resume-matching.md` | 📋 planned |
| **7** | Public deployment (Fly.io) + opt-in multiplayer | `docs/plans/phase-7-public-deployment.md` | 📋 planned, gated on 4/5/6 stability + lawyer |

## Phase 5/6/7 framing — important to internalise

- **BYO LLM is NOT its own phase.** It lives as a section inside Phase 5 (used in skill extraction) and inherits into Phase 6 (used in scoring + cover-letter draft). Four backends behind one seam: Gemini API / Claude Desktop via MCP / Ollama / OpenAI / none. See `docs/plans/phase-5-skill-library.md` §10.
- **The original "Phase 5: multiplayer backend" is folded into Phase 7** (public deployment). Multiplayer features (vacancy fingerprint dedup, community ontology contributions) are opt-in, k-anonymity-gated, and only make sense once the service is hosted.
- **Phase 7 is the legal cliff**, not earlier phases. Personal localhost use → very low risk. Hosted multi-user → hiQ-shaped. See `docs/legal-posture.md` for the full posture.
- **Tally is a proto-CRM and skill-development reflection tool** — never market or describe it as a scraper. The DOM-reading is implementation detail; the product is "smart notebook for your own job-search."

---

## What to do when the user re-engages

The user said "сворачиваемся" (closing for now) at the end of this session. They will reopen with a specific signal. Map their wording to action:

| User says | Do this |
|---|---|
| `next` or `phase 4` or "calendar" | Start **Slice 4.1** (event_at schema + back-compat) per `docs/plans/phase-4-calendar.md` §6. ~½ day. New branch, PR pattern. |
| `phase 5` or "skill library" | Start **Slice 5.1** — empirical pre-flight on the vault. Half-day notebook, deterministic decision gate (≥60% profile-skill roundtrip + ≥70% top-200 cluster coherence). Output: `docs/research/skill-extraction-feasibility.md`. **No infrastructure shipped in 5.1.** |
| `phase 6` | Don't start without Phase 5 done; the multi-persona scoring relies on the ontology. If user insists, push back gently. |
| `phase 7` | Push back firmly — gated on 4/5/6 stability AND the pre-Phase-7 checklist (`docs/legal-posture.md` §"Pre-Phase-7 checklist"). |
| Bug report | **TDD pattern.** If the bug class has been reported ≥2 times, write the failing test FIRST, then fix until green. Reference: `tests/test_extension_layout.py` for the pattern (catches `_*`-prefixed paths in `chrome_plugin/`, locks in the recurring `__pycache__` bug). The user explicitly invoked this rule on 2026-04-29 — see `memory/feedback_working_style.md`. |
| `push` | Push to origin/main. Otherwise NEVER push. |
| `merge` | `--no-ff` merge of feature branch into local main as a bubble. Don't squash. |
| `BYO LLM` or `MCP` | Reference Phase 5 §10 + Phase 6 §7. The seam already exists at `chrome_plugin/scoring.py::_default_llm`. Don't write a separate phase for it. |

## Operational notes the next agent will need

- **Server starts via** `./scripts/run-server.sh` (sets `PYTHONDONTWRITEBYTECODE=1` to prevent the recurring `__pycache__` Chrome-load bug). Bare `uvicorn` works but creates the bug; the regression test will fail if you forget.
- **Symlink:** `~/Desktop/tally-dev-plugin → /Users/leks/codeRepo/my_projects/multi-agent-data-miner/chrome_plugin`. Chrome's "Load unpacked" should point at `~/Desktop/tally-dev-plugin` (survives future worktree restructuring) OR directly at `chrome_plugin/`. After any code change in `chrome_plugin/`, user reloads in `chrome://extensions` then F5's the LinkedIn tab.
- **Tests run via** `venv/bin/pytest tests/ -q`. `pytest` standalone won't work — venv is required.
- **GEMINI_API_KEY** in env enables Phase 3 scoring; without it, the score endpoint returns `{"error": "scoring_unavailable"}` and everything else still works.
- **Stale worktrees:** `git worktree list` shows several leftover worktrees from prior sessions (`amazing-elbakyan`, `great-hamilton-fd5211`, two emdash worktrees). Don't touch them unless the user asks.

## Working-style reminders (from memory)

The next agent has these auto-loaded from `memory/feedback_working_style.md`, but worth re-stating:

1. **Auto mode is the default.** Don't ask "should I…" three times — pick the safer default and proceed.
2. **Russian for chat, English for code/commits/docs.** Mirror the user's language mix.
3. **Never push without an explicit "push" / "запушь".**
4. **Recurring bugs need regression tests, not promises** (added 2026-04-29). Pattern-class tests beat instance-tests.
5. **Frustration → diagnosis mode.** If the user says "бесит" or "фрустрирую," drop roadmaps and switch to numbered diagnostic steps.
6. **Don't dump full code diffs into chat** — point at `file_path:line_number` with a one-line summary.
7. **Don't repeat questions the user already answered.** Cache answers in conversation.
8. **Use `--no-ff` merges so feature work shows as a bubble.** History cleanliness matters to the user.

---

## Open questions / loose ends (NOT urgent)

1. **Phase A leftovers** — A3 Applications panel (📋 header icon with status grid), A5 Easy Apply auto-detect → POST event. Not blocking; surface them only if the user mentions Applications view.
2. **Devoteam company-name aliases** — vault has 40 `[[Devoteam]]` + 4 `[[Devoteam | Cyber Trust]]` + a couple variants. `/api/company-history` does exact-match. Phase 6 ontology should handle aliases naturally; track there, not as a standalone task.
3. **Stale legacy data in `data/`** — `skills_backup_*` directories (1987 + 1974 files), `skills_graph.json` (1MB), `skills_synonyms.json` from old `skills_miner_adk` work. Phase 5 plan treats `obsidian_vault/Skills/` (2016 legacy markdown) as a curation seed. The flat-JSON files in `data/` are not currently referenced; safe to ignore until Phase 5 runs.
4. **Match-score crowdsourcing** — discussed for Phase 7 but explicitly deferred (k-anonymity floor of 20 needed, only viable with enough users). Don't ship in Phase 7 v1.
5. **Cover-letter generation** — Slice 6.5 stretch goal in Phase 6 plan. Behind the BYO LLM seam. Stretch, not must-have.
6. **`__pycache__` cleanup is now regression-tested.** Don't keep deleting it manually — `tests/test_extension_layout.py` will fail if it sneaks back in.

---

## Files the next agent should read (in this order, ~15 min)

1. **This handoff doc** — current file
2. **`memory/MEMORY.md`** + linked memory files — auto-loaded but worth scanning to confirm freshness
3. **`docs/legal-posture.md`** — framing for any user/contributor-facing communication
4. **`docs/plans/phase-4-calendar.md`** — most likely next development target if the user says `next`
5. **`docs/plans/phase-5-skill-library.md`** §10 (BYO LLM) — important architectural decision applicable to Phase 6 too
6. **`docs/adr/0002-match-scoring.md`** — current scoring system design + why it's getting demoted to opt-in in Phase 5

For deeper context: `chrome_plugin/content.js` (~1400 lines) is the heart of the Chrome extension. `chrome_plugin/api_server.py` is the FastAPI backend. `chrome_plugin/scoring.py` has the LLM seam.

---

## Last thing

The user is **mid-active** on this project. They scrape ~300-400 vacancies/day with the autopilot in Stealth preset. Don't break the flow. If you need to ship a fix, the reload-cycle is reload extension + F5 LinkedIn tab — they've done this dozens of times today, but it's still friction.

Match their pace. Action over planning. Keep responses tight. Russian for chat, English for code.
