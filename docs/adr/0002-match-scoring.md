# ADR 0002 — Phase 3 LLM match-scoring

- **Status:** Accepted
- **Date:** 2026-04-26
- **Decision-makers:** Aleksei Petrov
- **Supersedes:** —
- **Superseded by:** —

## Context

Phase 3 added LLM-driven match scoring per vacancy so the user can
prioritise applications and dim noisy listings. Earlier phases settled
the architecture (extension → FastAPI → Obsidian vault); this ADR
covers the slice that lives between an already-saved JD and the
sidebar's Match section.

Four things needed picking:

1. Which model + provider to call.
2. Where the prompt lives (and what data feeds it).
3. What the user actually sees on the LinkedIn list and detail pages.
4. What the user can tune without editing code.

The rest of the pipeline (parse, save, Obsidian write) was already
stable, so the surface area of this decision is narrow on purpose:
score one JD, cache the result, reflect it in the UI.

## Decision

Four sub-decisions, each owning a different layer.

### 1. Engine: Gemini-Flash via lazy import

The scoring engine lives in `chrome_plugin/scoring.py`. The public
entry point is `score_vacancy(profile, vacancy, *, llm=None)` — the
`llm` kwarg is a callable, so tests inject a fake LLM and never hit
the network.

`_default_llm` lazy-imports `google.genai` so a missing dep does not
break unrelated routes. The `score_job` wrapper in
`chrome_plugin/api_server.py` catches `ModuleNotFoundError` /
`ImportError` and returns `{"error": "scoring_unavailable"}` with
HTTP 200, instead of letting a 500 reach the extension.

The JD description is truncated to `_MAX_DESCRIPTION_CHARS = 3000`
before the call. The system prompt is passed via
`system_instruction=` only — never concatenated into the user turn.
Commit `501258b` fixed an earlier version that duplicated the prompt
into both slots.

### 2. Prompt is profile-derived, not hardcoded

The scoring prompt is generated from
`profile.narrative.superpowers` and `profile.narrative.proof_points`,
not a string literal of skills. This is what makes the same
`scoring.py` reusable when another user imports their own
`data/profile.yml`.

The first implementation hardcoded "Python, FastAPI, …" into the
prompt body. Code review caught it and commit `501258b` reworked it
to read from the profile object. The engine has no opinion about
what skills matter — that's the profile's job.

### 3. Three user-visible knobs

That is the entire surface area exposed to the user; everything else
is implementation detail.

- **`GEMINI_API_KEY`** env var — auth lives outside the vault on
  purpose. Secrets do not belong in `data/settings.json`, which is
  user-editable and may end up in screenshots / shared tabs.
- **Autopilot preset** (Stealth / Regular / Fast) — each preset
  bundles `match_threshold` alongside the autopilot delays
  (85 / 80 / 70 respectively). Picking "Fast" relaxes the threshold
  because fast scrubbing implies the user wants more cards visible
  per page.
- **Match threshold slider** (0–100, step 5) — overrides the
  preset's threshold for users who want fine control. Stored in
  `data/settings.json`. `effective_threshold()` in
  `chrome_plugin/config.py` resolves preset → override.

### 4. Below-threshold cards dim, not hide

Cards under threshold render at opacity 0.55 with a grey badge
instead of being filtered out of the DOM. The class
`tally-card-below-threshold` lives on the LinkedIn card; on hover it
returns to opacity 1 so the user can still read the title and act on
it. Hiding would feel like Tally was lying about LinkedIn's results;
dimming preserves visibility while pushing the eye to the strong
matches.

## Rationale

**Why Gemini-Flash specifically.** Per-call cost is roughly
$0.0003 at our prompt size, JSON-mode output is reliable enough that
we can parse with `json.loads` without retries, and the user already
has a Google API-key flow from earlier projects. The `llm` callable
seam in `score_vacancy` means we are not locked in — swapping to
Claude or a local model is a one-function change.

**Why per-vacancy on demand, not bulk batch.** Scoring runs only
when the sidebar's Match section is active, and the result is cached
in `data/scores.jsonl` so a re-view of the same JD is free. Bulk
scoring all 500 saved JDs upfront would cost $5+ for a feature the
user might decide they do not want, and would burn the daily quota
on listings the user will never click. Lazy is cheaper and matches
the rest of the extension's "act on the tab in front of you" model.

**Why threshold instead of binary "good match".** Users disagree on
what counts as a match, and the same user wants a different
threshold depending on day, mood, and how desperate they are this
week. Treating the cutoff as a slider makes it a UI affordance the
user can move; treating it as a hidden hyperparameter would force a
code edit (or worse, a prompt edit) every time the user wanted to
see more / fewer cards.

**Why dim instead of hide.** Trust and reversibility. The user
already lost trust in LinkedIn's own ranking; if Tally also removes
results, it becomes another opaque filter. Dimming says "we have an
opinion, here it is, but the underlying list is intact" — and a
hover unsticks the opinion in one gesture.

## Consequences

**Positive**

- Per-vacancy cost ≈ $0.0003 and latency ≈ 2–3s; well below the
  threshold where users notice friction in the sidebar.
- The scoring engine is fully testable without hitting Gemini —
  tests pass a fake `llm` callable and assert on the prompt + the
  JSON-parsing path.
- The threshold UI lets users tune visibility without knowing
  anything about LLMs, prompts, or quotas.

**Negative / accepted trade-offs**

- A missing `GEMINI_API_KEY` silently degrades to
  `{"error": "scoring_unavailable"}` instead of a hard error. We
  accept this because it is strictly better than crashing the parse
  path, but it does mean a user can run the extension for days
  before realising scoring never turned on. The Phase 3 README
  update (separate task) documents the env-var requirement.
- Anyone reading commit history will see scoring code referencing
  `google.genai` and may assume a hard dependency; the lazy import
  + `score_job` envelope is the only thing that makes it optional.

**Future-affecting**

- When Phase 5 adds skill-extraction LLM calls, that pipeline will
  reuse the same lazy-import + LLM-seam pattern from `scoring.py`.
- The score cache in `data/scores.jsonl` will likely grow to include
  skill-extraction output. This ADR does **not** pre-commit to that
  schema — Phase 5 owns its own cache contract.

## Implementation references

- `chrome_plugin/scoring.py` — engine + prompt construction
- `chrome_plugin/api_server.py::score_job` — error envelope wrapper
- `chrome_plugin/config.py::effective_threshold` — preset → override
  resolution
- `chrome_plugin/sidebar.js` (Match section render) and
  `chrome_plugin/sidebar.css` (`.tally-match-pct` tier colours)
- `chrome_plugin/content.js::markScoreBadges` — list-page badge
  decoration + `tally-card-below-threshold` class
- Commits: `cecd82f`, `f4f42af`, `501258b`, `1ee57b0`, `148b60d`,
  `40b71da`, `59cfbc8`, `e4f26ee`
