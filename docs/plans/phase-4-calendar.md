# Phase 4 — Calendar integration

**Status:** Draft (planning only — not yet greenlit)
**Predecessor:** Phase 2 event timeline (`data/events.jsonl`)
**Author/owner:** Aleksei Petrov
**Date:** 2026-04-26

## 1. Goals & non-goals

### Goals
- Attach a **scheduled date/time** to events whose kind is time-bound (`interview`, `screening`, `test_task`).
- **Surface upcoming events** so a working candidate juggling 8–15 applications cannot miss an interview that's only logged in the timeline.
- **Export to ICS** so the user can subscribe in Calendar.app / Google Calendar / Fantastical and let their existing notification stack do the reminding.
- Keep the data shape **append-only and backward-compatible** — Phase 2 events from before Phase 4 ships must continue to load and render without migration.

### Non-goals (deferred to later phases)
- Cross-device sync (no multi-host backend; localhost only).
- **Calendar pull** (Google / iCloud / Outlook OAuth) — push to ICS only.
- Recurring events / multi-stage interview series as a single object — each round is its own event.
- Reminders / push notifications from the extension itself — we delegate to the calendar app.
- Editing/deleting scheduled events from the sidebar — Phase 4 is append-only (consistent with Phase 2). A wrong date is corrected by adding a new event with the same kind.
- Timezone selection UI — capture the browser's local tz, store ISO-8601 with offset, render in user's local tz.

---

## 2. Schema decision

**Decision: Option A — add an optional `event_at` field to the event record.**

The current schema already separates "when this row was written" (`at`) from any business-meaning timestamp. `event_at` becomes "when the scheduled thing happens." Both are ISO-8601 strings.

```jsonc
// Phase 2 (still valid)
{"job_id": "4389...", "kind": "applied", "at": "2026-04-22T09:30:00+00:00",
 "note": "Easy Apply"}

// Phase 4 (new)
{"job_id": "4389...", "kind": "interview", "at": "2026-04-27T18:11:00+00:00",
 "event_at": "2026-04-30T14:00:00+02:00",
 "note": "Round 1 w/ Maria, hiring manager"}
```

### Why A over B and C
- **Against B (`note` prefix `@2026-04-30T14:00 …`):** loses structure the moment a user writes a note that happens to start with `@`, and the `.ics` export would have to re-parse free text. Fragile.
- **Against C (separate `data/scheduled.jsonl`):** introduces a join, doubles the durability surface, and offers no benefit since events are append-only and small. The file would always be a strict subset of `events.jsonl` keyed by event identity — but events have no stable id, so we'd invent one.
- **Why A wins:** the JSONL format already tolerates extra keys (`load_events` does `json.loads` per line, no strict schema), so old rows with no `event_at` are read unchanged. The only validation change is one extra `isinstance` check in `_validate_event`. The `.ics` export is a trivial filter (`e.get("event_at")` truthy and in the future).

### Validation rule (added to `_validate_event`)
- `event_at`, if present, must be a string parseable as ISO-8601 with offset.
- `event_at` is **required** when `kind in {"interview", "screening", "test_task"}` only at the **API boundary** (`/api/events`), **not** in `config.append_event`. Rationale: the bulk-migration helper and the auto-stamped "saved" event must keep working without dates; only the user-driven Add-event path enforces the requirement.

---

## 3. UI decision

**Decision: conditional date picker — appears only when kind ∈ {interview, screening, test_task}.**

A `test_task` deadline is a real calendar event (the user is given "submit by Friday 18:00"), so it qualifies. `applied` does not need a date — `at` already records when the click happened. `note` / `saved` / `rejected` / `ghosted` are after-the-fact records, no date.

### Form sketch (after Phase 4)

```
┌────────────────── Application timeline ──────────── 4 ─┐
│ ● applied        Easy Apply                  Apr 22   │
│ ● screening      Recruiter call w/ Sara      Apr 24   │
│ ● interview      Round 1 — Maria        Wed Apr 30    │
│                                              14:00 ↗  │
│ ● note           Asked about hybrid policy   Apr 26   │
│                                                       │
│ ┌─ Add event ─────────────────────────────────────┐   │
│ │ [ interview  ▾ ] [ Add ]                        │   │
│ │ ┌─ When ──────────────────────────────────────┐ │   │
│ │ │ [ 2026-04-30 ] [ 14:00 ]   ← shown only when│ │   │
│ │ │                              kind ∈ time-set │ │   │
│ │ └──────────────────────────────────────────────┘ │   │
│ │ [ Note (optional)…                            ] │   │
│ └─────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
```

- Uses native `<input type="date">` + `<input type="time">` — no library, matches Tally's "minimal surface" philosophy.
- The picker is rendered always but `display:none` toggled in JS based on the kind dropdown's `change` event. Keeps the DOM stable, avoids form-reflow flicker.
- **Render in timeline:** scheduled events show **two lines** — `interview · Wed Apr 30 14:00` on the kind line, note below. The `↗` glyph hints "this is also in your calendar." A scheduled event whose `event_at` is in the past renders with a muted dot (already passed; mostly historical).

---

## 4. Surfacing decision

**Decision for MVP: replace the "Today" stat card with an "Upcoming" card, plus a new compact "Upcoming" section above the timeline.**

```
┌─ Vacancies ─┐ ┌─ Companies ─┐ ┌─ Upcoming ──┐
│     127     │ │     63      │ │  3 in 7d    │
└─────────────┘ └─────────────┘ └─────────────┘

┌── Upcoming (3) ──────────────────────────────┐
│ Wed Apr 30  14:00  Devoteam · interview    ↗ │
│ Fri May 02  10:30  Inetum · screening      ↗ │
│ Mon May 05  18:00  Thales · test_task      ↗ │
└──────────────────────────────────────────────┘
```

### Why this and not the alternatives
- **Vs. coloured pills on LinkedIn list cards:** that needs the content script to query `/api/events?upcoming=…` on every list-render and survive LinkedIn's virtualisation. Doable, but the user only sees it while on `/jobs/search/*`. Phase 4 should still warn when the user is on a vacancy page or a company page or just opened the sidebar to triage.
- **Vs. dedicated "Upcoming" page/route:** the sidebar is already cramped; adding a navigation hierarchy is Phase 7 / "saved searches" territory.
- **Vs. only the stat card:** a single number is too coy. The user needs to see *which interview is tomorrow* without clicking. The compact list under the cards is three lines max (we cap at the next 3, with a "more →" footer if `count > 3`) and only renders if any future event exists.
- **The "Today" card is replaceable without loss:** "parsed today / cap" is already shown in the rate banner, and the autopilot button area surfaces remaining capacity. No information lost.

### Where the data comes from
- New endpoint `GET /api/events/upcoming?days=7` returning events with `event_at` between now and now+7d, sorted ascending. Wraps the existing `load_events()`. The `dashboard()` endpoint also returns a top-3 sample inline so the sidebar's existing single-fetch dashboard pull keeps the badge fresh without a second round-trip.

### Why the LinkedIn-list pill can wait
It's high-effort (LinkedIn DOM is hostile, virtualised, and changes monthly) and lower-value once the ICS feed lands — the user's calendar app on their phone will buzz them about Maria's interview regardless of which website they happen to be on at 13:55.

---

## 5. Export decision

**Decision: single `GET /api/calendar.ics` endpoint, all future scheduled events, manual subscription via webcal.**

### Endpoint shape
- `GET /api/calendar.ics` → `text/calendar; charset=utf-8`
- No auth (consistent with the rest of the localhost API).
- Returns every event with `event_at` ≥ now-1d (one-day lookback so the morning interview that's 30 min in the past still shows during a same-day glance).
- Stable `UID` per event: `tally-{job_id}-{kind}-{event_at-epoch}@localhost` — deterministic so the calendar app dedupes and updates rather than spawning duplicates when the user edits.
- `SUMMARY = "{Company} · {kind}"`, `DESCRIPTION = note`, `URL = https://www.linkedin.com/jobs/view/{job_id}/`.
- `DURATION = 60M` for `interview` and `screening`, all-day `VALUE=DATE` for `test_task` (deadlines, not meetings).

### Sample output
```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Tally//Phase 4//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:Tally — interviews & deadlines
BEGIN:VEVENT
UID:tally-4389597827-interview-1745892000@localhost
DTSTAMP:20260427T181100Z
DTSTART:20260430T120000Z
DTEND:20260430T130000Z
SUMMARY:Devoteam · interview
DESCRIPTION:Round 1 w/ Maria\, hiring manager
URL:https://www.linkedin.com/jobs/view/4389597827/
END:VEVENT
END:VCALENDAR
```

### Subscription flow (single localhost feed)
1. User clicks "Copy calendar URL" in the sidebar settings → `webcal://localhost:8000/api/calendar.ics` is in clipboard.
2. Calendar.app: `File → New Calendar Subscription → paste`.
3. Refresh interval: every 5 min (Calendar.app's lowest setting; good enough for a working candidate's planning horizon).

### Why single feed, not per-application
Per-application means N feeds for N active vacancies — administrative chore on the user's side, no upside. A single feed colours the whole "Tally" calendar one colour in Calendar.app, which is the right mental model: "things I have committed to in my job search." Per-status feeds (interview-only vs. all) is a Phase-5 concern if the user ever asks.

### Why no auto-subscription
A `webcal://` link click triggers Calendar.app on macOS, but the precise behaviour is OS- and browser-dependent and the value is small. Manual one-time subscription is fine for an MVP that ships to one user. Documenting the URL in the README is sufficient.

---

## 6. Slicing breakdown

### Slice 4.1 — Schema + backend persistence
- **Files touched:**
  - `config.py` — extend `_validate_event` to accept optional `event_at`; update `append_event` to pass it through.
  - `chrome_plugin/api_server.py` — extend `EventRequest` (Pydantic) with `event_at: str | None = None`; enforce required-when-kind-is-time-bound at the API layer only.
  - `tests/test_config.py` — add tests for valid `event_at`, malformed `event_at`, and the back-compat case (Phase-2 row without `event_at` round-trips through `load_events`).
  - `tests/test_api_server.py` — add a POST `/api/events` test for an interview with `event_at` and one for the validation 400.
- **User-visible after this slice:** `curl -X POST /api/events` with an `event_at` payload persists; `GET /api/events?job_id=…` returns it. Sidebar still works as before (no UI changes yet; field rides through silently).

### Slice 4.2 — UI: date picker + timeline rendering
- **Files touched:**
  - `chrome_plugin/sidebar.html` — add date+time inputs inside `tally-add-event`, wrapped in a `tally-event-when` container.
  - `chrome_plugin/sidebar.css` — style the conditional row.
  - `chrome_plugin/sidebar.js` — wire `eventKindSelect`'s `change` to toggle the picker; include `event_at` in the `event.add` postMessage payload; extend `applyTimeline` to render `event_at` line.
  - `chrome_plugin/content.js` — extend the `event.add` handler that currently posts `{kind, note}` to also pass `event_at`.
- **User-visible after this slice:** the user can pick "interview" in the kind dropdown, see a date+time field appear, fill it in, hit Add, and see the scheduled time in the rendered timeline.

### Slice 4.3 — Surfacing: Upcoming widget
- **Files touched:**
  - `chrome_plugin/api_server.py` — add `GET /api/events/upcoming` and extend the `/api/dashboard` response with a `upcoming` list (top 3) + `upcoming_count_7d`.
  - `chrome_plugin/sidebar.html` — replace the "Today" stat card with "Upcoming"; add `tally-upcoming-section` above the timeline.
  - `chrome_plugin/sidebar.js` — render `applyUpcoming(payload.upcoming)`; click on a row navigates the parent tab to `linkedin.com/jobs/view/{job_id}` (consistent with Company History rows).
  - `tests/test_api_server.py` — `/api/events/upcoming` boundary tests (empty, in-range, past-excluded, sort order).
- **User-visible:** opening the sidebar on any LinkedIn page shows "3 in 7d" + the next three scheduled events, ordered by date.

### Slice 4.4 — ICS export
- **Files touched:**
  - `chrome_plugin/api_server.py` — `GET /api/calendar.ics` returning `text/calendar`. Use the stdlib only — hand-roll the ~30 lines of ICS, no `icalendar` dependency. The format is small and stable.
  - `chrome_plugin/sidebar.html` + `sidebar.js` — add a "Copy calendar URL" button + helper text in the settings panel.
  - `README.md` — add a "Subscribe to your Tally calendar" sub-section.
  - `tests/test_api_server.py` — golden-string test on the ICS output for one synthetic event.
- **User-visible:** user copies `webcal://localhost:8000/api/calendar.ics`, pastes into Calendar.app, and 30 seconds later their interviews appear there with reminders firing through their normal calendar pipeline.

---

## 7. Migration plan

**No migration is performed.** Existing Phase-2 rows in `events.jsonl` have no `event_at` field; after Phase 4 they continue to have no `event_at` field, and that's correct — those events were either (a) past tense (`applied`, `saved`) where `at` is already the right semantic, or (b) `interview`/`screening`/`test_task` rows the user logged after the fact, where the user *chose* not to record a forward date because the event already happened.

Specifically:
- `load_events` already tolerates extra/missing keys (it just `json.loads` each line).
- The `.ics` export filters on `e.get("event_at")` truthy, so old rows are silently excluded.
- The Upcoming widget filters the same way.
- The timeline renderer shows the kind+note as before for old rows; the `event_at` line simply doesn't render.

**Why not backfill `event_at = at` for old time-bound rows?** Because that would create fictitious calendar entries dated to "when the user clicked Add", not to when the actual interview was. It's worse than no data — it would put a fake interview on the user's calendar two weeks ago.

---

## 8. Open questions / risks

1. **Picker UX on iOS Safari (in case the user opens the sidebar on a phone via remote-debug):** native date+time pickers behave differently. Probably out of scope — the sidebar isn't designed for mobile — but worth noting.
2. **Localhost CORS for ICS:** Calendar.app fetches `webcal://` outside the browser, so CORS isn't an issue, but if any browser-side preview ever wants the feed we need to confirm `text/calendar` doesn't trip the existing wildcard CORS middleware.
3. **Timezone gotcha:** if the user travels and their browser switches tz while a scheduled event already exists, the stored `event_at` (with offset) is still correct — Calendar.app re-renders in the new tz. We should write a single test to lock this in.
4. **`uvicorn --reload` + ICS subscription cache:** Calendar.app caches subscription content for several minutes; during dev the user may be confused by stale data. Worth one line in the README ("if you don't see your event, force-refresh in Calendar → File → Refresh Calendars").
5. **Should `note` be visible in `DESCRIPTION` for screening calls?** The note may contain a recruiter's name and we're now publishing it via a feed. Localhost-only mitigates the leak, but if Phase 7 ever hosts the feed remotely we'll want a "private" toggle on individual events. Punt to Phase 7.
6. **Per-event delete for typos:** Phase 4 stays append-only (consistent with Phase 2) — to fix a wrong date the user adds a new event. If this becomes annoying in practice, a "supersedes" field on later events is a simpler change than introducing tombstones. Track for Phase 7 if user reports it.
