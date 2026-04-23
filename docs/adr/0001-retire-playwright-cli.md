# ADR 0001 — Retire the Playwright collect_search CLI

- **Status:** Accepted
- **Date:** 2026-04-23
- **Decision-makers:** Aleksei Petrov
- **Supersedes:** —
- **Superseded by:** —

## Context

Earlier in the project's life, vacancy collection happened through a
command-line pipeline built on Playwright:

```
collect_search.py → queue.json → parse_job.py → obsidian_vault/Vacancies/
```

This ran headless Chrome against LinkedIn with a CDP-attached profile,
paginated through `/jobs/search/*` in large batches, and dumped URLs
into a queue that another script later scraped.

During the Phase 1 Chrome-extension rework the CLI was stripped away in
commit [`d2a9b2f`](https://github.com/…) (`chore: retire legacy
Playwright CLI, simplify config to plugin MVP`). Scraping now happens
**inside the user's own logged-in Chrome tab** via the Tally extension's
content script and backend `/api/parse` endpoint.

Resolving this ADR came up today because `git stash pop` on `main`
attempted to restore a stashed experimental addition to
`collect_search.py` (a `--start-page` resume flag) and collided with
the already-deleted file, leaving `main` in a "deleted by us, updated
by them" unmerged state.

## Decision

The Playwright CLI is **retired permanently**. The stashed
`--start-page` experiment will **not** be restored. The last
working-tree copy of `collect_search.py` (including the stashed
modifications) is archived at `.legacy/collect_search.py` as a
reference snapshot, outside git, for the one-in-a-hundred case where
someone needs to review what the old code did.

The unmerged state on `main` is resolved by:

```
git rm collect_search.py        # unstage the "updated by them" entry
rm .git/AUTO_MERGE              # orphaned auto-merge artefact
git stash drop stash@{0}        # abandon the pre-Phase-A experiment
```

## Rationale

**Why remove rather than keep as a fallback:**

- **Chrome extension covers every scenario** the CLI used to cover.
  Autopilot walks `/jobs/search/*` via `history.pushState` pagination
  with randomised delays (see `chrome_plugin/content.js::processCurrentPage`),
  honours a per-run-configurable daily cap (`POST /api/settings/preset/*`),
  and auto-stops on LinkedIn safety pages. The `--start-page` flag
  the stash added is functionally equivalent to LinkedIn's own
  `?start=N` URL parameter, which the extension already respects.
- **Zero active dependency.** `grep -rn "collect_search"
  chrome_plugin/ config.py tests/ legacy/` returns nothing. No
  import, no shell-out, no doc reference outside this ADR.
- **Bigger attack surface.** The CLI required CDP on port 9222 and
  persistent browser profiles under `linkedin_session_*/` —
  session files that were routinely left on disk. The extension
  uses only the already-open tab with no new filesystem footprint.
- **Session cost.** Running the CLI meant keeping a separate Chrome
  instance in debugging mode; every run risked a captcha that broke
  the whole batch. Moving into the user's real tab eliminates this.

**Why archive locally instead of deleting outright:**

If a future requirement (a team CLI for headless CI, say) resurrects
the Playwright approach, having the last known-good source with the
`--start-page` experiment intact saves an archaeology session through
`git reflog`. `.legacy/` is gitignored so the archive never pollutes
the repo, but it survives on the developer machine.

## Consequences

**Positive**

- `main`'s working tree is clean; no more "deleted by us" paper-cut.
- Only one code path for scraping (extension) → easier to reason
  about rate limits, session isolation, and ban-safety.
- `legacy/` (tracked) still holds the **offline skills-enrichment**
  scripts (LLM miner, dedup, graph rebuild). Those stay — they
  operate on the already-collected vault, not on LinkedIn.
- The `.legacy/` (gitignored) archive makes the "don't lose working
  code" principle explicit without inventing a new branch-graveyard.

**Negative / accepted trade-offs**

- No headless / unattended scraping. Anyone wanting to run collection
  while away from their machine loses that option.
- Any reviewer reading old `git log` will see references to
  `collect_search.py` and need to consult this ADR to understand
  why it's gone.

## Notes

- Archive path: `.legacy/collect_search.py` + `.legacy/collect_search.README.txt`
  (both outside git).
- `.gitignore` updated to include `/.legacy/` so the convention is
  portable to any future contributor.
- Earlier PHP-era roadmap files (`ROADMAP.md`, `.gsd-specs/`) had
  already been cleaned up in commit `df7a3c0`; this ADR closes out
  the last loose thread from that same cleanup wave.
