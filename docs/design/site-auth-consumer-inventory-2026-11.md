# Site-auth consumer inventory — who calls the API before `SITE_AUTH_ENFORCE=1`

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · row `UI-OAUTH-SIGNIN` · lane `OAUTH-INVENTORY` · 2026-11-11 · READ-ONLY analysis, nothing flipped, nothing deployed.
> **Gates this adds or changes:** none. It lists what the existing gate (`src/web/api/auth.py::require_site_session`) would break and the retrofit needed first.

Method (MEASURED unless marked): the gate source (`auth.py:216-300`), the routers' own token checks, `grep` over `.github/workflows scripts src tools deploy`
for `ict-bot.duckdns.org | :8001 | BOT_API_URL`, and one read of the Caddy journal through the diag relay. Population of the grep: 92 files mention the API;
37 of them also reference a credential, 29 reference none (list below, **UNVERIFIED per file** — a script may only parse a file another step fetched).

## 1. What the gate does when on (read from the code, not the design doc)

* Public (no site credential): exact `/api/health`, `/api/bot/prop/report`; prefixes `/api/auth/`, `/api/diag/`, `/api/bot/prop/phone/`; `OPTIONS`.
* Everything else, **including loopback `127.0.0.1:8001` callers** (the gate is an app-level dependency, so same-host services are not exempt):
  `Authorization: Bearer ws_…` (device session), or **GET/HEAD only** `Bearer $DASHBOARD_API_TOKEN`. WebSocket: single-use `?ticket=`.
* **Consequence (the main finding): a non-public `POST` carrying a service token is rejected.** Routes that check their own write token inside the router
  (`alerts`, `work/items*`, `work/decision`, `wake-toggles`) are NOT in the public list, so the site gate runs first and returns 401 before the router's
  token is read. Only `prop/report` + `prop/phone/*` were carved out. `GET` consumers with `DASHBOARD_API_TOKEN` pass.
* **Update 2026-11-11 (SITE-AUTH step (i)):** `auth.SITE_PUBLIC_POST_PATHS` / `SITE_PUBLIC_POST_PREFIXES` now carve out, **for POST only**,
  `/api/bot/alerts`, `/api/bot/wake-toggles`, `/api/bot/work/decision` and `/api/bot/work/items[/…]`. Each router fails closed on its own token
  (pinned in `tests/test_web_site_auth_write_carveouts.py`), and the GET reads on the same paths stay gated. This clears the POST half of rows 5, 6, 7 and 8 below.
  `POST /api/bot/devices/register` is NOT carved out yet. Add it once #25007 (its own fail-closed bearer) has merged, or the Android app's POST gets 401.
* **Consumer count, reconciled 2026-11-11:** `PI-20261011-CFUJ7YFR-0002` says "26 anonymous groups". That number comes from the finer-grained
  table in `docs/plans/ui-upgrade-1-auth-and-keys-design.md` § 2b (33 groups B1–B33; 26 of them anonymous). The 15 rows below cover the same population
  more coarsely: rows 10 and 11 alone fold in the anonymous workflows and 29 script files. Same population, two granularities; neither count was re-measured.
* **Correction 2026-11-11:** row 1 lists the SPA as a `POST /api/bot/devices/register` caller. `ict-trader-dashboard/webapp/src` has 0 references to
  `devices/register` (a grep that finds the SPA's other `devices` strings). The only register caller is the Android companion app, which sends the bearer.

## 2. Consumers

| # | Consumer | Routes / method | Credential today | Under `SITE_AUTH_ENFORCE=1` |
|---|---|---|---|---|
| 1 | **SPA** (browser, GitHub Pages) | all `GET /api/bot/*`; `POST /api/bot/learning/progress`, `/api/bot/devices/register`; `WS /ws/market` | none (gate off); sign-in built (`ws_` session) | **session** (`ws_` bearer; WS via `POST /api/auth/ws-ticket`). Its two POSTs are fine with a session. Needs the 401→sign-in handler verified (design §1). |
| 2 | **Phone executor** (Android app `tools/phone-executor`, `Api.kt`) | `/api/bot/prop/phone/*` (claim, report, verify, go, event, capture, drill, exec-js-signature) POST | `DASHBOARD_API_TOKEN` bearer, checked in `prop.py` | **public path** (unchanged). Do not give it a session. |
| 3 | **Prop executor / feed ticks** (`src/prop/prop_executor.py`, `scripts/prop/prop_executor_tick.py`, `deploy/ict-prop-*`) | `GET /api/bot/prop/tickets, fills`; `POST /api/bot/prop/report` (loopback) | `DASHBOARD_API_TOKEN` | GETs pass with the service bearer (it already sends it, `prop_executor.py:721`); POST report is public. **OK, verify the GETs carry the header on every call.** |
| 4 | **Prop report POST** (`prop-report.yml`, `breakout_login_check.py`, `prop_feed_tick.sh`) | `POST /api/bot/prop/report`; `GET /api/bot/prop/status` | `DASHBOARD_API_TOKEN` | report public; `prop/status` GET passes with the bearer if sent. |
| 5 | **Telegram decision bot** (`src/runtime/telegram_decisions.py`, `ict-telegram-bot` / `ict-claude-decision-bot`) | `GET /api/bot/work/decisions`; **`POST /api/bot/work/decision`** (loopback :8001) | `DASHBOARD_API_TOKEN` bearer | GET ok; **POST → 401. NEEDS RETROFIT** (public-path carve-out; the router already fails closed on the token). |
| 6 | **Alert posters** (`scripts/ops/post_alert.sh`, `post_ping.py`, workflows `external-comment-alert`, `external-issue-alert`, `claude-run-failure-alert`) | **`POST /api/bot/alerts`** | `DASHBOARD_API_TOKEN` | **POST → 401. NEEDS RETROFIT** (same carve-out). `digest_due.py`, `attention_watch.py` read `GET /api/bot/alerts` with no token seen → need the bearer. |
| 7 | **Work store writers** (`scripts/ops/work.py`, `work-store-outbox.yml`, sandbox sessions) | **`POST /api/bot/work/items*`** | `X-Work-Store-Token` (`WORK_STORE_TOKEN`) | **POST → 401. NEEDS RETROFIT.** Seen in Caddy: sandbox IP `160.79.106.134` POSTed `/api/bot/work/items/<id>/note` in the window. `GET work/*` readers (`work-digest.yml`, `snapshot_soak_state_for_mandate.py`, `scoreboard.py`) need the bearer. |
| 8 | **Console MCP `JTA_Trader`** (`src/console_connector/`, Google-OAuth fronted, runs on its own host) | `GET /api/diag/*` (via `DIAG_READ_TOKEN`, `tabs.py:66-84`); **`POST /api/bot/wake-toggles`** (`server.py:162`, `WAKE_TOGGLES_WRITE_TOKEN` bearer) | diag token (read), write token (toggle) | diag reads: public, unchanged. **`wake-toggles` POST → 401. NEEDS RETROFIT.** The GET `wake-toggles` read (`src/runtime/wake_toggles.py:46`, runners, `User-Agent: wake-toggles-client`) sends no credential → needs the bearer. |
| 9 | **Diag relay** (`scripts/ops/diag_fetch.sh`, ~25 workflows, trainer VM, `vm-diag-snapshot`, `rotate-account-keys`) | `GET /api/diag/*` | `DIAG_READ_TOKEN` (`Authorization` and/or `X-Diag-Token`) | **public prefix, unchanged.** Caveat: any `diag_fetch.sh` call to a non-`/api/diag/` path (e.g. `/api/bot/stats`) is NOT diag and falls under the gate. |
| 10 | **Anonymous GET workflows** | `r4-demotion-gate.yml` (`/api/bot/performance/recent`), `gld-compat-matrix.yml` (`/api/bot/accounts/balances`), `live-replay-parity.yml` (`/api/bot/candles`, local copy `127.0.0.1:18001` + public), `deploy-candidate.yml`/`vm-caddy-deploy.yml` (`/api/bot/stats`) | none seen | **401 → NEEDS the `DASHBOARD_API_TOKEN` bearer** (GET only). Caddy saw `Python-urllib/3.11` from two GitHub runner IPs GETting `/api/bot/candles` with no credential. |
| 11 | **Anonymous GET scripts** (29 files, **UNVERIFIED each**): `scripts/ops/{ml_plan_status,strategy_liveness,verify_running_roster,target_expectation_coverage,digest_due,attention_watch,prop_silence,constraint_readout,check_ticket_package_divergence,snapshot_soak_state_for_mandate}.py`, `scripts/check_web_api.py`, `scripts/research/{live_vs_backtest,partial_close_reachability,research_watchdog,as_traded_stage0,live_bt_trade_join,real_money_close_attribution,prop_baseline_reconcile,counterfactual_grader,expectancyr_correction_matrix,r_sign_split_basis}.py`, `scripts/prop/trade_quality_review.py`, `src/prop/prop_status_request.py`, `src/runtime/wake_toggles.py` | `GET /api/bot/*` | none seen in the file | **NEEDS the bearer** on GETs (retrofit by one shared helper). Includes `prop_silence.py` and `prop_status_request.py` on loopback. |
| 12 | **Health / edge probes** (`ci-settled`, `vm-net-diag`, `vm-web-api-recover`, `fix_data_dir.sh`, `restart_web_api.sh`, `deploy/ict-web-api-watchdog.service`, `dashboard-edge-watch.yml`) | `GET /api/health`; watchdog also `/api/bot`, `/api/diag` | none (health) | `/api/health` public. `dashboard-edge-watch.py` also hits `/api/bot/stats` (`scripts/ops/dashboard_edge_watch.py`) → **bearer**. Confirm the watchdog's `/api/bot` call. |
| 13 | **Sandbox proxy credential** (`ict-bot.duckdns.org`, proxy-injected) | whatever a session calls | the proxy injects a header (**UNVERIFIED which**; `X-Diag-Token` exists because it clobbers `Authorization`, `diag.py:1413`) | A session GET to a non-diag route needs `DASHBOARD_API_TOKEN` — check what the proxy injects before relying on it. |
| 14 | **`live_review` / desk wakes** (`src/runtime/desk_packet_wake.py`, `short_hold_wake.py`) | `/api/diag/log_file`; `short_hold_wake` unknown | diag | diag public; `short_hold_wake.py` grep found no URL — **UNVERIFIED**. |
| 15 | **Unknown / external** | – | – | Caddy evidence below shows one Android browser (`Mozilla/5.0 … Android`, SPA) and nothing else foreign. No access log exists (below). |

Not consumers: `.mcp.json` `github-actions` (talks to GitHub, not this API).

## 3. Caddy evidence (read via the diag relay, read-only)

* `GET /api/diag/journalctl?unit=caddy.service&lines=500` works (`lines=500` ok; `since=24h` returned HTTP 400 here). Window returned: `2026-11-10T17:02Z → 2026-11-11T14:43Z`, **145 lines, not an access log**: `deploy/caddy/Caddyfile` has no `log` directive, so Caddy only emits warnings. 134 of the 145 are `aborting with incomplete response`
  (a request is logged only when the client disconnected mid-response) and 9 are `dial tcp 127.0.0.1:8001: connect` errors. **Population: aborted requests only → absence of a consumer here proves nothing.**
* Observed (aborted requests only): `curl/7.81.0` from `141.145.193.91` (the VM itself) on `/api/diag/{journal,bybit_open_orders,position_telemetry,alpaca_open_orders,ib_open_orders,audit_query}` carrying `Authorization`+`X-Diag-Token` (public prefix, fine);
  `Python-urllib/3.11` from GitHub runner IPs on `GET /api/bot/candles`, **no credential**; `curl/7.81.0` loopback `GET /api/bot/prop/tickets`, no credential (**consumer 3/11 gap**);
  `curl/8.5.0` from `160.79.106.134` `POST /api/bot/work/items/<id>/note` with `X-Work-Store-Token`; one Android browser `GET /api/bot/strategies` with `Authorization`.
* ⚠️ **SECURITY FINDING (filed, not fixed here):** those Caddy warn lines log request headers and the **`X-Diag-Token` value appears in plaintext** (only `Authorization` is redacted). Anyone holding `DIAG_READ_TOKEN`-class read access to `journalctl` can read it — it is the diag credential itself. Fix is a Caddy `log { … request>headers>X-Diag-Token delete }` / `servers { … }` header redaction (Tier-2 Caddyfile deploy via `vm-caddy-deploy`) **and a rotation of `DIAG_READ_TOKEN`** (`set-diag-token`) since it has been in a journal readable through the relay. The value is deliberately not copied into this repo. Same fix doubles as the access log wanted below: add `log` with redaction.
* **How to get the real 24 h list:** (1) deploy a Caddyfile `log { output file /var/log/caddy/access.log; format json; … redact credential headers }` via `vm-caddy-deploy`; (2) read it through `/api/diag/log_file` if that route allows the path, else `journalctl -u caddy`; (3) after ≥24 h aggregate `(method, path-pattern, user-agent, client_ip, header-present)`. Until then this inventory is **static (grep) + a partial runtime sample** and cannot prove completeness.

## 4. Retrofit list (who needs what before the flip)

**A. Needs a new public-path carve-out (POST routes that already fail closed on their own token — mirror `prop/report`; one small `SITE_PUBLIC_PATHS` edit, Tier-3 auth surface):**
1. `POST /api/bot/alerts` (alert posters #6; `DASHBOARD_API_TOKEN`)
2. `POST /api/bot/work/decision` (Telegram bot #5; `DASHBOARD_API_TOKEN`)
3. `POST /api/bot/work/items`, `/items/{id}/set|note|close` (#7; `WORK_STORE_TOKEN`) — `GET work/items` is a read the gate should keep guarded, so carve out by **method** (public for POST only); decide in the build lane.
4. `POST /api/bot/wake-toggles` (console MCP #8; `WAKE_TOGGLES_WRITE_TOKEN`)
   *Alternative:* extend `_service_token_ok` to accept the service token on POST for these exact paths. Rejected as the default: it widens a token that is read-only by design.

**B. Needs `Authorization: Bearer $DASHBOARD_API_TOKEN` added to GETs (service bearer):**
`r4-demotion-gate.yml`, `gld-compat-matrix.yml`, `live-replay-parity.yml` (public `candles` call), `deploy-candidate.yml` + `vm-caddy-deploy.yml` (`/api/bot/stats`), `dashboard-edge-watch.py`, `digest_due.py`, `attention_watch.py` (alerts GET), `src/runtime/wake_toggles.py` (GET `wake-toggles`, runners), work/brief readers (`snapshot_soak_state_for_mandate.py`, `scoreboard.py`), `prop_silence.py`, `prop_status_request.py`, `check_ticket_package_divergence.py`, and the other #11 scripts after a per-file check. Cheapest route: one shared `scripts/ops/_api_auth.py`/shell helper that every direct call goes through, plus a guard that fails CI on a new direct `ict-bot.duckdns.org/api/bot` call without it. Each workflow needs `DASHBOARD_API_TOKEN` in its `env:` (secret exists).
**C. No change:** SPA (session), phone executor, prop report, all `/api/diag/*` relays, `/api/health`.

## 5. Ordered steps to switch on safely (nothing here is done)

1. **Access log first** (Tier-2): Caddy `log` with header redaction + rotate `DIAG_READ_TOKEN` (§3 finding). Collect 24 h (ideally 72 h, to include the weekly workflows `weekly-audit`, Mon `research-ops` 4×/day, and the Wed/Sun reviews).
2. Diff the log against §2; update this file; every unmatched `(UA, path)` becomes a row.
3. Land the `app.routes` anonymous-walk regression test (design §1 item 1) and the **A-list carve-outs** (Tier-3, operator-approved design). Add a test that `POST`s each A route with the gate on and no site credential and expects the router's own 401/503, not the gate's.
4. Land the **B-list bearer retrofit** (Tier-1 scripts/workflows) + the new-direct-call guard.
5. Deploy, then **verify with the gate still OFF** that each retrofitted consumer still returns 200 (they already send a token the gate ignores) — proves the retrofit before it matters.
6. Dry-run the gate: with the code deployed, run each consumer's call against a local instance (`SITE_AUTH_ENFORCE=1`, loopback test app) from CI; one deliberately tokenless probe must 401 (negative control).
7. Operator observes the second-Google-account `403` (closes `UI-UPGRADE-1-AUTH`), then `set-env SITE_AUTH_ENFORCE=1` (operator act). Rollback: unset the var; no deploy.
8. After the flip, watch the access log + `/api/bot/alerts` ledger for 401s per consumer for 24 h; each 401 from a known consumer is a missed retrofit.

## 6. Not established (honest limits)

* Completeness of the consumer list: no access log; the Caddy sample is aborted requests only, ~21 h.
* Per-file auth for the 29 "no credential seen" scripts (some may only read a file fetched elsewhere).
* Which header the sandbox proxy injects for `ict-bot.duckdns.org`; whether `short_hold_wake.py` calls the API; whether the watchdog's `/api/bot` call carries a token; whether every `/api/diag/*` route calls `_require_diag_token` (design §1 already flags it).
