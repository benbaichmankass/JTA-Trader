# UI-UPGRADE-1 — site sign-in (Google + passkey) and the Keys admin tab

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
> Referenced by checklist rows `UI-UPGRADE-1` and `UI-UPGRADE-1-AUTH`. Operator asks, verbatim from the row: items (7) and (9). Popup answers: login **"Google + passkey"**, keys **"View + edit, passkey each time"**.

Every statement below is marked MEASURED (read this session, with where), or
INFERRED / PROPOSED.

---

## 1. What the sign-in is today (MEASURED, `src/web/api/auth.py`, `routers/auth.py`)

| piece | what it is |
|---|---|
| credential | **one email + one password**. The email must equal env `ALLOWED_EMAIL`. The password is hashed with **unsalted SHA-256** and compared, in constant time, with env `WEBAPP_PASSWORD_SHA256`. There is no rate limit and no second factor. |
| issued token | `POST /api/auth/login` returns an **HS256 JWT** signed with env `JWT_SIGNING_KEY`, **TTL 3600 s**, claims `{email, iat, exp}`. Nothing records issued tokens, so **no token can be revoked**: rotating `JWT_SIGNING_KEY` is the only kill switch, and it logs out everything. |
| where it is checked | `require_session` (FastAPI dependency) re-checks the signature, expiry and `email == ALLOWED_EMAIL`. Only these routes attach it: `/api/bot/db/*` (Data Explorer), `/api/pnl`, `/api/status`. |
| what is NOT gated | **Nearly the whole read API.** `/api/bot/{stats,positions,performance,signals,config,strategies,prop/*,work/*,…}` all answered an anonymous `curl` from this session (2026-10-11), as did `WS /ws/market`. The SPA itself is a public GitHub Pages site. |
| where the SPA keeps it | `localStorage` (`webapp/src/lib/auth.ts`) — deliberately, so a reload survives the 1 h TTL. |
| where the secrets live | GitHub Actions secrets → pushed to the VM by `system-actions` (`sync-vm-secrets` / `set-env`). `ALLOWED_EMAIL` is already set to the operator's Google address (`deploy-candidate.yml`). |

So the operator's "DB sign-in creds unclear" is accurate. It is a single
shared password that guards **three** routes, nobody has written it down
anywhere visible, and it cannot be revoked per device.

## 2. Target (PROPOSED)

**Google proves who you are; a passkey proves it is your device; the server
issues a long-lived, revocable, per-device session; every route requires it.**

### 2a. Sign-in flow
1. The SPA runs **Google Identity Services** (One Tap or a button). The browser
   gets a Google **ID token**: a JWT signed by Google, audience = our OAuth
   client id. **There is no client secret in the browser and no redirect
   dance.**
2. `POST /api/auth/google {id_token}`. The server verifies it with
   `google.oauth2.id_token.verify_oauth2_token` (`google-auth` is already in
   `requirements.txt`). It checks `aud == GOOGLE_OAUTH_CLIENT_ID`,
   `email_verified`, and `email == ALLOWED_EMAIL`. Anything else gets 403.
   The result is a **5-minute pre-auth ticket**, not a session.
3. **Passkey (WebAuthn)**, using `py_webauthn` (new dependency):
   - *First device, while no credential is registered:* registration requires
     the pre-auth ticket **and** a one-time **enrolment code**. The code is
     printed by a Tier-1 system-action (`passkey-enrol-code`) into a private
     Telegram SYSTEM ping. Without it, anyone who phished the Google login
     during the window could register their own passkey.
   - *Later devices:* register from an already signed-in device, or with a new
     enrolment code.
   - *Every sign-in:* `navigator.credentials.get()`. The server verifies the
     assertion against the stored public key and enforces the signature
     counter.
4. The server creates a **device session**:
   - random 256-bit id;
   - **30-day sliding expiry** (PROPOSED; the dispatch suggested 30 d);
   - stored **hashed** in the canonical `trade_journal.db`, table
     `web_sessions`, with a `# data-wiring:` declaration (a new table needs
     the operator's OK; this is that ask, §5);
   - columns: device label, user-agent, created / last-seen / IP, passkey id,
     `revoked_at`.
5. **Transport.** The SPA is on `github.io` and the API on `duckdns.org`, so a
   cookie would be **third-party** and Safari/ITP blocks those. So the session
   rides as a **bearer**, exactly as today (`api.ts` already sends one
   everywhere; its `auth-bearer.mjs` test enforces it).
   - Where the SPA stores it is the cost: `localStorage` is readable by any
     XSS on the page.
   - Mitigations, PROPOSED:
     - a strict CSP on the Pages site (no inline script, `connect-src` = the
       API);
     - the session is bound to the passkey: **step-up** for anything
       sensitive (§3);
     - revocation is instant.
   - The alternative is serving the SPA from the same origin (Caddy on
     `ict-bot.duckdns.org/`), which makes an HttpOnly first-party cookie
     possible. That is a bigger move; recorded as option B in §5.

### 2b. "Covering the WHOLE site"
- A new `require_site_session` (the existing `require_session` keeps its three
  routes) is attached **once, as an app-level dependency**
  (`FastAPI(dependencies=[...])`) so it covers every router and `WS /ws/market`,
  and is a no-op while `SITE_AUTH_ENFORCE` is unset (**BUILT** in the
  `UI-UPGRADE-1-AUTH` API PR). Only this stays public:
  - `/api/health`;
  - the auth routes themselves;
  - the CORS preflight `OPTIONS` (CORS **must** stay intact: the middleware
    answers preflight before any dependency runs, and a test pins that);
  - the `/api/diag/*` surface (`DIAG_READ_TOKEN`) and the prop phone/report
    routes (their own bearers), because the relays and the phone have no
    browser.
- **`WS /ws/market`**: a browser WebSocket cannot send an `Authorization`
  header (the SPA's own `auth-bearer.mjs` says so). It authenticates with a
  short-lived **ws ticket**: `POST /api/auth/ws-ticket` returns a 60 s
  single-use token, which goes in the query string.
- ⚠️ **Rollout order is the whole risk.** If the gate goes on before the SPA
  can sign in, the operator's dashboard goes dark. So:
  1. ship the auth routes + SPA sign-in with the gate **off** (gated routes
     unchanged);
  2. the operator signs in once and registers a passkey;
  3. flip the gate. The flip is `set-env SITE_AUTH_ENFORCE=1`, one revertible
     action, verified by an anonymous `curl` returning 401 and a signed-in
     one returning 200.
  
  This is a *rollout* switch for an auth surface, not a trading capability, so
  it is outside the "no third gate" rule; it is removed once enforcement has
  been observed.
- **Other non-browser consumers that read `/api/bot/*` — INVENTORIED 2026-10-11
  (build step 1, row `UI-UPGRADE-1-AUTH`).** ⚠️ **METHOD AND LIMIT.** This is a
  *static* inventory: a `grep` of the repo for the API host forms
  (`ict-bot.duckdns.org`, `127.0.0.1:8001`, `localhost:8001`, `BOT_API_URL`,
  `BOT_API_BASE`, `DIAG_BASE_URL`) and for `/api/bot/`, `/api/pnl`,
  `/api/status`, `/ws/market` in `*.py`, `*.sh`, `*.yml`, then read to separate
  files that *issue a request* from files that merely *mention* a route in a
  docstring or comment (e.g. `scripts/ci/check_collapsed_states.py`,
  `src/main.py`, `scripts/notify_on_pull.py`, `render_daily_brief.py`,
  `work_report.py` were all excluded after reading the matching lines). It
  proves these consumers EXIST; it does **not** prove the list is complete — a
  consumer that builds its URL from a variable in another file, or a caller
  outside this repo (a laptop `curl`, a bookmark, another repo's workflow),
  would be missed. **24 h of real traffic is the completeness check, and ⚠️ MEASURED
  2026-10-11: `deploy/caddy/Caddyfile` (the repo copy; the file says the VM copy is
  overwritten from it, but the VM copy was NOT read this session) has no `log`
  directive, so there is probably NO Caddy access log to read today** (uvicorn's
  access lines go to the journal, whose retention `docs/reference/env-vars.md`
  records as ~30 min — not re-measured here). It needs a Tier-2 Caddyfile change first. Filed as
  pipeline row `PI-20261011-CFUJ7YFR-0001` (`due_when` + `origin.rerun`); do not
  flip `SITE_AUTH_ENFORCE` before it reports. The bearer retrofit into the 26
  anonymous groups is `PI-20261011-CFUJ7YFR-0002`.

  **33 consumer groups, 42+ named files** (B20 is one group of 7 research scripts, B14 is a family of 5 that share `probe_lib`). **26 of the 33 groups read `/api/bot/*` ANONYMOUSLY today and are marked "needs the service bearer": each would 401 the moment the gate is on unless it sends a credential.** The other 7 already carry a bearer, are public by path, or only hit CORS preflight / `/api/health`. What this lane built for that:
  `require_site_session` accepts `Authorization: Bearer <DASHBOARD_API_TOKEN>`
  as a **read-only (GET/HEAD) service credential**; any non-GET with it is
  refused. Retrofitting the bearer into each consumer (and into `probe_lib` /
  `diag_fetch.sh` / `vm-diag-snapshot.yml` first, which cover the most) is a
  follow-up build row, not part of this lane.

| # | consumer | routes | transport | credential today | after the flip |
|---|---|---|---|---|---|
| A1 | `src/runtime/telegram_decisions.py` (the decision-prompt sweep; `telegram_query_bot` calls it) | `GET/POST /api/bot/work/decisions` | VM loopback `127.0.0.1:8001` (`WORK_DECISION_API_BASE`) | GET anonymous; POST sends a `DASHBOARD_API_TOKEN` bearer (line ~1036) | GET needs the service bearer |
| A2 | `src/prop/prop_executor.py` | `/api/bot/prop/*` | VM loopback | `DASHBOARD_API_TOKEN` bearer | unchanged for `report`/`phone/*`; reads need the bearer (already sent) |
| A3 | `src/prop/phone_executor.py` | `/api/bot/prop/phone/*` | public HTTPS (phone) | own bearer | public by prefix — unchanged |
| A4 | `scripts/prop/prop_executor_tick.py` | `/api/bot/prop/*` | VM loopback `--api-base` | bearer | as A2 |
| A5 | `scripts/prop/breakout_login_check.py` | `/api/bot/prop/*` | VM loopback | bearer | as A2 |
| A6 | `scripts/ops/prop_silence.py` | `/api/bot/prop/*` | VM loopback (`PROP_SILENCE_API_BASE`) | anonymous | **needs the service bearer** |
| A7 | `scripts/ops/reattach_stranded_package_legs_action.sh` | `/api/bot/positions` | VM loopback over SSH | anonymous | **needs the service bearer** |
| A8 | `.github/workflows/deploy-candidate.yml` | `/api/bot/stats` (+ `/api/health`) | VM loopback over SSH | anonymous | **needs the service bearer** (health stays public) |
| A9 | `.github/workflows/vm-caddy-deploy.yml` | `/api/bot/stats` CORS preflight + `/api/health` | public HTTPS | preflight only | unchanged (preflight and health stay public) |
| A10 | `.github/workflows/live-replay-parity.yml` + `scripts/ops/live_replay_parity.py` | `/api/bot/candles` (+ `/api/diag/*`) | SSH tunnel to `:8001` | anonymous for `/api/bot/candles` | **needs the service bearer** |
| A11 | `.github/workflows/prop-report.yml` | `POST /api/bot/prop/report` | VM loopback over SSH | `DASHBOARD_API_TOKEN` bearer | public by path — unchanged |
| A12 | `.github/workflows/work-decision-commit.yml` | `/api/bot/work/*` (+ `/api/diag/log_file`) | VM loopback over SSH | anonymous for `/api/bot/work/*` | **needs the service bearer** |
| A13 | `.github/workflows/vm-diag-snapshot.yml` + `scripts/ops/diag_fetch.sh` (the session-facing relay) | arbitrary `/api/bot/*` paths a session asks for (`order-packages`, `performance`, `pnl`, `trades`, `work`, `stats` …) + `/api/diag/*` | relay: runner → VM loopback, or session → public HTTPS | `/api/diag/*` carries `DIAG_READ_TOKEN`; `/api/bot/*` anonymous | **the biggest one — every session read of `/api/bot/*` goes through it; needs the service bearer or sessions go blind** |
| B1 | `.github/workflows/account-broker-reconcile.yml` | `/api/bot/positions`, `/prop`, `/trades` | public HTTPS (`BOT_API_BASE`) | anonymous | **needs the service bearer** |
| B2 | `.github/workflows/broker-bracket-reconcile.yml` + `scripts/ops/broker_bracket_reconcile.py` | `/api/bot/positions` | public HTTPS | anonymous | **needs the service bearer** |
| B3 | `.github/workflows/broker-truth-freshness.yml` | `/api/bot/pnl/broker-truth`, `/api/bot/trades/closed` | public HTTPS | anonymous | **needs the service bearer** |
| B4 | `.github/workflows/gld-compat-matrix.yml` | `/api/bot/accounts/balances` | public HTTPS | anonymous | **needs the service bearer** |
| B5 | `.github/workflows/r4-demotion-gate.yml` | `/api/bot/performance/recent` | public HTTPS | anonymous | **needs the service bearer** |
| B6 | `.github/workflows/sunset-pass.yml` | `/api/bot/performance` | public HTTPS | anonymous | **needs the service bearer** |
| B7 | `.github/workflows/dashboard-edge-watch.yml` + `scripts/ops/dashboard_edge_watch.py` | `/api/bot/stats` CORS preflight + `/api/health` | public HTTPS | preflight only | unchanged |
| B8 | `scripts/ops/constraint_readout.py` | `/api/bot/performance`, `/api/bot/work/*` | public HTTPS | anonymous | **needs the service bearer** |
| B9 | `scripts/ops/error_feed_digest.py` | `/api/bot/logs`, `/api/bot/notifications` | public HTTPS | anonymous | **needs the service bearer** |
| B10 | `scripts/ops/exit_mechanics_audit.py` | `/api/bot/db/*`, `/api/bot/positions` | public HTTPS (`--api`) | anonymous (`/db/*` already needs the JWT) | **needs the service bearer** |
| B11 | `scripts/ops/journal_venue_audit.py` | `/api/bot/positions` | public HTTPS | anonymous | **needs the service bearer** |
| B12 | `scripts/ops/leg_flow_report.py` | `/api/bot/config`, `/prop`, `/strategies` | public HTTPS (`BOT_API_URL`) | anonymous | **needs the service bearer** |
| B13 | `scripts/ops/ml_plan_status.py` | `/api/bot/ml*`, `/api/bot/shadow*` | public HTTPS | anonymous | **needs the service bearer** |
| B14 | `scripts/ops/probe_api.py` + `probe_lib.py` (used by `probes.yml`, `run_probes.py`, `soak_alarm.py`, `probe_soak.py`) | `/api/bot/config`, `/logs`, `/trades` … | public HTTPS (`BOT_API_URL`) | anonymous | **needs the service bearer** (one change in `probe_lib` covers the family) |
| B15 | `scripts/ops/snapshot_soak_state_for_mandate.py` | `/api/bot/work/brief` | public HTTPS | anonymous | **needs the service bearer** |
| B16 | `scripts/ops/strategy_liveness.py` | `/api/bot/config`, `/strategies` | public HTTPS (`BOT_API_URL`) | anonymous | **needs the service bearer** |
| B17 | `scripts/ops/target_expectation_coverage.py` | `/api/bot/positions` | public HTTPS | anonymous | **needs the service bearer** |
| B18 | `scripts/ops/verify_running_roster.py` | `/api/bot/runtime-config` | public HTTPS | anonymous | **needs the service bearer** |
| B19 | `scripts/prop/trade_quality_review.py` | `/api/bot/prop/*` | public HTTPS | anonymous | **needs the service bearer** |
| B20 | `scripts/research/{partial_close_reachability, prop_baseline_reconcile, expectancyr_correction_matrix, r_sign_split_basis, real_money_close_attribution, realized_slippage, geometry_amend_census}.py` (7 files) | `/api/bot/{config,db,prop,performance,trades,pnl}` | public HTTPS | anonymous | **need the service bearer** (7 files, one pattern) |

  Not consumers of the gated surface, listed so nobody re-checks them:
  `/api/diag/*` callers (`system-actions.yml`, `sync-vm-secrets.yml`,
  `set-diag-token.yml`, `rotate-account-keys.yml`, `cutover-live.yml`, …) carry
  `DIAG_READ_TOKEN` and the gate leaves `/api/diag/*` alone;
  `/api/health` callers (`vm-web-api-recover.yml`, `ci-settled.yml`,
  `scripts/check_web_api.py`, `restart_web_api.sh`, …) hit a public path.
  `/docs`, `/redoc` and `/openapi.json` are **not** covered by the app-level
  dependency (they are not router routes) and remain public when the gate is on
  — they list route names, not data; closing them is a one-line follow-up.
  `trainer-diag-relay.yml` mentions `/api/bot/ml` against the **trainer** VM, a
  different service.

### 2c. Devices admin (revocable list)
- `GET /api/auth/sessions` lists device sessions (label, last-seen, created).
- `DELETE /api/auth/sessions/{id}` revokes one.
- Both are behind a session; the DELETE also needs passkey step-up.
- The SPA gets **Admin → Devices**.
- "Sign out everywhere" = revoke all but the current session.

## 3. Keys admin tab (item 9) — PROPOSED, with one decision for the operator

Operator's terms: list the keys; value hidden behind an eye icon; the field is
prefilled with the current value and has Save; **every reveal and every save
re-prompts the passkey**; values are never cached client-side; every reveal
and change is audited server-side and pinged once to SYSTEM; writes go through
the sanctioned secret path.

- **List.** `GET /api/admin/keys` returns names only, plus for each:
  - where it lives (`shared` `.env` / `web-api.env`);
  - set / set_empty / unset (the same four states `get-env` already reports,
    never collapsed);
  - whether a GitHub Actions secret of the same name exists.
  
  The allowlist of names is a reviewed constant (the `get_env.py::ALLOWED_KEYS`
  doctrine). The page never enumerates the environment freely.
- **Step-up.**
  - `POST /api/auth/stepup/begin` returns a WebAuthn challenge bound to
    `{action: reveal|save, key}`.
  - The assertion is redeemed for a **single-use, 60-second** step-up token
    scoped to exactly that action + key.
  - No step-up token, no value.
- **Reveal.** `POST /api/admin/keys/{name}/reveal` with the step-up token.
  - The server reads the value from the file the running service loaded.
  - It returns the value with `Cache-Control: no-store`.
  - It writes an audit row: who, device session, key name, action, time, IP.
    **Never the value.** The audit is `ops_audit`-style JSONL beside the
    existing system-actions audit, so no new store.
  - It sends one SYSTEM Telegram ping: "🔑 revealed `KEY` from <device>".
  - The SPA holds the value only in a component-local variable. It is cleared
    when the eye closes or the page leaves, never written to
    `localStorage`/`sessionStorage`, and never logged.
  - `auth-bearer.mjs` gets a sibling test asserting no storage write in the
    keys route.
- **Save.** `PUT /api/admin/keys/{name}` with the step-up token. ⚠️ **This is
  where "the sanctioned path" forks, and it is the operator's decision (§5,
  D2):**
  - The source of truth for most keys is **GitHub Actions secrets**.
    `set-env` with a blank `env_value` copies `secrets.<KEY>` to the VM. A
    value written only to the VM `.env` is **overwritten** by the next
    `sync-vm-secrets`. So writing the VM file alone is not a sanctioned path:
    it is a silent revert waiting to happen.
  - **D2-A (recommended).** The API calls GitHub's *create-or-update repository
    secret* endpoint, encrypting the value with the repo's public key (libsodium
    sealed box). Then it opens the existing `set-env` system-action issue for
    that key (blank value, so the value never transits the issue). The page
    shows the run's result.
    - Cost: the VM needs a **fine-grained GitHub token with only "Secrets: read
      and write" on this one repo**.
    - That token is a powerful credential on an internet-facing host: whoever
      steals it can rewrite every Actions secret. It is guarded by the passkey
      step-up and the audit/ping, and it is itself NOT editable from the page.
  - **D2-B.** Saves only write the VM `.env` (via `set-env`'s file-write code
    path) and **flag the key as "diverged from Actions secret"** on the page
    until the operator updates GitHub by hand. Simpler, no new credential, but
    a second source of truth for as long as the flag stands.
  - Either way, a save to a key whose service must restart goes through
    `set-env`'s `service:` restart. **A save that would restart
    `ict-trader-live` asks for a second confirmation in the UI**, because a
    restart is a Tier-2 live action.
- **Never editable from the page:**
  - `JWT_SIGNING_KEY` / session-signing material;
  - the GitHub token itself;
  - `ALLOWED_EMAIL`;
  - `GOOGLE_OAUTH_CLIENT_ID`;
  - broker/exchange API keys that the operator rotates at the venue (CLAUDE.md:
    rotating exchange keys is an operator act). These are **revealable**,
    with step-up.
  
  Editing the keys that guard the page from inside the page lets one stolen
  session lock the operator out.

## 4. What the operator must provide (names only; values never in chat or git)

| name | what | where it goes |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | A Google Cloud **OAuth 2.0 Client ID, type "Web application"**. Authorised JavaScript origins: the SPA's GitHub Pages origin, plus `https://ict-bot.duckdns.org` if option B is ever taken. No redirect URI is needed for the ID-token flow. **No client secret is used by this design.** | GitHub Actions secret → `set-env` → `web-api.env`. It is not secret in the cryptographic sense (it ships in the SPA too) but is kept as a secret for one place of record. |
| `WEB_SESSION_PEPPER` | 32 random bytes, used to hash session ids at rest. | Actions secret → `web-api.env`. Can be generated by a runner. The operator does not have to originate it (`credentials-and-vm-mutations`). |
| `GH_SECRETS_WRITE_TOKEN` | **Only if D2-A.** Fine-grained PAT, this repo only, permission *Secrets: read & write*, nothing else, 90-day expiry. | Actions secret → `web-api.env`. |
| a passkey | Registered by the operator on each device, once, using the enrolment code from the SYSTEM ping. | the operator's device / password manager |

`ALLOWED_EMAIL` already holds the operator's Google address. `JWT_SIGNING_KEY`
and `WEBAPP_PASSWORD_SHA256` are retired once enforcement is observed: the
password login is removed, not kept as a back door.

## 5. Decisions for the operator

- **D1.** New table `web_sessions` in `trade_journal.db`, holding device
  sessions and passkey public keys. A new persistent table needs the operator's
  OK (CLAUDE-RULES § Rule 3). The alternative is a JSON file beside the
  web-api env, but sessions are written on every sign-in and last-seen update,
  which is what a DB is for. Recommended: yes.
- **D2.** Keys Save path: **A** (API writes the GitHub Actions secret, then
  `set-env`; needs `GH_SECRETS_WRITE_TOKEN`) or **B** (VM file only, flagged as
  diverged). Recommended: A.
- **D3.** Session lifetime: 30-day sliding (recommended), or absolute.
- **D4 (optional).** Move the SPA to the API origin (option B in §2a) for an
  HttpOnly cookie. Not needed for the first version.

## 6. Build order (row `UI-UPGRADE-1-AUTH`)

> **Status 2026-10-11:** steps 1–2 are built in the API PR (inventory in §2b;
> `routers/auth_google.py`, `web_sessions.py`, `auth.py::require_site_session`,
> `tests/test_web_site_auth.py`); step 3 is the SPA patch (separate repo / `comms/`).
> Two deliberate deviations from the sketch above: the Devices admin revokes
> through `POST /api/auth/sessions/{handle}/revoke` (the API's CORS allow-list is
> GET/POST only and was left untouched) with a `DELETE` twin for non-browser
> callers; and DELETE does **not** yet need passkey step-up (step-up is built
> with the Keys tab, step 5).

1. Inventory the non-browser consumers of `/api/bot/*` (24 h of the Caddy
   access log, plus a grep).
2. API:
   - `/api/auth/google`, WebAuthn register/assert, device sessions,
     `/api/auth/sessions`, ws-ticket;
   - tests: forged / expired / wrong-audience Google token, wrong email,
     replayed assertion, counter regression, revoked session, preflight
     unaffected, diag/phone bearers unaffected.
3. SPA: sign-in screen, passkey prompts, Devices admin.
4. Operator enrols; then the gate flips with `set-env`; the post-state is
   verified.
5. Keys tab (after D2), with step-up tokens, audit + SYSTEM ping, and the
   no-client-storage test.
6. Remove the password login and `WEBAPP_PASSWORD_SHA256`.
