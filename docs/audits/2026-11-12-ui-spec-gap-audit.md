# UI spec gap audit: two surfaces vs what is live (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · written by the UI standing lane, part 2
> (session_01AFoLuMw1bWyUmi4HkqYBX8), dispatched by Manager Session 2026-11-11a.
> **Spec:** [`docs/plans/UI-TWO-SURFACE-DESIGN-2026-11.md`](../plans/UI-TWO-SURFACE-DESIGN-2026-11.md) §§ 2–5 (operator decisions U1–U6, 2026-11-05).
> **Gates this adds or changes:** none.

**How it was measured, 2026-11-12 07:44–08:05Z.** Every verdict below comes from a live read:

- live `/api/bot/*` routes, fetched from a cloud session through the proxy
- `/api/diag/journalctl?unit=ict-web-api` (the API's access log: 1,582 GETs between 07:00 and 08:00Z; the operator's browser is 213.137.72.98)
- the JTA Trader connector, called from claude.ai at 07:44 and 07:50Z
- the console artifact (v22 as read, v23 published by this lane), and its page `db` (`inbox`, 20 docs)
- the work store (`GET /api/bot/work/items/<row>`), which is the register of record since the WORK-STORE S4 freeze. The repo row files are an export.

The SPA repo (`benbaichmankass/ict-trader-dashboard`) is not reachable from this lane (decision m2). SPA behaviour is judged only by the requests it makes to the API.

Verdicts: **built + observed** · **built, not observed** · **not built**.

## Top gaps, ranked by what the operator sees first

1. **The console has shown a 6-day-old work register since 11-06, labelled `read`.**
   - The connector built Work, Overview and Inbox from the repo files on the trainer, which have been the frozen export since S4 (#23962).
   - Measured through the connector: 28 in flight, every one updated 161.7 h ago. The store has 7, all updated today.
   - The operator's reorders on 11-07 (`inbox/mv-*`) were made on rows from that stale view.
   - **Fix: PR #25164** (held, Tier 2), which reads the register from the store.
2. **The trading dashboard still polls, and there is no push stream** (T1/T2).
   - `GET /api/bot/stream` returns 404, and no SSE route exists in `src/web/api`.
   - Between 07:00 and 08:00Z the operator's browser made 184 API GETs: `work/snapshot`, `stats`, `strategies`, `signals`, `accounts/balances`, `prop/overview`, `config`, `trades/closed`, `performance` and `news/recent`, each 9–12 times.
3. **The crypto live chart (T3a) is due today (11-12) and is not built.**
   - `market_ws.py` still fetches `*USDT` candles per connection.
   - It is SPA-side work, blocked on repo access (m2).
4. **Health cards (T4) are not built.** They need T1, plus the SPA.
5. **The console is missing three of the tabs the spec names: Journal, Reports, and Strategies & ladder.**
   - Inbox → Alerts says `could_not_look` even though `/api/bot/alerts` answers 200 and the connector's sign-in (G1) is live.
   - "Ask Claude" (C5) is not built: the page does not declare `sample`.
6. **SPA routes are slow.**
   - `work/brief` returned 502 after 30.5 s.
   - `work/decisions` took 13.9 s, `accounts/balances` 5.3 s, and `prop/overview` 4.5 s.
   - In one burst, `positions`, `balances`, `prop/overview` and `trades/closed` all passed 6 s; re-reads took 0.4–5.3 s.
7. **The SPA Work page serves row ages days too old.**
   - Store writes do not refresh the row's own `updated_at`.
   - Example: MANAGER-VM-DIRECT-OPS shows 11-05 00:46Z; the store wrote it 11-12 01:16Z.
   - Filed as row `WORK-ROW-AGE-STALE` (Tier 2, due 11-14).

## Trading surface (SPA): spec § 4–5

| Element | Verdict | Evidence | Owning row · due | Blocked by |
|---|---|---|---|---|
| T1 broadcaster + `GET /api/bot/stream` (SSE; journal, alert and health frames) | **not built** | `/api/bot/stream` 404 at 07:5xZ; no `text/event-stream` in `src/web/api` | `UI-TRADING-PUSH` · 11-18 | nothing. API-side, buildable in this repo (Tier 2) |
| T2 SPA subscribes; 15 s and 30 s polls deleted | **not built** | the operator's browser polls 10 routes 9–12×/h (journal, 07:00–08:00Z) | `UI-TRADING-PUSH` · 11-18 | T1; SPA repo access (m2) |
| T3a crypto chart on the Bybit public WS, with markers; `/ws/market` stops `*USDT` candles | **not built** | `market_ws.py::_candle_ttl` still fetches `*USDT` | `UI-CHART-CRYPTO-LIVE` · **11-12 (today)** | SPA repo access (m2). Live markers wait on T1. |
| T3b equities (Alpaca WS, dedicated empty paper key) | **not built** | — | `UI-CHART-EQUITIES-FEED` · 11-25 | T3a; an operator-originated data key |
| T3c futures (Databento relay or Massive) | **not built** | — | `UI-CHART-FUTURES-FEED` · 12-09 | T3b; an operator spend decision on fresh quotes |
| T4 health cards as pushed frames | **not built** | no stream; `health/latest` 200 and `health/services` 200 exist as REST | `UI-OVERVIEW-HEALTH-CARDS` · 11-10 (**overdue**) | T1; SPA (m2) |
| § 4.1 open positions with brackets | **built, not observed** for brackets | `positions` 200 (0.5 s), polled. `/brackets/history` needs a fill id (400 without one). | `PI-20261112-Y8IHTRHC-0001` (SPA halves) · 11-15 | SPA (m2) |
| § 4.1 urgent alerts on the trading surface | **not built** (SPA) | `/api/bot/alerts` 200, `read_state: read`; no SPA request for it in the 07–08Z log | `UI-TRADING-PUSH` (via T1) | T1; SPA |
| § 4.1 balances + mode, prop cushion + tickets | **built + observed** (polled) | `accounts/balances`, `prop/overview` 200, called by the operator's browser 10×/h | — | — |
| Four books on the funding axis | **built, not observed** in a browser | row note: dashboard #232 merged, bundle has the labels | `UI-FOUR-BOOKS` (landed_unproven) | a human look |
| Surge backend halves (#24873 #24924 #24893 #24919 #24927 #24926) | **built + observed** (API); SPA halves **not built** | `performance/categories` 200 (4.0 s), `work/ledger` 200, `work/topics` 200 (150 KB) | `PI-20261112-Y8IHTRHC-0001` · 11-15 | SPA (m2) |
| R1 retire 17 console pages from the SPA | **not built** | the operator's browser still calls `work/snapshot`, `performance`, `news/recent`, … | `UI-SPA-RETIRE-CONSOLE-PAGES` · 11-27 | C2–C4 observed for 7 days; SPA (m2) |

## Console (artifact + connector): spec §§ 2–3, 5

| Element | Verdict | Evidence | Owning row · due | Blocked by |
|---|---|---|---|---|
| C1 connector on the trainer, OAuth allowlist (G1), cache (G2) | **built + observed** | claude.ai called `work_items` and `work_rows` at 07:44 and 07:50Z. Gated tools (`performance`, `system_health`, `data_query`) and the write tool `set_wake_toggle` are listed, so the Google sign-in is active. | `UI-CONSOLE-CONNECTOR` (store: queued, stale) | — |
| C1 tool set (§ 2.3) | **partly built** | Live tools: hello, work_rows, inbox, workplan, ml_roadmap, system_catalog, research_queue, wake_toggles, performance, system_health, data_query, work_items. **Missing:** alerts, work_brief, work_decisions, journal_trades, order_packages, signals_history, reports/report, strategies/config_roster, prop_reconcile, roadmap. | `UI-CONSOLE-ARTIFACT` | nothing. Buildable here. |
| Register freshness (everything the Work, Overview and Inbox tabs read) | **built, wrong source** | export read: 28 in flight, 161.7 h old; store: 7 | `UI-CONSOLE-ARTIFACT` · PR **#25164** | the manager's merge and the connector install |
| C2 tabs: Journal | **not built** (only `data_query` rows) | v23 nav: Overview, Work, ML roadmap, Performance, Data, Research queue, Wake switches, System | `UI-CONSOLE-ARTIFACT` | nothing |
| C2 tabs: Data, ML, Research | **built + observed** (`UI-CONSOLE-TABS-DATA` note: v11–v15 opened) | tools answer: `ml_roadmap`, `research_queue`, `data_query` | `UI-CONSOLE-TABS-DATA` | — |
| C2 tabs: Strategies & ladder | **partly built**: System tab has the strategy catalog with status; no ladder view | `system_catalog` live | `UI-CATALOG-STRATEGIES-ML` · 11-09 (**overdue**) | — |
| C2 tabs: Reports | **not built** | `/api/bot/reports` 200 (48 KB), but no connector tool | `UI-CONSOLE-ARTIFACT` | nothing |
| C3 Work tab on the work store | **built, not observed** | v23 Work tab (watch `work_items` recent, 30 s; Due / Open; History). Tool live-tested from a cloud session; the deployed connector still has the stub. | `UI-CONSOLE-ARTIFACT` · PR #25164 | merge + install, then the 45 s probe |
| C4 N1 inbox notes → manager → store | **built + observed** | page `db` `inbox`: 20 docs, all `status: filed` (11-05 → 11-07) | `CONSOLE-OPERATOR-ASKS` · 11-07 (**overdue**) | — |
| C4 N2 comments + `sendToClaude` | **built, not observed** (declared `comments`; no observation recorded) | — | `UI-CONSOLE-ARTIFACT` | a watching manager session |
| C4 N3 `fire_trigger` from the page (U4, after a probe) | **not built** | no probe recorded | `UI-CONSOLE-ARTIFACT` | the probe |
| Inbox → Alerts section | **not built** (says `could_not_look`) | `/api/bot/alerts` 200; the connector never reads it | `UI-CONSOLE-ARTIFACT` | nothing. G1 is live. |
| C5 "Ask Claude" (`sample`) | **not built** | page capabilities: `comments`, `db`, `mcp`, `user` (no `sample`) | `UI-CONSOLE-ARTIFACT` | nothing |
| "Needs from you" asks panel | **built + observed** | `inbox/ask-*` operator_input docs filed 11-05 | `CONSOLE-OPERATOR-ASKS` | — |

## What this lane builds next (all in this repo)

1. **#25164** (held): the register from the store, plus `work_items`. It closes C3 once installed and probed.
2. Console: an alerts section on the live ledger; Journal and Reports tools and tabs.
3. **T1**: the SSE broadcaster `GET /api/bot/stream`, prepared as a held Tier-2 PR. It is the only trading-surface step that does not need the SPA repo.
4. A written SPA diff plan for T2, T3a, T4 and the surge halves, so an SPA lane can start the moment m2 is granted.
