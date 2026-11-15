# UI workplan, 2026-11 — design for nine UI / work-surface rows

> **PLAN STATUS: `superseded`**
> **Superseded by:** `docs/design/ui-redesign-2026-11-reconciliation.md`
> Written without the operator's wording (see § 0). Its behaviour sections bind only where the reconciliation says **stands**; the operator spec is row `UI-REDESIGN-2026-11`.

> **Doc status:** `superseded` · category `architecture` · last verified `2026-11-12` · superseded by [`docs/design/ui-redesign-2026-11-reconciliation.md`](ui-redesign-2026-11-reconciliation.md) · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes: none.** Every item below is a read surface, a Tier-1 store, or arms an already-built switch
> (`SITE_AUTH_ENFORCE`) that is Tier-3 on its own row. Nothing here touches an order path, a risk cap, or a strategy.

Dispatched by Manager Session 2026-11-09a on the operator's ask of 2026-11-11. **DESIGN ONLY.** Build lanes start from the *Build order* (§ 11).

## 0. How this was written — read first

* **MEASURED, 2026-11-11, `origin/main` = `dd61c6306`:** none of the nine named rows exist in `docs/claude/work/checklist/`
  (`git ls-tree` over `origin/main`: no `UI-OAUTH-SIGNIN`, `PROP-UI-BRACKETS-CLOSED`, `UI-CHART-BRACKET-HISTORY`,
  `PERF-PAGE-CATEGORY-TABLE`, `PERF-PAGE-PNL-CHART`, `INSIGHTS-LEDGER`, `UI-MODELS-STRATEGIES-TABLES`,
  `UI-SIDEBAR-COLLAPSE-DESKTOP`, `WORK-TOPIC-TAXONOMY`; `git grep` for the ids is empty). `checklist.py` has no `get` subcommand either.
  So I could not read the operator's verbatim wording. **The behaviour below is inferred from the row ids and the dispatch text.**
  The manager must create the rows (`checklist.py add`) before the `note` step; I could only note rows that exist (§ 12).
* **The SPA repo was not reachable** (`benbaichmankass/ict-trader-dashboard`; the session scope is `JTA-Trader` only; a prior lane was denied
  `add_repo` for it, row `UI-UPGRADE-1-AUTH`). SPA-side work is therefore specified against **this repo's API**. Where the SPA's current
  components matter (sidebar, tables), I say *"read the SPA first"*.
* Marking: **MEASURED** = read in code/data this session, with the path. **PROPOSED** = design. **UNVERIFIED** = not checked.

---

## 1. UI-OAUTH-SIGNIN

**Finding (MEASURED):** the operator's Google sign-in already exists and is live, gate off. Row `UI-UPGRADE-1-AUTH` (`landed_unproven`, tier 3)
+ `-CONFIG` + `-SPA` (done): Google ID token → 5-min pre-auth ticket → WebAuthn passkey → 30-day sliding **device session** (`ws_…`, hashed in
`trade_journal.db::web_sessions`), SPA sign-in screen live (dashboard #222/#223), operator signed in 2026-10-12 13:40Z (Android) and desktop via phone passkey.
`src/web/api/auth.py::require_site_session` is an **app-level dependency** (`main.py`: `FastAPI(dependencies=[...])`) so it covers **every HTTP route and
`WS /ws/market`, including routes added later (default-deny)**. It is a no-op until `SITE_AUTH_ENFORCE` is set. So the row is mostly **"turn the existing gate on,
safely"**, not "build OAuth".

**User-visible behaviour (PROPOSED):** an anonymous browser (or `curl`) gets the SPA sign-in screen / `401 {error}` on every `/api/*` route except the public list; the operator
signs in once per device (Google + passkey), stays signed in 30 days sliding, can list/revoke devices. A second Google account gets `403 email_not_allowlisted`.

**How API routes check the session, not just the page (MEASURED, `auth.py:255-300`):** `Authorization: Bearer ws_…` → `web_sessions.validate_session` → row must still
satisfy `email == ALLOWED_EMAIL` (de-allowlisting kills all sessions). WebSocket: single-use `?ticket=` from `POST /api/auth/ws-ticket`. `OPTIONS` passes. Service credential:
`DASHBOARD_API_TOKEN` accepted **for GET/HEAD only**. The SPA is a static page on GitHub Pages — a page-level guard would protect nothing; the check lives in the API.

**Public paths when on (MEASURED, `auth.py:216-231`):** exact `/api/health`, `/api/bot/prop/report`; prefixes `/api/auth/`, `/api/diag/`, `/api/bot/prop/phone/`.

### Candidate approaches

| | approach | CORS | diag / phone / other clients | verdict |
|---|---|---|---|---|
| **A** | **Enforce the existing Google + passkey device-session gate** (`SITE_AUTH_ENFORCE=1`) | none: `allow_headers` already has `Authorization`; bearer, not cookies, so no `SameSite`/credentialed-CORS change | diag keeps `DIAG_READ_TOKEN`; phone keeps `DASHBOARD_API_TOKEN`; read-only service consumers use `DASHBOARD_API_TOKEN` GET | **RECOMMENDED** — built, observed signing in, zero new auth code except the HARDEN items |
| B | Reverse-proxy auth in Caddy (oauth2-proxy / Cloudflare Access) | breaks browser-direct: the proxy redirects XHR to a login page (CORS failure); needs same-origin SPA | every non-browser client needs a bypass rule | reject: re-architects "SPA browser-direct, CORS load-bearing" |
| C | Same-origin SPA + `HttpOnly` session cookie | needs SPA moved behind the API host, `allow_credentials` + `SameSite` rework, CSRF on POST | phone/diag unchanged | reject for now: design §2 D4 "same-origin" was explicitly deferred by the operator |

**Impact checklist (A):**
* **CORS** — unchanged. Caveat (MEASURED, `main.py:90`): `allow_methods=["GET","POST"]`; every new write below must be a POST (the revoke route is already a POST twin for this reason).
  A 401 from a route behind `CORSMiddleware` still carries CORS headers (middleware is outermost) — acceptance test checks it, otherwise the SPA sees an opaque network error instead of 401.
* **Diag token** — `/api/diag/*` is *exempt* from the site gate and enforced inside the router (`diag.py:1406 _require_diag_token`; 503 if unset). Unchanged. **UNVERIFIED:** that *every* diag route
  calls it (a route that forgets would be open *because* the prefix is public). Build lane adds a test that walks `app.routes` under `/api/diag/` and asserts 401/403/503 anonymous.
* **Phone executor / prop write** — `/api/bot/prop/phone/*` + `/api/bot/prop/report` stay public at site level and rely on the bearer **inside** prop.py (`prop.py:58-67`, fail-closed 503 when unset, MEASURED).
  Same anonymous-walk test over those prefixes. **Do not** put `ws_` sessions on the phone path.
* **Other API clients (the real blocker):** the row's own inventory (`UI-UPGRADE-1-AUTH` note; pipeline `PI-20261011-CFUJ7YFR-0001` / `-0002`) found **26 anonymous consumer groups** and **Caddy has no access log**,
  so consumers cannot be enumerated from traffic. Known/likely: the console MCP connector (`mcp…7f24194c` "JTA Trader console data" — **UNVERIFIED how it authenticates**), GitHub Actions diag relays (use diag token),
  `scripts/ops/diag_fetch.sh`, health/uptime probes, `ict-git-sync` local calls, trainer VM → live VM reads, the sandbox's proxy-injected `ict-bot.duckdns.org` credential (**UNVERIFIED** which header it injects).
  Enforcing without the retrofit will silently 401 these.
* **Tier:** Tier-3 (auth surface on a live system; operator already approved the design and D1–D3). The flip is the operator's `set-env`, per the row.

**Backend vs SPA:**
1. Backend (Tier-2 deploy of Tier-1-class code): reopen & land `UI-UPGRADE-1-AUTH-HARDEN` items (a)–(h) (currently `dropped` by the 2026-10-29 bulk reset, "value unknown" — **the value is now known; set `queued`**); the `app.routes` anonymous-walk test (new, default-deny regression test).
2. Tier-2: Caddyfile access log (PI-…-0001), then 24 h of logs → consumer list.
3. Backend: service-bearer retrofit for each consumer found (PI-…-0002) — send `Authorization: Bearer $DASHBOARD_API_TOKEN` (GET only).
4. SPA: nothing for sign-in (done). Verify: 401 handler routes to the sign-in screen, `ws-ticket` URL for `/ws/market`.
5. Operator: second-Google-account `403` observation (closes `UI-UPGRADE-1-AUTH`); then `set-env SITE_AUTH_ENFORCE=1`.

**Acceptance:** anon `curl` over a route-enumerated list → 401 for every route outside the 2 exact + 3 prefix public set, and the diag/phone/report anonymous walk → no 2xx; signed-in `ws_` → 200 on `/api/bot/stats` and WS connects with ticket; `DASHBOARD_API_TOKEN` GET → 200, POST → 401; revoked device → 401 next request; every consumer from the access-log inventory still 200 post-flip (negative control: one deliberately tokenless probe → 401); SPA loads signed-in on desktop + Android; rollback = unset the env var (merged ≠ deployed ≠ observed — state which).

---

## 2. PROP-UI-BRACKETS-CLOSED

**Behaviour (PROPOSED, inferred):** on the SPA's prop views, a **closed** prop trade shows its final **SL and TP** (and where they started, if they moved), the way open prop trades already do.

**Data source (MEASURED):** `prop_journal.db` tables `prop_fills` (`sl`, `tp`, `amendments` TEXT JSON list, `status`) and `prop_tickets` (`sl`, `tp`, entry intent). Read route exists:
`GET /api/bot/prop/fills?account_id=&limit=` → `{present, count, trade_open_count, fills:[…]}` (`prop.py:110`), rows are fill **events** (an opening row keeps `status:"open"` after the trade closes — use `trade_state`, which
`annotate_trade_state` sets). `prop_journal.amend_fill_levels` (`prop_journal.py:712`) is the **only** writer of before/after stop/target history (appends `amendments` entries).
**UNVERIFIED:** whether `list_fills` already returns `amendments` and `tp` for closed rows, and whether a closed row's `sl`/`tp` is the *final* level or the opening one (`insert_fill`'s idempotent UPDATE "rewrites every mutable column").
**First build step = read one closed `prop_fills` row per prop account via `diag_fetch.sh` and write down which columns are populated** (known gap: `tradeify_1` / `velotrade_1` positions are unreadable in executor status, `milestones.yaml` G2 baseline).

**Split:** Backend (Tier-1): if `amendments`/`tp` are absent from `/fills`, add them (`amendments` parsed to a list; `read_state: "no_record"` when null — never `[]` for "unknown") and add `entry_sl`, `entry_tp` (from the linked `prop_tickets` row via `ticket_id`) beside `final_sl`, `final_tp`. SPA: show final levels on closed rows, "—" when null, a tooltip listing amendments.
**Depends on:** nothing. Feeds § 3 (prop half of bracket history). **Tier 1.**
**Acceptance:** for each prop account with ≥1 closed trade, SPA row's SL/TP equals the DB row (spot-check by `diag` query, arithmetic: closed count in UI = `trade_state=='closed'` count from the route); a closed trade with null levels renders "—".

---

## 3. UI-CHART-BRACKET-HISTORY

**Behaviour (PROPOSED):** on the price chart for a trade/position, draw the **main** SL and TP lines (the level currently in force, or the final one for a closed trade) in normal styling, and each **earlier** level as a **subtle** line (thin, dashed, low opacity) from the time it was set until it was replaced; at each update a **marker on the bar** at the update time (▲/▼ for stop tighten/widen, ◆ for TP move) with hover = `from → to · source · detail`.

**Where bracket-update history lives today, per account class (MEASURED):**

| class | store | content | gaps |
|---|---|---|---|
| **real money / paper (exchange accounts)** | `order_packages.meta` JSON: `sl_moves` (list, **capped at 20**: `{ts, from, to, source, detail}`) + `last_sl_move`, stamped by `src/runtime/sl_mover.py::stamp_sl_move`, `source ∈ {structure_exit, strategy_monitor, live_review_apply}` (since 2026-11-06) | **SL only** | (1) **no TP history** in `sl_moves`; (2) cap of 20 drops oldest on a trailing package; (3) packages before 2026-11-06 have none (no row ≠ "never moved", see `last_sl_move_ts` docstring); (4) a netted position carrying several packages has one history per package |
| exchange accounts, **path** | `position_path_history` (append-only, one row per `(order_package_id, bar_ts)`; the bar-by-bar state incl. R distances; BRACKET-ADVISOR-SHADOW columns added) | per-bar state, **may include the stop in force per bar — UNVERIFIED, read the table schema** | pruned (`prune_history`) — retention unstated here |
| **venue truth** | `venue_protection_snapshot` — LATEST venue read per `(order_package_id, account_id)` | what the venue was resting | latest only, no history |
| **directed / live-review applies** | `live_review_apply` + `comms/directed_actions/<id>.json` receipts (diag `log_file?name=directed_actions`) | each amend with operator quote and read-back | event log, not keyed for chart joins |
| **prop** | `prop_fills.amendments` JSON list written by `prop_journal.amend_fill_levels` — `{before/after sl, tp}` per call | **SL and TP**, before/after | whether each entry has a timestamp: **UNVERIFIED** (read `prop_journal.py:740-770` first); prop levels move via the phone executor / `phone_trail`, a manual bridge — an amend that never reached the journal is invisible |

**Data contract (PROPOSED), one normalised read route:** `GET /api/bot/brackets/history?trade_id=<id>` (also `?order_package_id=`) →
```
{ as_of, trade_id, account_id, account_class, read_state: "measured"|"partial"|"no_record",
  levels: [ { kind:"sl"|"tp", price, from_ts, to_ts|null, source, detail, provenance } ],   // to_ts null = still in force
  updates: [ { ts, kind, from, to, source, detail, bar_ts } ] }                            // one marker per update
```
Builder (new `src/web/api/brackets_history.py`, Tier-1, read-only) merges `order_packages.meta.sl_moves`, `prop_fills.amendments`, `position_path_history` (to reconstruct TP where only the path has it) and the opening `sl`/`tp`.
`read_state:"partial"` whenever the 20-cap was hit or the package predates 2026-11-06; **never fabricate a continuous line** (a level with unknown start renders from the open time with a "—" tooltip and `provenance: ESTIMATED`).
`bar_ts` = update `ts` floored to the chart interval so the SPA places the marker on the right bar.

**Closing the TP gap (Tier-2, optional but needed for an honest chart):** extend `stamp_sl_move` to a sibling `stamp_tp_move` writing `meta.tp_moves` at every TP write (TP doctrine "prediction moves through the trade" makes TP updates real). Off the order path (meta only) but runs in `order_monitor._apply_update` → treat as Tier-2, one operator OK.

**Split:** Backend: route + builder (Tier-1), `tp_moves` (Tier-2). SPA: chart overlay (Lightweight Charts `createPriceLine` for main; `LineSeries` stepped segments or short `PriceLine`s for history; `setMarkers` for bar markers — **read the SPA chart component first**, specs `UI-CHART-CRYPTO-LIVE` etc. own the chart). **Depends on** § 2 (prop data) and the `UI-CHART-*` rows. **Tier 1** (+ Tier-2 for `tp_moves`).
**Acceptance:** pick the 2026-11-06 ADAUSDT `pkg-78342b614f6040f6` (stop 0.18747 → 0.186646 at 08:00Z): chart shows the old level subtle, new level main, one marker on the 08:00 bar; a prop trade with an amendment shows its SL/TP step; a package without records renders the main lines only, no markers, and the tooltip says "no record".

---

## 4. PERF-PAGE-CATEGORY-TABLE

**Behaviour (PROPOSED):** a Performance page table, one row per **category**, a window selector (7d / 30d / 90d / all), a "measured only" toggle, a dash for any null.
**Categories (derive from `config/accounts.yaml`, never hard-code counts):** `real_money` (bybit_2, alpaca_live), `real_mirror` (bybit_portfolio, alpaca_portfolio), `paper` (bybit_1, alpaca_paper, ib_paper), `prop` (breakout_2, tradeify_1, velotrade_1), `prop_dry`/other excluded and named. `account_class_wire` in `_clean_trades.py` already maps real vs paper; **prop and mirror are not in it — Backend adds them.**

**Data source:** new `GET /api/bot/performance/categories?window=` (a sibling of the existing `/api/bot/performance`, which is real-money-top-level + `paper`/`demo` sub-blocks and returns **HTTP 400 on an unknown window** — copy that rule). Reads `trade_journal.db::trades` (closed, non-backtest, `exclude_superseded`), `order_packages` (entry/risk), `balance_snapshots` (equity, via the same source as `/api/bot/accounts/balances`), and `prop_journal.db::prop_fills` for the prop category. Existing implementations to **reuse, not rewrite**: the perf-review metrics in `docs/reviews/2026-10-15-weekly-walkthrough-perf.md` § 2 (`$/day`, `bps/notional-day`, `R/cap-day`) and `src/runtime/provenance.py`.

**Exact metric definitions** (every row also returns `n_closed`, `n_priced`, `n_r_graded`, `window`, `population`):

| column | definition | provenance (per `provenance.py`) |
|---|---|---|
| `n_closed` | closed trades in window with `closed_at` in window, backtests and superseded excluded | counted |
| `net_pnl_usd` | Σ stored `pnl` over rows where `pnl IS NOT NULL`, **split** into `measured_usd` (rows `classify_pnl == MEASURED`) and `not_measured_usd` (ESTIMATED + FABRICATED + UNVERIFIED), each with its row count | headline = `measured_usd`; the split is shown, never folded (Rule: UNVERIFIED never folded into measured) |
| `win_rate` | wins ÷ priced closes, wins = `pnl > 0`, over **measured** rows | MEASURED; null if `n_priced < 1` |
| `avg_realised_r`, `expectancy_r` | mean of `pnl ÷ risk_usd` over R-graded rows (risk from the package: `|entry−sl|×qty`); `n_r_graded` shown | ESTIMATED when risk reconstructed from a moved stop (stop moved ⇒ entry risk unknown unless `sl_moves[0].from`/opening `sl` is read — use the opening stop); null when `n_r_graded < 1`; **flag `insufficient_n` at < 10** (the perf-review `--min-n`) |
| `profit_factor` | Σ wins ÷ |Σ losses|, measured rows | MEASURED; null if no losses (never ∞/0) |
| `fees_usd`, `funding_usd` | Σ from the journal columns/notes | MEASURED where the venue fill gave them, else null — **verify columns exist (UNVERIFIED)** |
| **`capital_utilisation`** | **time-weighted fraction of the category's capital that is deployed:** Σ over closed trades of (`|qty × entry_price|` × hold_days) ÷ (Σ over accounts of mean equity over the window × window_days). *Gross notional-days ÷ equity-days.* May exceed 1.0 (leverage) — that is information, not an error. Open positions are included at mark to the window end so the number is not biased low by excluding in-flight trades. | **ESTIMATED**: numerator MEASURED (qty/entry from the journal), denominator = mean of hourly `balance_snapshots` (a sampled series); **null** if the category has < 24 snapshots in the window or an account lacks any snapshot ("no_equity_record"); paper ib/alpaca notionals are inflated vs real money (perf-review caveat) so paper carries a flag |
| **`return_on_time_in_trade`** | **net P&L earned per unit of capital-time actually at risk:** `Σ net_pnl ÷ Σ(|qty × entry| × hold_days)`, shown as **bps per notional-day**, plus the annualised figure ×365 as a tooltip. This is the perf review's existing `bps/notional-day` (so no new definition to drift); `hold_days = (closed_at − opened_at)` in days, fractional. Companion `r_per_cap_day` = Σ realised R ÷ Σ hold_days (existing). | **ESTIMATED** when any contributing row's pnl is not MEASURED → show the **measured-only** value in the cell and the all-rows value in the tooltip; null if Σ notional-days = 0 or `opened_at`/`closed_at` missing on any row (counted in `n_no_hold`) |
| `avg_hold_days` | mean `hold_days` | MEASURED from timestamps |

**Population line (Rule: state the population):** the table footer prints `window · accounts included · n_closed · rows excluded (null pnl, superseded, backtest)`.

**Split:** Backend builds the route + a pure `src/runtime/perf_category.py` (so the perf review and the page share one definition; a test asserts the page's `$/day` equals the review script's for the same window — **the cross-check**). SPA renders table, dash for null, tooltips with the definitions above. **Depends on:** nothing (needs § 3's none). **Tier 1.**
**Acceptance:** for one category and 30d, hand-recompute net P&L, `n_closed`, and `bps/notional-day` from a raw `diag` query and match to rounding; `measured + not_measured == net` exactly; a category with no equity snapshots shows "—" for utilisation, not 0; `window=90d` works and `window=zz` is 400; real_money R-graded n < 10 renders the `insufficient_n` badge.

---

## 5. PERF-PAGE-PNL-CHART

**Behaviour (PROPOSED):** a cumulative-return line per category over time; y-axis in **% of that category's capital**, **$ shown on hover** (and `n` trades that day); filters below.

**% denominator per category (PROPOSED, flagged for the operator, § 13 Q3):** **capital base at window start** = Σ over the category's accounts of the equity from the `balance_snapshots` row nearest at-or-before the window start (first row in window if none earlier, flagged). So `pct = cumulative_net_pnl ÷ start_capital`. This keeps curves comparable across categories and windows and does not let early gains inflate later %.
For `prop`: the firm account's **starting balance** (the evaluation size from `config/prop_rulesets/`), because the firm's DD limits are quoted against it. For `paper`: the configured paper balance, labelled ESTIMATED (paper notionals are inflated). Null denominator → the line is drawn in $ only and the axis is labelled "$ (no capital record)"; never 0%.

**Data range:** `7d | 30d | 90d | all`; `all` starts at the category's first closed trade, capped at 400 days (the `MAX_DAYS` of `pnl_history.py` is the existing ceiling — **read it**). Daily points (UTC) for ranges ≥ 30d, per-trade points for 7d.
**Filters:** category (multi), account, strategy, symbol, asset class, **"measured only"** (default ON: excludes ESTIMATED/FABRICATED/UNVERIFIED rows; a dotted second line shows the all-rows curve so the gap is visible).
**Data source:** extend `GET /api/pnl/history` (flat `[{date, pnl, trades}]` today, `days`, `account_id`) **additively** (same rule as `/performance`: the old shape must not break the SPA) with a new `GET /api/bot/performance/pnl-series?window=&category=&account_id=&strategy=&symbol=&measured_only=` → `{as_of, window, population, series:[{category, start_capital_usd|null, read_state, points:[{date, pnl_usd, cum_pnl_usd, cum_pct|null, n}]}]}`. Daily bucket uses `_closed_at.close_time_sql` (same close time as the rest of the system).
**Split:** Backend route (reuses § 4's category map + `perf_category`); SPA chart (**read the existing Performance tab**: daily bars + cumulative line + drawdown already exist). **Depends on** § 4 (category map, denominator). **Tier 1.**
**Acceptance:** last point's `cum_pnl_usd` equals § 4's `net_pnl_usd` for the same window/category/toggle (the cross-check); hover shows $ and %; a category with no snapshot draws $ only with the "no capital record" label; changing the filter changes `population` text.

---

## 6. INSIGHTS-LEDGER

**What it is (PROPOSED):** a durable, queryable ledger of **insights** — findings the system or a session produced about performance, models, strategies — each **linked to the work that came of it**, so "what did we learn and what did we do about it" is one view. Not the existing `/api/bot/insights/*` (that is the AI-Analyst narrative cache under `runtime_logs/insights/`, file-based, no links — **MEASURED**, `insights.py`; do not overload it).
**Doctrine check:** a spec/memo that no row points at "is not work — it is a memo" (CLAUDE.md). Therefore the ledger is **not a new register**: it is the existing follow-through intake **`docs/claude/work/PIPELINE.jsonl`** (append-only; `scripts/ops/pipeline.py`; refuses rows without `due_when`, `origin.rerun`, and `terminal_reason` to close) **plus a thin read view**. Adding a parallel store would resurrect a retired register (`OPEN-ITEMS.json` etc. are retired — do not).
**Store / schema (PROPOSED, additive fields on pipeline rows, no new file):** `kind: "insight"`, `claim` (one sentence), `population` (RULE: always state it), `provenance` (MEASURED/ESTIMATED/UNVERIFIED), `evidence` (path/commit/diag query), `topic` + `subtopic` (§ 10 taxonomy), `roadmap` (milestone id), `links: [{type:"row"|"unit"|"pr", id}]`, `outcome` (`acted|filed|killed|open`) with `terminal_reason` on close. **Who writes:** any lane via `pipeline.py` (the existing guard enforces the schema); perf/health/ml reviews already file here — they add `kind:"insight"` rows rather than prose. **Links to rows/units:** `links` hold ids; a **guard** `insight-link-guard` (new, Tier-1 CI) fails if an `acted` insight names a row/unit id that does not exist (pattern of `pipeline-guard`).
**Read:** `GET /api/bot/work/ledger?topic=&subtopic=&outcome=&roadmap=` — a filter over the pipeline rows the work router already reads (`work.py`, `/brief` renders due items from the same file). The SPA tab lists insights grouped by topic with their linked rows' live state (join to `/api/bot/work/checklist`).
**Split:** Backend: schema doc + `pipeline.py` accepts `kind:"insight"`+fields (Tier-1), guard, read route. SPA: ledger tab. **Depends on:** § 10 (topic taxonomy). **Tier 1.**
**Acceptance:** file one insight via `pipeline.py` with a link to a real row → it appears in the route and tab with that row's current state; a dangling link fails the guard; an insight with no `population` is refused.

---

## 7. UI-MODELS-STRATEGIES-TABLES

Extends open row `UI-CATALOG-STRATEGIES-ML` (queued; operator 2026-10-29: a card per item, status indicator, ML weights, strategy rules, comparison stats, hover-to-learn). This row is the **table view**: one sortable table for strategies, one for models.
**Strategies table — columns / source (MEASURED sources):** `name` · **status** (`testing|production|inactive`, **derived** by `scripts/ops/strategy_status.py`, never stored) · accounts it trades (`config/accounts.yaml` roster) · `execution` live/shadow (`config/strategies.yaml`) · timeframe, symbols (`/api/bot/strategies`, `strategies.py:364`) · n closed, win rate, total/avg P&L, exit-reason mix (`stats` in the same response, already there) · **category-level numbers from § 4 per strategy** (return on time in trade, R/cap-day) · TP-doctrine compliance (`scripts/ci/check_tp_doctrine.py` output — **re-run, never quote**) · `description.short` (+ hover `how_it_works`). **Backend gap:** `status` and the § 4 metrics are not in `/api/bot/strategies` → add `status` + `perf` blocks (additive).
**Models table — source:** `GET /api/bot/training/registry` (`training_center.py:334`: registry rows + `linked_strategies`), `/shadow/stats`, `/shadow/drift`; display names from `docs/reference/model_names.yaml` (row `MODEL-NAMES`). Columns: display name, family, stage (candidate/shadow/advisory), linked strategies, train date, headline metric + its population, drift state, weights link (operator ask).
**Rules:** null → "—"; every number has population + provenance on hover; **no stage/promotion control** on the table (read surface).
**Split:** Backend adds the two additive blocks; SPA builds the tables (reuse the card data, **read the SPA**). **Depends on:** § 4 (per-strategy metrics) for the performance columns — the rest can ship first. **Tier 1.** **Acceptance:** row count equals roster count from `accounts.yaml`/registry (re-parsed, not quoted); a leg's status in the table equals `strategy_status.py` output; a model with no drift reading shows "—".

---

## 8. UI-SIDEBAR-COLLAPSE-DESKTOP

**Behaviour (PROPOSED):** on desktop widths the left navigation can be **collapsed to an icon rail** and re-expanded; state persists per browser; mobile behaviour is unchanged (the mobile nav/Settings gear shipped in dashboard #223).
**Data/backend:** none. **SPA only**, pure UI: toggle button + keyboard shortcut, width transition, tooltips on icons when collapsed, `localStorage` for the choice (wrapped in try/catch — it may be unavailable), default expanded, layout reflow of the content area (charts must `resize()` on the transition end — Lightweight Charts does not auto-resize).
**Dependencies:** none; independent of every other row. **Tier 1.** **Acceptance:** collapse/expand at ≥1024 px; reload keeps the state; at <1024 px the control is absent and the mobile nav is unaffected; the chart fills the freed width without a reload; keyboard-focus order sane. (This is the cheapest row; a build lane can take it tonight with no backend.)

---

## 9. Cross-cutting rules for every item above

* null renders **"—"**, never 0/"unknown"; every new count that can be "could not look" carries an explicit `read_state` (`scripts/ci/check_collapsed_states.py`).
* New routes are **GET** (CORS allows GET/POST only) and add themselves to `docs/reference/bot-api-reference.md`; they sit behind the site gate with no special-casing (default-deny).
* Reuse `src/runtime/provenance.py` (`classify_row`, `classify_pnl`, `coverage`); do not add another `exclude_*` predicate.
* Windows: unknown token → HTTP 400 (the `/performance` rule).

---

## 10. WORK-TOPIC-TAXONOMY — draft topic map (every milestone in `docs/roadmap/milestones.yaml`)

**Purpose (PROPOSED):** the `topic`/`subtopic` facet for rows, units, pipeline rows and insights (§ 6) so the Work page groups by *subject*, not by goal id. One topic per milestone (the `roadmap` field already on every row resolves row → milestone → topic, so **no row needs a new field**); subtopics are optional refinements. Computed, never typed on the row (like the roadmap counts).
**Coverage MEASURED (script, 2026-11-11):** `milestones.yaml` has 36 milestones; the table below has 36 rows and the id sets are identical (none missing, none extra). The build lane's guard: `topic-map-guard` fails when a milestone id in `milestones.yaml` has no entry here (and the other way round).

| milestone id | status | **topic** | subtopic |
|---|---|---|---|
| L-AM-STANDARD | active | Trade management | active management standard |
| L-ATM | active | Trade management | brackets as predictions |
| M20 | closed | Trade management | exits & TP doctrine (merged into L-ATM) |
| M31 | closed | Trade management | position telemetry (merged into L-ATM) |
| L-LADDER | active | Strategy lifecycle | promotion ladder |
| M21 | closed | Strategy lifecycle | entry refinement |
| M22 | active | Strategies | pairs & small-timeframe |
| M27 | active | Strategies | scalp family |
| L-TIMEFRAMES | active | Strategies | horizon frontier |
| M18 | active | Portfolio & risk | allocator & arbitration |
| M16 | closed | Portfolio & risk | confidence risk architecture |
| M24 | closed | Portfolio & risk | net-R / cost-aware modelling (retired) |
| M15 | closed | Markets & venues | platform migration (retired) |
| L-PROP | active | Prop accounts | automate, protect, qualify |
| M39 | active | Plumbing & integrity | measurement invariants |
| L-ALERT-INTEGRATION | active | Plumbing & integrity | alerts & venue state |
| L-ML-LIVE | active | ML | ML in live loops |
| L-ML-MECE | active | ML | one owner per decision |
| L-ML-AGGREGATOR | backlog | ML | position aggregator (offline) |
| M25 | active | ML | promotion & consolidation |
| M23 | active | ML | meta-labelling & signals catalog |
| M14 | closed | ML | optimisation program |
| M9 | closed | ML | AI traders & HF/data pipeline |
| M26 | closed | ML | regime-transition intelligence (retired) |
| M41 | backlog | ML | local LLM |
| L-REGIME | active | Regime | regime program |
| L-DATA | active | Data | ingest/process/label/learn |
| L-DESK-V1 | active | Trading desk | V1 production-ready |
| L-DESK | active | Trading desk | Claude desk over lanes |
| L-PROGRAMMES | active | Research | programmes |
| M40 | active | Research | testing workflow & throughput |
| L-OPS | active | Operations | manager loop & cost discipline |
| M28 | active | Macro & value | value sleeve |
| M29 | dormant | Macro & value | system dynamics |
| M36 | closed | Macro & value | consolidation umbrella (retired) |
| M6 | active | Operator surfaces | web app & Telegram |

**Topics (15):** Trade management · Strategy lifecycle · Strategies · Portfolio & risk · Markets & venues · Prop accounts · Plumbing & integrity · ML · Regime · Data · Trading desk · Research · Operations · Macro & value · Operator surfaces (count by script over the table above).
**Open call:** `Regime` and `Data` could fold under `ML`; closed/retired milestones keep their topic so history groups correctly; items with **no** `roadmap` ref fall under `Unmapped` (visible, so the gap is a to-do, not hidden).
**Build:** Backend adds `docs/roadmap/topics.yaml` (milestone → topic/subtopic), `topic-map-guard`, and `topic`/`subtopic` on the work-route payloads (computed). SPA: Work page "group by topic". **Depends on:** nothing. **Tier 1.**
**Acceptance:** every milestone id maps (guard green); a row with `roadmap: L-PROP` shows under *Prop accounts*; an unmapped row shows under *Unmapped*, count printed.

---

## 11. Dependencies and build order (tonight → later)

```
Tonight, no backend, parallel:   UI-SIDEBAR-COLLAPSE-DESKTOP (SPA only)
Tonight, backend start:          PERF-PAGE-CATEGORY-TABLE (route + perf_category.py)        ─┐
                                 PROP-UI-BRACKETS-CLOSED (first: read one closed row/account) │
                                 WORK-TOPIC-TAXONOMY (topics.yaml + guard)                    │
                                 UI-OAUTH-SIGNIN prep: reopen HARDEN (a)-(h), anon-walk test, Caddy access log (Tier-2 OK)
Next:                            PERF-PAGE-PNL-CHART (needs category map)  ◄─────────────────┘
                                 UI-MODELS-STRATEGIES-TABLES (perf columns need the category metrics)
                                 UI-CHART-BRACKET-HISTORY (route+builder; needs prop data; tp_moves is Tier-2)
                                 INSIGHTS-LEDGER (needs topics)
Gated on the operator:           enforce flip (after HARDEN + 24 h consumer log + retrofit + 2nd-account 403 observation)
```

## 12. Row notes

The dispatch asks for `checklist.py note <ID> --append …` on each row. **MEASURED: the rows do not exist on `origin/main` at write time**, so the command would fail (`note` needs an existing id). The manager must `checklist.py add` them first; the one-line pointer to use is
`"Design: docs/design/ui-workplan-2026-11.md § <n> (UI-WORKPLAN-DESIGN 2026-11-11)"`. Whether the lane could note is reported in the trigger text.

## 13. Operator questions (only the operator can answer)

1. **Enforce window for the site gate (Tier-3):** after HARDEN + a 24 h Caddy-log consumer inventory + service-bearer retrofit, may the manager flip `SITE_AUTH_ENFORCE=1` without a further popup? (Otherwise it stays a per-flip OK.)
2. **Is anonymous read access wanted anywhere** (e.g. a public read-only dashboard view, or a link you share)? The gate is all-or-nothing today apart from the 2 + 3 public entries.
3. **% denominator:** is "capital at window start (hourly equity snapshot; prop = evaluation size; paper = configured balance)" the base you want, or the *current* equity?
4. **Prop TP/SL history:** prop levels move through the phone bridge; if an amend does not reach `prop_journal`, it is invisible — is it acceptable that the chart shows "no record" there, or do you want the phone executor to report every amend (Tier-2)?
5. **Category set:** are `real_mirror` (bybit_portfolio / alpaca_portfolio) and `prop` separate categories from `real_money` on the Performance page, or merged?
6. **Also — the nine row ids were not on `main`:** were they meant to carry operator wording I should have read (e.g. in an unpushed manager commit)?

---

## 14. FEATURES-CATALOG-UI-VERIFY (addendum 2026-11-11, manager request)

**Reading limits (stated first):** the SPA repo is unreachable, and the row `FEATURES-CATALOG-UI-VERIFY` is **not on `origin/main`** (`git ls-tree`: absent; same for `FEATURE-IMPACT-MAP`). So "what the Features sub-tab shows today" **could not be observed**. What follows is what the **API and data behind it** can and cannot support, MEASURED in this repo on 2026-11-11.

**The API route behind a Features catalog (MEASURED):** none. `grep -rn -i 'signal.catalog|signal_catalog' src/web src/runtime` finds **no consumer**; no router in `src/web/api/routers/` serves `docs/reference/signal-catalog.yaml`. The only `catalog` route is `GET /api/bot/research/catalog` (`research_catalog.py:56`) — research **units**, not features. Model data comes from `GET /api/bot/training/registry` (`training_center.py:334`: registry rows + `linked_strategies`). **So if the SPA shows a Features sub-tab today it is either static/bundled data or empty — UNVERIFIED; the first build step is to open the live SPA and note which request it makes (browser network tab) and from what path.** Do not assume it is fed by the API.

**The best existing data source (MEASURED):** `docs/reference/signal-catalog.yaml` (generated 2026-10-08; guard `scripts/ci/check_signal_catalog.py`, `signal-catalog-guard`): **335 inputs** (regime_macro 157 · ml 105 · strategy 73) and **76 `ml_models`** entries (manifest, family, dataset, stage, `features` list). Each input has `id, name, family, kind, definition, source (file:line), read_at, timeframe, freshness (prose), used_by, health{state,detail}`. Population of `health.state`: **unmeasured 241 · build_time_only 67 · batch_level_only 17 · measured 10** (so **only 10 of 335** have any freshness/null-rate metric).

**Does it cover every feature every live and candidate ML uses? NO — measured gaps:**
1. **The catalog is a hand-edited static YAML, generated 2026-10-08.** It predates the 2026-11 ENTRY models. `ml/served/` now holds `ml_decision_entry_v1`, `…v1r20261106`, `…v2`, `ml_entry_tp_revision_v1`; `ml/candidates/` holds `ml_entry_eq_v1`, `ml_entry_eq_v2_struct`, `ml_entry_eq_v3_struct_ens5`. The manifests-keyed guard does not see them: `ml-feature-inventory-2026-11-01.md` § 1a measured **0 matches** for ENTRY's 20 features (`xs_rank_ret24`, `ret_168`, `btc_vol24`, `breadth_up24`, `rel_vol`) in the catalog — ENTRY is a standalone harness. **Re-measure before building:** diff `ml/served/*/model.json::features` and `ml/candidates/*/model.json::features` against the catalog `inputs[].id`/`ml_models[].features` (a 20-line script; the diff *is* the gap list).
2. **Its own `unguarded_surfaces` says so:** entry/exit **head** feature lists live in VM artifact JSON, not git; hand-built live feature rows (`vwap.py`, `ict_scalp.py`, `turtle_soup.py`, `advisory_sizing.py`); hardcoded regime constants.
3. **Source:** present for every row (`source`, `read_at` file:line) — but code-location, not **data** source (vendor/stream/store/history depth/symbols covered). The operator's "catalog of what we store/have available" is the retired-then-reopened row `DATA-CATALOG` (ml-feature-inventory § 1a); not delivered.
4. **Freshness:** prose only, and `measured` for **10/335**; no live "last value at / age" field. A freshness cell cannot be truthful for 325 rows — render **"—"** with `read_state: unmeasured`, never "fresh".
5. **Consuming models:** `used_by` exists for **305 of 335** inputs (MEASURED) but it names **strategies and some model ids**, not the registry's model ids for models trained after 2026-10-08; the inverse (model → features) is `ml_models[].features`. 30 inputs have no consumer (unused) — a useful view, not a bug.
6. **Staleness of the catalog itself:** no field says how old the file is in the UI. Show `generated` and `guard` status.

**Gaps to fix (build rows, Tier-1 unless noted):**
- **G1 route:** `GET /api/bot/catalog/features` → `{as_of, catalog_generated, read_state, features:[{id, family, kind, definition, source_code, data_source|null, freshness:{state, last_value_at|null, age_s|null}, used_by_strategies, used_by_models:[{model_id, stage}], health_state}], coverage:{n_features, n_with_consumer, n_models_in_registry, n_models_missing_from_catalog}}` — joins the YAML with the registry rows (stage, `linked_strategies`) and the `model.json`/manifest feature lists. `n_models_missing_from_catalog` must be **computed and shown**, not asserted.
- **G2 coverage test:** `signal-catalog-guard` extended (or a sibling) to key on `ml/served` and `ml/candidates` `model.json::features` so a new model with unlisted features fails CI. **Gates this adds: a CI guard — needs the operator's OK (No-new-gates rule).** Alternative with no gate: the route's `n_models_missing_from_catalog` plus a weekly review line.
- **G3 freshness:** only for streams with a measurable timestamp (funding, OI, macro) — a per-stream `last_value_at` from the stores' existing `max(ts)`; others stay "—".
- **SPA:** read the sub-tab first; render from G1; "—" for nulls; filter by family/stage/consumer; a row for "unused (no consumer)".
**Acceptance:** model count in the tab == registry count (re-parsed, not quoted); the three `ml_entry_eq_*` candidates appear with their 21-feature lists (the `v1` file lists 21 features, not 20 — **MEASURED** from `booster_txt.feature_importances`); a feature with no freshness metric shows "—".

---

## 15. FEATURE-IMPACT-MAP (addendum 2026-11-11, manager request)

**Ask (operator, per the dispatch):** for every ML and feature, a measure of impact **per asset / market / timeframe**, rolled up into a **drill-down heat map** (feature family × asset class or ML type → drill to feature × symbol × timeframe), plus a **"where to invest in data collection"** view.

### 15.1 What already holds importances (MEASURED, grep of `ml/` and artifacts)
| artifact | what | limits |
|---|---|---|
| `ml/candidates/*/model.json::booster_txt.<side>` → trailing `feature_importances:` block | LightGBM **split counts** per feature (e.g. `ml_entry_eq_v1`: `breadth_up24=2037 … xs_rank_volz=31`) | **split count only**, no gain; biased toward high-cardinality/continuous features; per model, pooled over the whole training population (no per-symbol breakdown) |
| `ml/offload-inbox/*/…/model_state.json::feature_importance_gain` + `feature_importance_split` (+ `feature_columns`) | **gain and split** for the regime LGBMs | trainer-VM offload artifacts; per model, one symbol/timeframe each (the model *is* per symbol) |
| `ml/trainers/lightgbm_multiclass.py`, `lightgbm_regression.py`, `regime_classifier.py`, `per_strategy_winrate.py`, `torch_sequence.py` | write the above at train time | the sequence/HMM/ONNX models have **no** native importance |
| `docs/research/e2-feature-information-2026-08-20.md`, `cross-asset-feature-probe-2026-06-18.md` | earlier model-free information probes | one-off reports, not a store |
| `src/runtime/entry_head_pwin.py`, `exit_head_shadow.py`, `ml_entry_tp_policy.py` | load head artifacts | head feature lists are on the VM (catalog `unguarded_surfaces`) |
**There is no store of importances over time and none keyed by (feature, symbol, timeframe).** The registry (`ml/registry/model_registry.py`, mirrored `registry.jsonl`) holds model metadata; whether it carries importances is **UNVERIFIED** (grep `feature` in it: no hits).

### 15.2 Measures (three, kept separate — never blended into one score)
1. **M1 model-internal importance** — **gain** (preferred) and permutation importance / **SHAP** computed on **each model's own out-of-fold (OOF) data**, never the training fit and never the held-out read (ML-BAR-ONE-READ governs held-out; this uses dev folds only). Per model, per feature; normalised **within model** to a share of total (so models are comparable by *share*, not raw gain). Models without native importance (HMM/seq): permutation on OOF, or "—".
2. **M2 model-free rank IC** — Spearman rank correlation between the feature (as-of, point-in-time) and the **forward return at the ML's own label horizon** (after the ML's cost/label transform where the label is cost-adjusted), computed **cross-sectionally per timestamp then averaged** (so it measures ranking of symbols, not the market's trend), reported as **mean IC, IC t-stat/ICIR, and stability: IC by calendar quarter, sign-consistency %, and rolling-window decay**. Population stated per cell (n timestamps × n symbols).
3. **M3 ablation (optional, expensive)** — retrain the ML without the feature **family** (not each feature) on the dev walk-forward and report Δ in the registered metric; the only measure that answers "does it add edge **given the others**". Pre-registered per `RQ-20261101-fs01-01`-style units; reuse its results rather than recompute.

### 15.3 What raw correlation with price gets wrong (call-out)
- **Non-stationary, trending series:** correlating a level (price, OI, a moving average) with price level produces spurious correlation; features must be differenced/normalised and the target a **forward return**, not price.
- **Contemporaneous ≠ predictive:** corr(feature_t, return_t) includes the bar that built the feature (look-ahead by construction); impact must use **forward** returns at the horizon.
- **Overlapping labels & autocorrelation** inflate significance — the effective n is far below the row count; use non-overlapping or block-bootstrap CIs.
- **Pooled sign flips (Simpson's):** a feature can be +IC in one asset class and −IC in another; pooled correlation can be ~0 while each class is strong — hence the per-class heat map.
- **Linear only:** misses non-linear/threshold/interaction effects a tree model uses (M1 catches them, M2 does not); **redundant features** share credit (M1 splits it arbitrarily among collinear columns; M3 is the fair test).
- **Cost and regime blind:** a feature can predict gross return but not net of the full cost stack; and be regime-specific. Show IC **by regime/vol bucket** and mark ESTIMATED where costs are not applied.
- **Provenance:** every cell carries `provenance` (`src/runtime/provenance.py`) and `n`; a cell with n below a registered floor shows "—" (`insufficient_n`), never 0.

### 15.4 Long-table schema and store (PROPOSED)
One append-only long table, **`feature_impact`**, a new table → **needs the operator's OK for the new store** (data-wiring declaration, `new-table-wiring-guard`; Tier-2 per the db-wiring rule). Cheaper alternative with no new table: Parquet/JSONL under `comms/feature_impact/<run_id>.parquet` published by the job and read by the route (file-based, like `runtime_logs/insights/`); recommended for v1.
```
run_id, computed_at, feature_id (= catalog id), feature_family, model_id|null, ml_type,
asset_class, symbol, timeframe, horizon_bars, regime|"all",
measure ("gain_share"|"perm_importance"|"shap_abs"|"rank_ic"|"ic_ir"|"ic_sign_consistency"|"ablation_delta"),
value, ci_low, ci_high, n_obs, n_symbols, window_start, window_end,
provenance, read_state ("measured"|"insufficient_n"|"not_computed"|"no_importance_native"), source_artifact (path/sha)
```
Key = (run_id, feature_id, model_id, symbol, timeframe, regime, measure). Roll-ups (feature family × asset class / ML type) are **views computed on read**, never stored (so they cannot drift from the leaf rows).

### 15.5 The off-VM scheduled job (no Claude, no live-VM load)
New `scripts/ml/feature_impact.py`, run as a **GitHub Actions scheduled workflow (weekly, off-peak) or on the trainer VM's existing cycle** — never on `ict-bot-arm`, never an Anthropic API call (rule: *nothing spends API credits*; this is pure pandas/lightgbm/sklearn). Inputs: (a) every registered model's `model_state.json`/`model.json` (M1, from the artifacts above; SHAP/permutation recomputed on stored OOF predictions where the manifest keeps them — **UNVERIFIED which manifests persist OOF**: if not, the job rebuilds OOF from the dataset family with the model's own splitter `ml/experiments/splitters.py`); (b) the dataset families `ml/datasets/families/market_features.py` + the pooled feature store (L-DATA) for M2 over the 60-perp universe and equity pools; (c) the catalog for ids/families. Idempotent per `run_id`; a failed model is recorded `read_state:"not_computed"` with the reason and the run continues (**no halting**); one red flag if a model fails 3 runs running.
**Tier:** Tier-1 (offline research tooling, no live path). Needs the data stores readable off-VM (the trainer mirror / data lake).

### 15.6 API route and SPA view
**Route:** `GET /api/bot/feature-impact/heatmap?group=family|ml_type&by=asset_class|ml_type&measure=&run=latest` → cells `{row, col, value, n, provenance, read_state}`; `GET …/feature-impact/detail?family=&asset_class=&measure=` → drill-down feature × symbol × timeframe cells; `GET …/feature-impact/invest` → ranked list for the data-collection view. Reads the file/table above; GET only; behind the site gate; null → "—".
**SPA:** heat map (diverging scale for IC sign, sequential for importance share; `dataviz` skill), click a cell → feature × symbol × timeframe grid; toggles: measure, regime, "stable only" (sign-consistency ≥ a registered floor); hover shows value, CI, n, provenance. Empty/insufficient cells are hatched "—", not colour-0.
**"Where to invest in data collection" view (PROPOSED rule, flagged — registers before use, § 16 Q7):** rank **families** by `(proxy for edge: stable positive IC-IR or ablation Δ, shrunk by CI)` × `coverage gap` (fraction of the universe/timeframes where the family is **absent or stale** — from § 14's catalog coverage/freshness) ÷ `collection cost` (from `ml-feature-inventory` § 7 backfill hours / COLLECT class). Output is a **ranked list with each factor visible**, not a single opaque score; a family with no coverage record shows "—" in the gap column. This view **recommends**; it authorises nothing (roadmap-loop rule).

### 15.7 Build split and order
1. **ML lane (Tier-1, off-VM):** § 14 G1-input diff script → `scripts/ml/feature_impact.py` v0 with **M1 only** from existing artifacts (cheapest, most of the data already exists — `model.json`/`model_state.json`) → write `comms/feature_impact/*` → add **M2** (needs pooled dataset) → weekly workflow → **M3** reuse from `fs01` results.
2. **Backend lane (Tier-1):** § 14 G1 route (also gives M1/M2 a stable feature id), then the three heat-map routes reading the published artifacts.
3. **UI lane:** Features sub-tab (§ 14) → heat map + drill-down → invest view. The UI can start against a **fixture** of the long-table schema (committed sample) the moment the schema is agreed, in parallel with the ML lane.
**Depends on:** § 14 (stable feature ids and the catalog↔registry join); L-DATA pooled store for M2 breadth. **Acceptance:** for `ml_entry_eq_v1` the heat map's `gain_share`/split share for `breadth_up24` equals the artifact's `2037/Σ` to rounding (the cross-check, arithmetic not re-read); a model with no native importance shows `no_importance_native`; M2 for a feature recomputed by hand on one symbol/quarter matches; no cell shows 0 where n is insufficient; the job runs with no network to Anthropic and no ssh to the live VM.

## 16. Added operator questions (addenda)
7. **Invest-view rule:** is "stable edge proxy × coverage gap ÷ collection cost, all factors shown" the ranking you want, or a different priority (e.g. by asset class you intend to trade next)?
8. **Store:** file-based `comms/feature_impact/` (no new table, recommended for v1) vs a `feature_impact` table in a DB (needs your OK)?
9. **CI guard:** may the catalog guard be extended to fail when a served/candidate model has features missing from the catalog (adds a gate), or keep it as a route-computed coverage number only?
