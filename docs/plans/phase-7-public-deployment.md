# Phase 7 — Public deployment + multiplayer features

**Status:** Draft (planning only — gated on Phases 4/5/6 being stable)
**Predecessor:** Phase 6 (multi-tenant data shape; this phase swaps the hardcoded `default` user for real auth)
**Author/owner:** Aleksei Petrov
**Date:** 2026-04-28

## 1. Goals & non-goals

### Goals
- **Move the API server from localhost to a public URL.** Pick a host, ship a Dockerfile + deploy config, document the runbook.
- **Real auth.** Magic link + WebAuthn passkey. No password storage; minimal PII.
- **Multi-tenant data isolation.** Inherit Phase 6's `data/users/<uid>/` shape; replace the `default` user with auth-derived IDs.
- **Encryption at rest.** Per-user data encrypted with a key derived from the user's session.
- **Opt-in cross-user features (the "multiplayer" parts that were originally Phase 5).** Vacancy fingerprint dedup with k-anonymity floor of 5; opt-in skill ontology contributions to a shared community pool.
- **Observability.** Logging, error tracking, basic metrics dashboards.
- **CI/CD.** Reproducible deploys via GitHub Actions; documented rollback.

### Non-goals
- **Paid plans / billing.** Whole next phase if there is one.
- **Enterprise SSO** (SAML / Okta).
- **Mobile apps.** Chrome extension stays the only client.
- **Recruiter-side product.** Tally is a candidate-side tool; resisting feature creep.
- **Self-hostable polished UX.** The codebase stays deployable both to public hosting and to a local box, but documenting "how to host your own Tally server" isn't a v1 user journey. Don't break it; don't optimise for it.
- **Match-score crowdsourcing.** Aggregating "users with profiles like yours scored X% on this JD and N got an offer" is a Phase 7.5 / Phase 8 idea — only viable after enough users join.

---

## 2. Hosting choice

**Decision: Fly.io.**

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Fly.io** | App + persistent volumes + secrets in one CLI; Lisbon region (`mad` ≈ Madrid) is closest to Aleksei; reasonable free tier; `flyctl deploy` is fast | Cold starts on free tier; smaller community than AWS | ✓ |
| **Railway** | Zero-config; nice deploy UX | Pricier per workload; limited region selection | runner-up |
| **Bare-metal VPS** (Hetzner, DO) | Maximum control; lowest cost | Ops burden falls fully on Aleksei (TLS renewal, backups, monitoring) | overkill for v1 |

**Why Fly over the others:**
- Aleksei's stack (FastAPI + small data) is the canonical Fly.io use case.
- `fly.toml` declarative config is friendly to the kind of git-tracked infra he already maintains.
- The latency from Lisbon to `mad` is ~30ms — better than US-east hosts. Important because the Chrome extension is chatty (one HTTP call per saved vacancy + per page nav).

---

## 3. Multi-tenant data model

### Storage abstraction

`chrome_plugin/storage.py` (new module). Two implementations:
- `LocalFsStorage` — current behaviour, used when `JOB_MINER_DATA_DIR` is local.
- `S3Storage` — Backblaze B2 or Cloudflare R2 (both S3-compatible; both cheaper than AWS S3). Used when `TALLY_S3_*` env vars are set.

All callers in `config.py` go through this layer. `LocalFsStorage` keeps the `data/users/<uid>/...` directory structure inherited from Phase 6; `S3Storage` keys are `<bucket>/users/<uid>/...`.

### Vault sync strategy

Vault stays primarily local (Obsidian is a desktop app; canonical store is the user's machine). Phase 7 adds **opt-in** vault sync:
- A small CLI (`tally sync push`, `tally sync pull`) ships with the Chrome extension; calls `/api/vault/{push,pull}/<uid>`.
- Encryption: client-side, end-to-end. The server stores ciphertext blobs without ever holding the key.
- **Default behaviour: no sync.** If a user wants their vault on their phone, they opt in.

### User_id provisioning

- Phase 6 hardcodes `user_id = "default"`.
- Phase 7 generates a real `user_id` (UUIDv7) on first sign-up.
- One-time migration on the user's first cloud sign-in copies `data/users/default/*` → `data/users/<real-uid>/*` (or pushes to S3, depending on backend).

---

## 4. Auth

**Decision: passwordless magic link + WebAuthn passkey.**

### Sign-up flow
1. User enters email on the sign-up page.
2. Server hashes email (Argon2) for storage; sends a magic link to the plaintext email address.
3. User clicks link → server validates the token (15-min TTL, single-use) → issues a session JWT (1h) + refresh token (7d) as HTTP-only cookies.
4. Optionally, the user enrols a passkey (`navigator.credentials.create()`) for future logins. With a passkey enrolled, magic links become a fallback.

### Why not OAuth (Google / LinkedIn)?
- Adds a third-party dependency that contradicts the privacy story (Tally is about scraping LinkedIn, not handing them another identity surface).
- Magic link + passkey is enough for an MVP, and 2026's WebAuthn UX is good.

### Account deletion
- `DELETE /api/me` triggers soft-delete (7 days) → hard-delete.
- Hard-delete removes all `data/users/<uid>/*` and `obsidian_vault/users/<uid>/*` (if synced); also rotates the dedup hashes contributed by this user.

### Chrome extension auth handshake
- On first install, sidebar shows a "Sign in to Tally" button → opens the hosted sign-up page in a new tab.
- After sign-in, the extension pulls a fresh refresh token via `/api/auth/extension-handshake?session=<jwt>`; stores it in `chrome.storage.local`.
- All subsequent API calls from the extension include `Cookie: refresh_token=…` (or use bearer header).

---

## 5. Privacy + encryption

### At rest
- AES-256-GCM, per-user data key derived from `HKDF(master_key, user_id || "data")`.
- `master_key` lives in Fly.io's secret store; never logged.
- The server can decrypt user data only while serving an authenticated request from that user. Background jobs (cron, dedup probe) operate on metadata-only (file sizes, timestamps, hashes) — never on plaintext content.

### In transit
- TLS everywhere (Fly handles automatically via Let's Encrypt).

### Cross-user features (where multiplayer becomes real)
- **Vacancy fingerprint dedup**:
  - Hash = `SHA256(canonical_url || normalized_title || normalized_company)`.
  - Endpoint: `POST /api/dedup/probe { hash }` → `{ count: int }` only when `count >= 5` (k-anonymity floor); otherwise `{ count: null }`.
  - Use case: sidebar shows "47 other Tally users have this vacancy in their vault."
- **Public skill ontology contribution**:
  - Opt-in atom-by-atom. Default off.
  - When user adds a new atom to their personal Skills graph, a checkbox: "Contribute to community ontology."
  - Contributed atoms (slug + synonyms only — no JD context, no user identity) flow into a shared `community_ontology.jsonl` that all users benefit from on next ontology rebuild.
- **Match-score crowdsourcing**: deferred (see non-goals).

### Telemetry
- Opt-in only (default off). User can toggle in settings.
- Anonymized: only `(event_kind, at, scoring_engine, persona_count_bucket)` — no `job_id`, no atoms, no persona slugs.
- Used for product metrics (signup funnel, retention, scoring engine usage breakdown).

---

## 6. Observability + ops

### Logging
- Structured JSON to stdout. Fly's log aggregation picks it up.
- Mirror to a 7-day retention bucket (B2/R2) for replay.

### Errors
- Sentry free tier (5K errors/month). Auto-redacts emails and tokens via Sentry's PII scrubber.

### Metrics
- Prometheus-compatible `/metrics` endpoint.
- Grafana Cloud free tier dashboard, 5 panels: request rate, p99 latency, scoring engine breakdown (Gemini / Claude / Ollama / OpenAI / search), signup funnel, error rate.

### Health checks
- `/api/health` (existing) — fast liveness.
- `/api/health/deep` (new) — checks storage backend + each configured LLM backend; returns 200 only if all-green.

### On-call
- One person (Aleksei). No rotation. Failures handled during business hours.
- Fly's "auto-scale to 0 when idle" means a cold start on the first request after idle; document this is acceptable for a free MVP.

---

## 7. CI/CD + reproducible deploys

### GitHub Actions
1. **On PR**: pytest + lint + Docker build (no deploy).
2. **On merge to `main`**: same + deploy to Fly *staging* (`tally-staging.fly.dev`).
3. **Manual promotion**: `gh workflow run promote-to-prod` runs the same artefact against prod (`api.tally.example`).

### Migrations
- `scripts/migrate_<version>.py` files; each idempotent.
- Stamped via `data/.migrations_applied` (a JSONL of `{version, at}`).
- Run on app startup before serving traffic.

### Rollback
- `flyctl releases rollback <release-id>` — Fly natively supports this.
- Migrations are forward-only; if a rollback would require downgrading data, the runbook says "stop the app, restore from the last B2 snapshot, redeploy."

### Backups
- Daily snapshot of S3-compatible storage to a separate B2 bucket (cron Lambda or Fly machine on a schedule).
- Retention: 30 daily + 12 monthly.

---

## 8. Frontend distribution

- Chrome extension code stays in `chrome_plugin/`. Same codebase deployable to localhost or to the public host.
- At install time the extension prompts: "What's your Tally server?" Default: `https://api.tally.example`. Advanced users can point at their localhost.
- URL stored in `chrome.storage.local`; settings panel exposes it for changes.
- **Chrome Web Store submission** is out of scope for v1 — Aleksei iterates via "Load unpacked" and a small invite list. Web Store happens once the API has been stable for ~30 days. Track as Phase 8 if needed.

---

## 9. Multiplayer features (the parts that were originally Phase 5)

These all live behind opt-in toggles in the user's settings. Default: off.

| Feature | Endpoint | Privacy posture |
|---|---|---|
| Vacancy dedup index | `POST /api/dedup/{probe,contribute}` | k-anonymity floor 5, hash-only |
| Public skill ontology | `POST /api/community/skills/contribute`, `GET /api/community/skills/snapshot` | atoms only, no JD context, no user link |
| Anonymized telemetry | `POST /api/community/telemetry` | bucketed counts only |

The aggregation layer is a small sidecar process (Fly machine on a schedule) that reads contributions, applies k-anonymity, and emits a public `community_ontology.jsonl` that the API serves to all users on ontology rebuild.

---

## 10. Slicing breakdown

### Slice 7.1 — Storage abstraction + S3 backend (~1 day)
- **Files:** `chrome_plugin/storage.py` (new), all existing `Path`-based callers in `config.py` switched to `Storage.read/write/list`.
- **Tests:** round-trip with both backends; golden-state verification per backend.
- **User-visible:** none yet. Localhost still works exactly as before.

### Slice 7.2 — Auth (magic link + passkey) (~2 days)
- **Files:** `chrome_plugin/auth.py` (new), endpoints `/api/auth/{login,verify,refresh,logout,delete,extension-handshake}`, `obsidian_vault/_internal/auth_state.json` for the extension's stored token.
- **Tests:** magic-link TTL, single-use, refresh-token rotation, account-delete cascade.
- **User-visible:** sign-up page on the hosted instance; "Sign in to Tally" button in extension.

### Slice 7.3 — Multi-tenant data routing (~1 day)
- **Files:** every endpoint that took `?user_id=` from Phase 6 now reads it from auth context (JWT `sub` claim) instead. Migration helper `scripts/migrate_default_to_uid.py` for the user's existing `default` user data.
- **Tests:** cross-user isolation (user A can't read user B's data even via direct API call), migration idempotency.
- **User-visible:** Aleksei's existing data follows him to his real user_id on first sign-in.

### Slice 7.4 — Encryption at rest (~1 day)
- **Files:** `chrome_plugin/storage.py` gets transparent encrypt/decrypt via per-user key. `chrome_plugin/auth.py` gains `derive_user_key(user_id)`.
- **Tests:** ciphertext doesn't leak plaintext; key rotation (admin endpoint); decrypt-after-rotate.
- **User-visible:** none. Performance: ~1ms overhead per read/write — measured, not feared.

### Slice 7.5 — CI/CD pipeline + Fly deploy (~1 day)
- **Files:** `Dockerfile`, `fly.toml`, `.github/workflows/{ci.yml,deploy-staging.yml,promote-to-prod.yml}`, runbook in `docs/runbook.md`.
- **Tests:** the pipeline itself — verified by a deploy-then-rollback dry run.
- **User-visible:** the URL `https://api.tally.example` is live.

### Slice 7.6 — Multiplayer dedup + ontology contribution (~1 day)
- **Files:** `chrome_plugin/community.py` (new; aggregation logic), endpoints `/api/dedup/{probe,contribute}` + `/api/community/skills/{contribute,snapshot}`, settings panel toggles.
- **Tests:** k-anonymity gate (count < 5 returns null); contribution dedup; snapshot regen.
- **User-visible:** "47 others have this vacancy" badge on saved cards (opt-in); shared atoms appear in ontology rebuild.

---

## 11. Migration plan

- **Aleksei's existing data (`data/users/default/*`)**: migrated to `data/users/<his-real-uid>/*` on his first cloud sign-in. Migration helper kept around for re-runs.
- **Vault**: stays local on his machine. Opt-in to vault sync after the cloud is stable.
- **Phase 6 telemetry**: re-keyed to new user_id during migration; same data, new path.
- **`data/profile.yml` legacy fallback**: removed at this phase. By Phase 7 every persona lives in `obsidian_vault/Personas/`.

---

## 12. Open questions / risks

1. **GDPR + Portuguese data law applicability.** If users beyond Aleksei sign up, jurisdictional analysis is needed. Provision `GET /api/me/export.zip` and `DELETE /api/me` *before* opening sign-ups beyond invite-only.
2. **LinkedIn ToS exposure.** The extension's read-only DOM scraping has been operating from individual users' browsers; the cloud version still does. But the cloud now **receives** the parsed data. Document the boundary clearly: Tally is a personal note-taking tool; the user's LinkedIn session is theirs and never crosses to the server.
3. **Cost ceiling for the free tier.** Fly's free tier covers ~3 small VMs and ~3GB persistent volume. Storage isn't free past a small floor. Estimate per-user cost; gate beta to invite-only until economics are clear.
4. **What if a user wants to self-host?** Document the env vars + `docker compose up`; keep the codebase deployable both ways. Don't optimise for self-host UX in v1; just don't break it.
5. **Browser-extension auto-update.** With "Load unpacked", users manually pull. Chrome Web Store fixes this — track as Phase 8.
6. **Multiplayer privacy edge cases.** What if a user contributes an atom that's actually a sensitive personal identifier? Mitigation: contribution is opt-in *per atom*; UX shows the slug + synonyms before contributing.
7. **Cold-start latency.** Fly auto-scales to 0; first request after idle is ~3s. For an MVP this is fine; if it bothers users, set `min_machines_running = 1` on prod.
8. **Account recovery if user loses both magic-link email and passkey.** Today's plan: support email at a manual address; user proves identity by re-attesting via a second device. Document.
