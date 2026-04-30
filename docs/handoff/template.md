# Handoff template — copy this for each session-boundary

Per the working-mode locked in 2026-04-29, each session = one slice or one bounded conversation. At the end, write a handoff so the next session can pick up cold without reading the chat.

**How to use:**
1. Copy this file to `docs/handoff/YYYY-MM-DD-<slug>.md` (e.g. `2026-05-02-slice-4.1-event-at.md`).
2. Fill the sections below. Delete sections that don't apply (the "In flight" and "For next session" blocks are optional).
3. **Skip the handoff entirely** if the session was trivial (small bug fix, doc typo, single-commit slice with a clear commit message). The commit message + memory + plan-docs are enough.
4. **Write the longer free-form variant** (like `2026-04-29-end-of-session.md`) only when the session changes the working agreement, sets a new architectural direction, or wraps up a multi-day phase. Once a quarter at most.

Don't pad. The next session reads this in < 2 minutes.

---

# Handoff — YYYY-MM-DD · <slice or topic>

**Branch:** `<branch>` at `<short-sha>` · **Tests:** N passed · **Pushed:** <yes / no / PR #N>

## What landed

- `<sha>` — one-line summary of each commit. Point at the file:line if it matters.
- (Or just: "see PR #N" if commits are described well there.)

## In flight (delete if clean)

- Anything uncommitted, work-in-progress, or waiting on a decision.
- A failing test you couldn't fix yet — what it tests, why it fails, where to look.
- A spike branch that didn't merge — link + one-line "why parked."

## For the next session (delete if next can pick up from memory + plans alone)

- Anything non-obvious that's NOT in `MEMORY.md`, `docs/plans/*`, the PR description, or commit messages.
- New gotchas the user surfaced that need a regression test (link the test if you wrote one).
- Updated assumptions: "X used to be true, now it's Y" — especially if memory references the old state.

## Branch policy

- If session ends mid-slice on an unmerged branch: state explicitly "main untouched; don't merge or push <branch> until I confirm."
- If session ended on a merged PR: just say "main is at <sha>, all work pushed."
