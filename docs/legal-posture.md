# Legal posture & technical advisory

**Status:** Living document. Updated as the project evolves.
**Last updated:** 2026-04-29
**Disclaimer:** This document is engineering reasoning, not legal advice. Consult a qualified lawyer before any public deployment (Phase 7).

---

## What Tally is

**Tally is a proto-CRM and skill-development reflection tool for individual job-seekers.**

It helps a single user:

1. **Maintain a personal pipeline of applications** — like a tiny Salesforce for your own job search. Statuses (`saved` → `applied` → `screening` → `interview` → `offer/rejected/ghosted`), per-application notes, timeline of touches, calendar of upcoming interviews.
2. **Reflect on their own skill profile** — by comparing what the market describes ("vacancies want X, Y, Z") to what they have on their CV, the user gets a deterministic, explainable signal: "you match 7 of 10 listed skills; here are the 3 missing." This is **skill-gap analysis for self-improvement**, not market intelligence for resale.
3. **Iterate on multiple resume personas** (Phase 6) — the user maintains 2-3 versions of their CV (e.g. "Solutions Engineer pre-sales" vs "AI Solutions Architect") and sees which persona scores highest for each opportunity. Output: a clearer self-understanding of how the user is positioned.
4. **Build a personal skill library** (Phase 5) — over time, the atoms the user encounters across vacancies become a personalised ontology, weighted by how the user's own outcomes correlate with each atom. Output: "you should learn Rust before applying to embedded roles," not "here's a market dataset."

Tally is **not**:

- A market-intelligence product. We don't aggregate vacancy data across users to sell or publish.
- A recruiter tool. We don't help recruiters reach candidates.
- A data broker. The vault stays on the user's local disk; even Phase 7 (public deployment) keeps per-user data isolated and encrypted, with cross-user features behind opt-in toggles and k-anonymity floors.
- A LinkedIn API client. We do not reverse-engineer or hit any LinkedIn endpoint that the user's own browser doesn't already render for them.
- A bulk scraper. The pace of the autopilot is human-like (Stealth preset: 20-45s between saves, randomised). The "350-vacancy run" the user did in April 2026 took ~3.5 hours — slower than a determined human reviewer would do it.

The closest analogy: Tally is a **smart notebook** that watches you read job ads and helps you remember which ones you read, what was in them, and what they teach you about your own market position.

---

## Technical posture

These are the design choices that minimise legal exposure. Each is enforced in code; not aspirational.

### What Tally does

- Runs as a Chrome MV3 extension **inside the user's own logged-in browser session**. Same DOM the user is reading. Same network requests Chrome would make to render the page for the user anyway.
- Reads the DOM **after** LinkedIn has rendered it. Parses `innerText` and structured selectors. Stores the parsed result locally.
- Posts JSON to **`http://localhost:8000`** — a FastAPI server running on the user's own machine. No cloud component (until Phase 7, with explicit user consent + auth).
- Saves Markdown files to the user's own **Obsidian vault** on their own disk.
- Honours human-paced delays in the autopilot (`between_saves_min/max` defaults `20000–45000` ms in Stealth, `8000–20000` in Regular, `2000–5000` in Fast; randomised by default).
- Detects LinkedIn safety / captcha / authwall / checkpoint pages (`isOnLinkedInSafetyPage()`) and **stops immediately** — no retry loops that would train detection.

### What Tally does NOT do

- ❌ No headless browsers. No Playwright. No CDP debugging mode. (We retired the legacy Playwright CLI in [`ADR 0001`](adr/0001-retire-playwright-cli.md) — partly for stability, partly because CDP-attached profiles are exactly the fingerprint LinkedIn flags.)
- ❌ No fake accounts. No credential stuffing. No proxy rotation. The user is logged into their own LinkedIn account; that's the only identity Tally ever interacts with.
- ❌ No write-side automation. Tally never likes posts, sends connection requests, sends InMail, applies to jobs, or modifies the user's profile. It only **reads** what's already on screen.
- ❌ No reverse-engineered API calls. We don't hit `voyager-api.linkedin.com` directly. Everything we read is the rendered DOM from the page the user navigated to.
- ❌ No history.pushState patching. Earlier versions monkey-patched `history.pushState` to detect SPA URL changes; that's a fingerprint anti-bot scripts probe for via `history.pushState.toString()`. Removed in commit `83d99bb`. We poll `location.href` every 200ms instead — invisible to fingerprinting.
- ❌ No data aggregation across users. Phase 7 introduces opt-in cross-user features (vacancy fingerprint dedup, community skill ontology), each gated behind k-anonymity floors (≥5 users for dedup, see `docs/plans/phase-7-public-deployment.md` §5). No raw data ever crosses user boundaries.
- ❌ No data resale. Ever. The license should explicitly forbid commercial re-distribution of vault contents.
- ❌ No background scraping. Tally only acts while the user is actively on a LinkedIn tab. No cron, no service worker that ticks while the browser is closed.

### What Tally does that **could** look like scraping (and why it's actually not)

| Surface | Why it might look bad | Why it's actually OK |
|---|---|---|
| Autopilot iterates through 350 cards in 3.5h | Looks like a bot | Human pace; uses the user's own session; same clicks the user would do; user invokes it |
| `markSavedCards` queries DOM every 200ms | Looks like polling | Read-only over rendered DOM; doesn't hit network; same as the user's eyes scanning the list |
| `extractJob` reads `innerText` of the detail panel | "Extracting" sounds bad | The user opened the panel; LinkedIn rendered the text for the user to read; we're taking notes |
| Stores Markdown of vacancies in the user's vault | "Storing scraped data" | Personal note-taking. No different from the user copy-pasting the JD into a Google Doc |
| Phase 7 community ontology | "Aggregation" | Opt-in atoms only (slug + synonyms; no JD text; no user identity); k-anonymity floor of 5; user can revoke contribution at any time |

---

## Risk assessment by phase

| Phase | What ships | Risk to user |
|---|---|---|
| Phases 1, A, 3 (done) | Single-user localhost tool, no cloud | **Very low.** Worst case: LinkedIn flags the account → temporary cooldown. No precedent for a lawsuit against an individual using a personal tool against their own session. |
| Phases 4, 5, 6 (planned) | Still single-user localhost; richer features (calendar, ontology, multi-persona) | **Same as above.** Adds no new ToS exposure — same surface, more local intelligence. |
| **Phase 7 (public deploy)** | Hosted multi-user MVP | **Materially higher.** This is when Tally moves from "Aleksei's notebook" to "a service Aleksei operates that other people use." The hiQ Labs precedent applies here, not in earlier phases. |

The famous LinkedIn lawsuits (hiQ Labs, Mantheos, ProAPIs) were all against **companies that aggregated and resold scraped data**. None were against individuals using personal tools against their own session. None were against open-source projects shipped to install-it-yourself users.

The **legal cliff is Phase 7**, not the current state. Pre-Phase-7 checklist below.

---

## Pre-Phase-7 checklist (must-do before any public deployment)

1. **Lawyer review.** A specialist in tech / data law (preferably with US Computer Fraud and Abuse Act + EU DSA exposure) reads `docs/plans/phase-7-public-deployment.md` and this document, and writes back a memo identifying the actual exposure.
2. **Public-facing ToS** for the hosted service that says explicitly:
   - "You operate Tally against your own LinkedIn session. You're responsible for compliance with LinkedIn's ToS as a logged-in user."
   - "Tally does not redistribute vacancy content. Cross-user features are opt-in and aggregated to k-anonymity floors."
   - "If LinkedIn requests removal of any data sourced via your account, you (the user) commit to removing it within 30 days."
3. **Privacy policy** that documents:
   - Exactly what Tally stores per user.
   - Where it's stored (region, encryption posture).
   - How a user exports / deletes.
   - That the operator (Aleksei) has *technically* no read access to encrypted user vaults.
4. **DMCA / takedown contact** published.
5. **Rate limiting** on the *hosted* API to prevent any user from running an autopilot that's faster than a determined human (already implemented client-side; needs to be re-enforced server-side once the cloud is multi-user).
6. **Consider reaching out to LinkedIn** in a "we're shipping a personal note-taking tool, here's our posture, please flag concerns" mode. This is unconventional and might invite a C&D, but the alternative is being surprised by one. Discuss with the lawyer first.
7. **Open-source the codebase.** A self-hostable, transparent project is harder to litigate against than a closed-source product. (Already public on GitHub: `Morty2049/multi-agent-data-miner`.)
8. **Don't market with the word "scraper."** Tally's framing in copy, README, blog posts, and any landing page is **proto-CRM for job-seekers** + **personal skill-development tool**. The technical mechanism (DOM reading) is implementation detail, not the product.

---

## Disclaimer

- This document is **engineering reasoning, not legal advice.** It reflects our understanding of LinkedIn's published terms, of US case law (notably *hiQ Labs v. LinkedIn*, 9th Cir. 2022), and of EU data-protection norms. It is not a substitute for a lawyer.
- **Each user is responsible** for their own use of Tally with respect to LinkedIn's terms of service. Installing Tally does not grant immunity from LinkedIn's normal account enforcement (cooldowns, restrictions, bans).
- **The maintainer (Aleksei Petrov)** is responsible for the hosted Phase 7 instance, when it ships. The pre-deployment checklist above must be completed first.
- **Contributors** to this codebase do not, by contributing, take on legal responsibility for downstream use of the software. The MIT license (or whatever the project ends up under) governs.

If you find a security or privacy issue, contact: `aleksei.petrov.sd@gmail.com`.

---

## What this document is **not**

- It's not a guarantee that Tally is legal. We believe it is, for current single-user localhost use, with the technical precautions documented above. Anyone with a contrary opinion (especially a qualified lawyer) is invited to open an issue.
- It's not a permission to scale Tally beyond personal use without going through the Phase-7 checklist.
- It's not an endorsement of using Tally to violate any third party's terms of service. Use it on services you have a legitimate reason to interact with via your own logged-in session.
