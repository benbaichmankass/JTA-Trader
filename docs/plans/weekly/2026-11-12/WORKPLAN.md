# Weekly workplan — week of 2026-11-12 (Thu 11-12 → Wed 11-18)

> **Doc status:** `unknown` · category `plan` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

> **Gates this adds or changes: none.** It assigns owners, order and dates to existing rows; it changes no automatic path, adds no guard, and decides nothing about whether anything trades.

Lane WEEKLY-PLANNING (session_01AFoLuJYH2DegJNK1DRonR4), dispatched by Manager Session 2026-11-11a after the operator's 2026-11-12 ~09:00Z order: *"Go back and do a FULL WEEKLY PLANNING, making sure that we understand ALL the tasks and have them qued up correctly"*. Protocol: [`docs/plans/weekly-planning-protocol.md`](../../weekly-planning-protocol.md). Operator answers used: `docs/plans/thursday-planning-2026-11-12-answers.md` (on branch `lane/opdec-20261112`, not yet on main when this was written; p1–p9, m1–m13).

**The work store is the record; this file is the readable copy.** Every disposition below is APPLIED in the store (`work.py --via direct`): owner `AM-<class> (<session>)`, `lane` = the assistant manager's session unless a live working lane already holds the row, `week_lane`, `due_rule` = slot day, `priority_rank` = order within the class, and a note on each row carrying the triage evidence, size, deps and governing spec. Where this file and the store disagree, the store wins.

## Population and method

- **Population:** every `kind=build` item in state queued / in_flight / blocked in the store snapshot of 2026-11-12 09:05Z: **518** (470 queued, 23 in_flight, 25 blocked; 4,353 items total). 517 of them are dispositioned here; the 518th is `WEEKLY-PLANNING` itself (this lane records on it). One more row, BACKLOG-DRAIN-20261112 (landed_unproven in the snapshot, in triage file D), was also given its slot, so the decision set is 518. Two snapshot rows filed at 08:59Z (CLOSED-TRADE-SNAPSHOT-ROUTE/-WRITER) were missing from the triage files and were dispositioned by this lane directly. One triage row, TRADEIFY-FUTURES-FRONTIER, is not in the store and was skipped.
- **Triage input:** six read-only agents (files A–F under `triage/`, folded into this PR). This lane verified samples in every file (≥10 per file; all close/superseded/duplicate/kill claims in A–E were read, PR merges checked on GitHub for #24942, #25022, #23200) and corrected what was wrong (§ Corrections).
- **Assistant managers** (Manager 2026-11-11a, 09:03Z): UI `session_01AFoLuMr5RixbuwJtqED344` · ML `session_01AFoLuJkXEM1EigH9mSfz1F` · TRADING `session_01AFoLuMroLtrU2biw4ZDoBk` · OPS `session_01AFoLuJUGfpon2bNgwFbFmx`. A row spanning classes went to the class owning its money risk first (TRADING > ML > UI > OPS).
- **Writes:** 518 dispositions + 337 slot sets + 120 carry-over re-slots + 731 observation routings; **0 write failures** (each retried up to 3×).

## 0a. Scoreboard (before the numbers)

**Scoreboard** — net P&L per book, trials vs survivors, measured cost

_As of 2026-11-12T09:05:39+00:00 · source `diag` · 7098 journal rows read. `—` = no number (unreadable / empty / no capital basis). Populations are in the JSON (`/api/bot/work/scoreboard`)._

| book | inception net | inception % | n | PF | trailing 30 d net | 30 d % | n | PF | pnl measured |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Real money | -$132.10 | -41.36% | 514 | 0.66 | -$19.89 | -9.41% | 34 | 0.62 | 79% |
| Prop | -$581.86 | -2.91% | — | — | -$101.84 | -0.51% | 25 | 0.74 | — |
| Mirror (Stage-2 paper twin) | -$36,437.62 | -18.23% | 172 | 0.61 | -$3,833.10 | -2.50% | 37 | 0.75 | 60% |
| Paper (soak + floor) | -$49,189.58 | -2.74% | 1762 | 0.91 | -$108,795.56 | -8.37% | 194 | 0.28 | 41% |

Paper and mirror dollars are paper notional, not money. % = net / broker equity at window start (`balance_snapshots`; prop: declared `account_size_usd`); `—` where no start equity could be read.

**Cost per trade** (real-money closed priced trades, closed by 2026-11-12T09:05Z; n=514): MEASURED 0.248 $/trade (n=106) · ESTIMATED 0.186 $/trade (n=400) · UNVERIFIED/uncosted n=8. Measured share 20.6%; estimated is not folded into measured.

**Trials vs survivors** (comms/research/RQ-20261016-6013-01/42276444552/trial_ledger.json generated 2026-11-06T19:06:39+00:00 by scripts/research/trial_ledger.py; 57 evidence records; report_only=True): 3457 configs tried · 29 Stage-0 pass · **0 survive** (dsr > 0.95 AND bhy haircut expectancy > 0).

Sceptical-quant line: real money is −41% since inception (n=514, PF 0.66) and the trial ledger shows **0 survivors** of 3,457 configs; nothing this week is promoted on a live book's P&L. Real-money promotions this week (PROMOTE-TLT-1H, PR1111-SURVIVOR-PROMOTIONS) go only on a committed Stage-0 record; demotions go to the operator first (p2, one-off).

## 0. Review follow-through (`review_followthrough.py --window-days 7`)

```
REVIEW FOLLOW-THROUGH  as of 2026-11-12  window 7 d  closed-within 7 d
POPULATION: 2700 pipeline items (store read, 0 unreadable) + 1398 checklist rows; source classified from id/origin/title text (see SOURCES)

source             | cohort(filed 7d): filed done kill open ≤7d | backlog(now): open due% med-age no-owner
--------------------------------------------------------------------------------------------------------
perf-followup      |                 0    0    0    0    — |                 9  78%      31        2
performance-review |                 5    5    0    0 100% |                32  75%      20       15
frontier           |                 1    1    0    0 100% |                16  69%    16.5        1
ml-review          |                 2    2    0    0 100% |                12  83%    32.5        0
health-review      |                 1    0    0    1   0% |                87  95%      74       46
weekly-audit       |                 0    0    0    0    — |                17  94%       8        0
programme-review   |                 2    1    0    1  50% |                14  71%      11        2
research-ops       |                 7    1    0    6  14% |                54  87%    15.5       20
ltr                |                 8    2    0    6  25% |                37  51%      14        3
desk               |                 7    2    0    5  29% |                72  57%      13       17
```

## 0b. BACKLOG

**BACKLOG (store, 09:05Z):** 731 queued observations — **due 637**, no due date 36, **unrouted (no parent row) 88**; oldest BL-20260525-005 (filed 2026-05-25, 171 d); opened in 7 d **65** (by the filing date in the id, 730 of 731 ids carry one), closed in 7 d **≥119** (terminal records updated since 11-05, excluding the 11-05 import minute; INFERRED, the store's `created_at` is the import time). File export (`checklist_daily_measure.py`, stale export, see HEALTH-20261111-EXPORT-READS-STALE): pipeline due 737, unrouted 315, open 800 — population differs from the store; the store is the record. Last week's drain: merge-slot files `backlog-drain-20261105-b1..b3` exist on main, so three drain batches were claimed; their outcome was NOT re-read by this lane (UNVERIFIED); BACKLOG-DRAIN-20261112 is this week's lane (operator p4: *"Accept: start after the export fix"*).

**Routing applied (never bulk-dropped):** all 731 queued observations got an owner + lane: to their parent row's assistant manager when the parent is an open row planned today (TRADING 154, ML 66, UI 8), otherwise to the OPS drain (503: parent closed today, parent landed_unproven/not in today's set, or no parent). The drain may be deferred to the throttle-down if surge needs the capacity (protocol item 5; record the deferral on WEEKLY-PLANNING). Every drop carries its own reason and supporting data (operator p7).

## Capacity

Operator p1, verbatim: *"We have a reset so the plan is to surge until we reset again, hopefully on Saturday or Sunday, then reset and keep surging until we have to throttle ahead of the Wednesday reset. Don't worry about capacity for now, just keep the surge going"*. So there is no WIP cap this week: surge Thu 11-12 → Sat 11-14, reset (~Sat/Sun), surge Sun 11-15 → Tue 11-17, throttle-down ahead of the Wed 11-18 reset. Slot days are an order of start, not a cap: an AM starts the next slot as soon as one frees. Standing work goes first whenever due; **one ML-research lane stays reserved through the surge** (manager skill § 'ONE ML LANE ALWAYS RUNS').

## 1. Carry-over from last week (11-04/05 plan, 11-06 replan, 11-10 must-queue, 11-11 lite plan)

| row | store state | this week |
|---|---|---|
| ML-ENTRY-ALL-ACCOUNTS | blocked | landed_unproven 2026-11-15 |
| ML-DECISION-MODELS | queued | surge 2026-11-13 |
| ML-PROP-ITERATE | queued | surge 2026-11-15 |
| ML-ENTRY-WATCHDOG-EXIT | landed_unproven | (not in today's set: landed_unproven) |
| SHARED-BRACKET-FIX | landed_unproven | (not in today's set: landed_unproven) |
| BYBIT2-FUNDING-SETTLEMENT-READ | done | (not in today's set: done) |
| PROP-SIZE-EXCEEDS-DD-CUSHION | queued | surge 2026-11-13 |
| ML-ENTRY-LIVE-MONITOR | queued | landed_unproven 2026-11-15 |
| ML-ENTRY-RETRAIN-CADENCE | queued | close_done |
| STRUCTURE-EXITS-DEFAULT | landed_unproven | (not in today's set: landed_unproven) |
| TRADEIFY-OWN-LEG-DRIVER | queued | surge 2026-11-16 |
| ALPACA-LIVE-ACTIVITY-ML | landed_unproven | (not in today's set: landed_unproven) |
| HF-LAKE-KAGGLE-LOADER | queued | surge 2026-11-15 |
| ETF-HISTORY-PIPELINE-LOWDISK | queued | superseded |
| ALPACA-LIVE-MECHANICS | landed_unproven | (not in today's set: landed_unproven) |
| ML-ENTRY-EQ-STRUCTURE-RETEST | queued | superseded |
| ML-AM-NEXT-LIVE | blocked | surge 2026-11-12 |
| TMBENCH-QTM1B-BUILD | done | (not in today's set: done) |
| VENUE-SCOPE-HYPERLIQUID | queued | close_done |
| TRADEIFY-FUTURES-EVAL | in_flight | surge 2026-11-13 |
| PROP-PLAN-EV-6M | in_flight | surge 2026-11-12 |
| TRADE-ACTION-FAST-PATH | landed_unproven | (not in today's set: landed_unproven) |
| MIRROR-QTY-DIVERGE | landed_unproven | (not in today's set: landed_unproven) |
| LTR-ACCOUNT-SCOPED-ACTIONS | queued | surge 2026-11-14 |
| ML-PROGRAMME-CONSOLIDATION | queued | surge 2026-11-12 |
| ML-ENTRY-EQ-PRESCREEN | queued | surge 2026-11-16 |
| GLD-WEDGE-RETRO | queued | throttle 2026-11-18 |
| TELEGRAM-TRIM | landed_unproven | (not in today's set: landed_unproven) |
| ETF-HISTORY-PIPELINE | queued | close_done |
| PHONE-SCREENSHOTS | queued | superseded |
| PROP-UI-BRACKETS-CLOSED | in_flight | surge 2026-11-12 |
| DESK-ENTRY-REVIEW-REDESIGN | queued | surge 2026-11-17 |
| FABLE-RESETS-PLAN | queued | later 2026-11-23 |
| UI-SIDEBAR-COLLAPSE-DESKTOP | queued | landed_unproven 2026-11-13 |
| LTR-FAST-MOVE-LOCKIN | queued | surge 2026-11-15 |
| PHONE-LIVE-ACCOUNT-FEED | in_flight | surge 2026-11-12 |
| UI-CHART-BRACKET-HISTORY | in_flight | surge 2026-11-13 |
| SECRETS-UI-SCOPE | queued | later 2026-11-23 |
| SECURITY-HARDENING-AUDIT | queued | surge 2026-11-14 |
| UI-OAUTH-SIGNIN | queued | surge 2026-11-15 |
| WORK-TOPIC-TAXONOMY | queued | throttle 2026-11-18 |
| PERF-PAGE-CATEGORY-TABLE | queued | surge 2026-11-14 |
| PERF-PAGE-PNL-CHART | in_flight | surge 2026-11-13 |
| UI-MODELS-STRATEGIES-TABLES | queued | surge 2026-11-16 |
| INSIGHTS-LEDGER | queued | surge 2026-11-16 |
| VOLUME-COMPOSITION-RESEARCH | queued | close_done |
| ML-DEEP-AUDIT-FABLE | queued | surge 2026-11-12 |
| LANE-STRUCTURE-WEEK | queued | close_done |
| UI-REDESIGN-2026-11 | in_flight | surge 2026-11-13 |
| TP-DOCTRINE | done | (not in today's set: done) |
| REVIEW-FOLLOWTHROUGH | landed_unproven | (not in today's set: landed_unproven) |
| RESEARCH-PIPELINE-SLO | landed_unproven | (not in today's set: landed_unproven) |
| LIVE-DECAY-MONITOR | queued | throttle 2026-11-17 |
| PASS-TO-DECISION-SLO | queued | superseded |
| ML-LEARNING-LEDGER | queued | surge 2026-11-14 |
| EXIT-HEAD-ETH-REGISTER | done | (not in today's set: done) |
| REGIME-UNITS-W45 | queued | close_done |

Unfinished carry-overs were re-slotted **first** in their class (right after rows with a live lane). **Second carry (operator decision):** LIVE-DECAY-MONITOR was a (a) item on 11-04, moved to 11-11, and is still queued — scheduled throttle 11-17 here, question routed to the manager. ML-LEARNING-LEDGER had the same history but the operator already scheduled it (p7, due 11-16; slotted 11-13). PASS-TO-DECISION-SLO closed as superseded by AUD-20261019-RESEARCH-SLO-RED (OPDEC-P7 lane, PR #25184).

## 2. Totals

| class | surge | throttle | standing | landed_unproven | later | closed | kill candidates | observations routed |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| UI | 21 | 3 | 0 | 1 | 3 | 9 | 0 | 8 |
| ML | 22 | 67 | 3 | 2 | 26 | 30 | 4 | 66 |
| TRADING | 72 | 72 | 3 | 2 | 17 | 37 | 6 | 154 |
| OPS | 19 | 61 | 1 | 1 | 9 | 24 | 3 | 503 |
| **all** | 134 | 203 | 7 | 6 | 55 | 100 | 13 | 731 |

Sum check: 518 dispositions = 46 (F) + 263 (A/C/D) + 111 (B) + 98 (E, incl. the 2 CLOSED-TRADE-SNAPSHOT rows) = 517 snapshot rows + BACKLOG-DRAIN-20261112; the snapshot's 518th row is WEEKLY-PLANNING.

## 3. Day-by-day schedule per assistant manager (surge)

Order = `priority_rank`. Size: S < 1 h lane, M half day, L multi-day. Rows with a live lane keep it (named in the row note).

### AM-UI (`session_01AFoLuMr5RixbuwJtqED344`)

Governing spec: **UI-REDESIGN-2026-11** (operator 2026-11-09 + addenda) and `docs/design/ui-workplan-2026-11.md` for every UI row. SPA work in `ict-trader-dashboard` (lane UI-SPA running).

**2026-11-12**

| # | row | size | what |
|--:|---|---|---|
| 1 | PROP-UI-BRACKETS-CLOSED | M | Prop trades: show SL/TP on chart+data; include prop closes in closed-trades log |
| 2 | UI-CHART-BRACKET-HISTORY | M | Charts: faint past SL/TP lines plus a marker where each bracket changed |
| 3 | PERF-PAGE-PNL-CHART | M | Performance page: 30-day P&L % line chart per category with filters |
| 4 | UI-CHART-CRYPTO-LIVE | M | Crypto charts on Bybit public WS in browser with markers; /ws/market drops USDT candles |

**2026-11-13**

| # | row | size | what |
|--:|---|---|---|
| 5 | CLOSED-TRADE-SNAPSHOT-ROUTE | M | Read routes: GET /api/bot/trades/{id}/snapshot (stored closed-trade chart snapshot) + /tra |
| 6 | CLOSED-TRADE-SNAPSHOT-WRITER | M | Close-time chart snapshot writer + backfill (web-api background builder, table trade_chart |

**2026-11-14**

| # | row | size | what |
|--:|---|---|---|
| 8 | PERF-PAGE-CATEGORY-TABLE | M | Performance page category table (live / prop / paper portfolio / testing) with metric colu |
| 9 | UI-OAUTH-SIGNIN | L | OAuth sign-in before the overview + session check on the API routes the SPA calls |
| 10 | UI-MODELS-STRATEGIES-TABLES | M | Models and Strategies tabs as sortable/filterable tables; row click opens the card |

**2026-11-15**

| # | row | size | what |
|--:|---|---|---|
| 11 | INSIGHTS-LEDGER | S | Insights ledger table on the Performance page + manager-skill logging line |
| 12 | POSITIONS-ORDER-PACKAGE-ID | S | Add orderPackageId to /api/bot/positions rows for the SPA bracket-history overlay |
| 13 | CONSOLE-OPERATOR-ASKS | M | Console 'Needs from you' panel: every operator ask with instructions and inputs |
| 14 | UI-TRADING-PUSH | M | SSE /api/bot/stream push; delete SPA 15/30 s polls |
| 15 | UI-CONSOLE-ARTIFACT | M | Management console artifact tabs (Work, Journal, Data, ML ...) |

**2026-11-16**

| # | row | size | what |
|--:|---|---|---|
| 7 | UI-REDESIGN-2026-11 | L | Dashboard redesign per operator spec 11-09: overview, performance, strategies/models, work |
| 16 | SIGNALS-CATALOG-ROUTE | S | API route for the SPA Signals Catalog tab |
| 17 | PERF-API-SINCE-IGNORED | S | /api/bot/performance ignores since= |
| 18 | UI-WORKPLAN-QUESTIONS-1111 | S | Operator answers the 8 UI design questions (decision doc) |
| 19 | FEATURES-CATALOG-UI-VERIFY | M | Features catalog sub-tab under Strategies & Models: SPA tab + fill the coverage gaps |
| 20 | UI-OVERVIEW-HEALTH-CARDS | M | Overview health cards (per account, research/ML, work queue) as pushed frames |
| 21 | UI-DECISION-DOCS | S | Console 'waiting on you': list open decision docs with artifact links |

### AM-ML (`session_01AFoLuJkXEM1EigH9mSfz1F`)

Governing specs: **ML-PROGRAMME-CONSOLIDATION** / `docs/plans/ML-CONSOLIDATION-2026-11-11.md`, `docs/plans/ML-ROADMAP-MECE-2026-11.md`. Reserved ML-research lane works the throttle list in order through the surge.

**2026-11-12**

| # | row | size | what |
|--:|---|---|---|
| 1 | ML-AM-NEXT-LIVE | M | Next live ML does active management (in-trade), starting with exit-head measurement |
| 2 | ML-PROGRAMME-CONSOLIDATION | L | Consolidate ML registry: keep/retire per slot, retire waves, champion/challenger units |
| 3 | ML-DEEP-AUDIT-FABLE | L | Deep audit of ML rosters, infra and workflows (Fable lane) |

**2026-11-13**

| # | row | size | what |
|--:|---|---|---|
| 4 | ML-DECISION-MODELS | L | Umbrella: ENTRY / BRACKETS / MANAGE decision models on real money |
| 5 | ML-LEARNING-LEDGER | M | Build ml_learning_ledger.py: hops H1-H7 per source with read-states, weekly record |
| 6 | HF-LAKE-KAGGLE-LOADER | M | Lake loader reads frozen months from the Kaggle mirror; then delete the HF frozen copy |
| 7 | ML-ENTRY-EQ-PRESCREEN | M | ml_entry_eq refresher latency: pre-screen symbols before bar close |

**2026-11-14**

| # | row | size | what |
|--:|---|---|---|
| 8 | ML-LIVE-PARITY-ML-LEGS | M | Live-vs-replay parity for ml_entry and ml_entry_eq_struct |
| 9 | TM-BENCH-EXIT-ARM | M | TM-BENCH exit-head learner arm + one registered unit per live leg |
| 10 | REGIME-VOL-SPEC-ADVISORY-ONLY | M | vol_detector must read advisory heads only (shadow can change orders) |
| 11 | SMALL-TF-ML-RESEARCH | M | Small-timeframe ML (1m-15m): cost-breakeven census before more model training |
| 12 | ML-REGISTRY-SERVED-MODELS-NO-STAGE | M | Served ML models (LIVE/SHADOW bucket) show no registry stage or metric |

**2026-11-15**

| # | row | size | what |
|--:|---|---|---|
| 13 | ML-ENTRY-EVIDENCE-SOURCE | S | Commit the source file ml_entry.json cites so r4_demotion_gate can grade ml_entry |
| 14 | ML-ENTRY-PROP | M | ML entry on prop accounts: net-edge crypto candidate then V3 prop gate |
| 15 | ML-SHADOW-NEVER-ORDERS | S | Prove shadow-stage models never change an order |
| 16 | ML-DECISION-LABEL-VOL-CONFOUND | S | Is served ml_entry picking symbols by cost-per-R (ATR) rather than direction? |
| 17 | ML-ENTRY-EQ-RESTART-REDECIDE | S | ml_entry_eq re-decides last close after every restart (in-memory memo) |
| 18 | CRYPTO-ENTRY-RETRAIN-UNIT | M | Diagnose served crypto ml_entry -0.13 R: drift vs regime vs cost |
| 19 | FEATURE-IMPACT-MAP | L | Feature impact map: M2 for the other families, M3 ablation, SPA heat map + drill-down |

**2026-11-16**

| # | row | size | what |
|--:|---|---|---|
| 20 | AUD-20261111-RESEARCH-OPS-NO-RECORD | S | research-ops fires but pass records do not land |
| 21 | ML-EQ-ENTRY-TIMING | M | Equity ML entries land ~15.6 min late: batched fetch + close-aligned poll |
| 22 | ML-ENTRY-UNIVERSE-LEVER | M | Run the ml_entry population test RQ-20261101-a24c-01 across venues |

### AM-TRADING (`session_01AFoLuMroLtrU2biw4ZDoBk`)

Real money first. p2 one-off: demotion proposals go to the operator via the manager. Desk v1 chain dated W49 behind DESK-ENTRY-REVIEW-REDESIGN.

**2026-11-12**

| # | row | size | what |
|--:|---|---|---|
| 1 | PHONE-LIVE-ACCOUNT-FEED | L | Phone executor streams live prop account feed (positions, venue SL/TP, P&L) |
| 2 | PROP-PLAN-EV-6M | M | 6-month expected-return ranking of prop plans for every firm |
| 3 | TRADEIFY-FUTURES-EVAL | S | Evaluate Tradeify's other account types: reuse, new avenues, roster builds, best plan |
| 4 | PHONE-CANCEL-FILLED-AS-SKIPPED | S | Phone stale-entry cancel marks a filled ticket skipped; check Positions first |
| 5 | PERF-F1-DEMOTION-SIGNAL | M | Per-trade backtest rows for ml_entry legs + config-date cut: demotion signal for real-mone |
| 6 | DD-SWITCH-OVERRIDE | M | Daily DD switch one-time operator override button, journaled and alerted |

**2026-11-13**

| # | row | size | what |
|--:|---|---|---|
| 7 | CLOSE-CLASS-NOC-TEST | S | Register net-of-cost test for the live-review CLOSE class |
| 8 | PROMOTE-TLT-1H-REAL-MONEY | S | Promote tlt_pullback_1h to real money after evidence rebuild |
| 9 | PR1111-SURVIVOR-PROMOTIONS | S | Tier-3 proposals for 1h ETF survivors tlt/qqq/slv/uso |
| 10 | TRADE-ACTION-DIRECT-PATH | M | Direct trade-action path: review lane acts at once; one-tap Approve executes |
| 11 | PROP-SIZE-EXCEEDS-DD-CUSHION | S | Prop phone entries: dd-floor cushion check on ticket size |
| 12 | LTR-ACCOUNT-SCOPED-ACTIONS | M | Single-account desk actions enforced per account in RiskManager |
| 13 | ML-PROP-ITERATE | L | Backtest every ML variant on the props until one passes the prop gate |

**2026-11-14**

| # | row | size | what |
|--:|---|---|---|
| 14 | TRADEIFY-OWN-LEG-DRIVER | M | Build tradeify_ml_leg.py: pooled ETH/SOL/XRP features, walk-forward, prop_gate V3 |
| 15 | DESK-ENTRY-REVIEW-REDESIGN | L | Desk v1 as an LTR-style entry review triggered by setups |
| 16 | LTR-FAST-MOVE-LOCKIN | M | Faster SL lock-in on fast impulse moves: trigger, pricing, apply speed |
| 17 | BREAKOUT-UNRECORDED | M | breakout_2 phone-executor trades not recorded in journal |
| 18 | ALPACA-CLOSE-BROKER-TRUTH | M | Alpaca closes: read filled bracket leg for broker's reason/price/time |

**2026-11-15**

| # | row | size | what |
|--:|---|---|---|
| 19 | EVIDENCE-DECISION-BAR-DEFAULT | S | Evidence builder: treat absent decision_bar as forming; relabel eth_4h / sol_prop records |
| 20 | STATUS-MOVE-OPEN-POSITIONS | M | Define and build what happens to open positions when a leg moves books |
| 21 | BYBIT2-PROMO-23935-OBS | S | Observe first clean bybit_2 + mirror trade for 3 legs promoted in #23935 |
| 22 | ZERO-QTY-EXPOSURE-EXPLAIN | M | Name the exposure ceiling in sized_qty=0 refusals + netted de-risk proposal |
| 23 | ORDER-PATH-RESIDUE-2 | L | Order-path residue: close-side cancel at all sites, orphan-adopt guard, max_qty, IB rearm |
| 24 | SMALL-ACCOUNT-RISK | M | alpaca_live notional cap, derived reachable set, per-account losing-streak floor |

**2026-11-16**

| # | row | size | what |
|--:|---|---|---|
| 25 | PNL-GROSS-VS-VENUE-6817 | S | Journal pnl gross local vs venue closed_pnl (trade 6817) |
| 26 | BRACKET-POSITION-TRUTH | M | Venue position/bracket read truth: bybit settleCoin, null reasons, trades.stop_loss synced |
| 27 | PROP-JOURNAL-INTEGRITY | M | Prop journal integrity: ticket pkg backfill, pnl basis, sl/tp on prop_fills, stale-balance |
| 28 | PROP-TRAIL-BAD-CANDLE-EXT | S | Prop trail replay reads a corrupt SOL low (ext 22.93, mfe_r 44.18) on tradeify_1/velotrade |
| 29 | LTR-FAST-MOVE-WAKE | M | Live-review fast-move wake: impulse event wakes review at once |
| 30 | PHONE-EMPTY-POSITIONS-MOBILE | S | Phone: empty mobile Positions view reads no_table and raises a false anomaly |
| 31 | PHONE-CLOSED-ORDERS-NEW-LAYOUT | M | Phone: read Closed orders on the new Breakout layout (Activity view) |
| 32 | PHONE-CAPTURE-POST-400 | S | Phone: step-capture POST rejected with 400, captures unread |

**2026-11-17**

| # | row | size | what |
|--:|---|---|---|
| 33 | PROP-ML-NEW-DATA | L | Non-price data (funding, OI, liquidations, depth, basis) for a fresh prop ML |
| 34 | BRACKETS-ALWAYS | M | Invariant: every open position always has both SL and TP, guarded on every order path |
| 35 | IR-TRADEIFY-NATIVE-SERIES | M | ~23h continuous-futures 1h series (SI/CL/ES/NQ) for Tradeify non-crypto fits |
| 36 | LTR-WAKE-COALESCE | M | Coalesce live-review wakes per package into the running reviewer |
| 37 | PHONE-READS-HARDENING-1026 | S | Phone: pin Breakout account path per device; prove Closed read returns rows |
| 38 | PROP-EXEC-PARTIAL-FILL | S | Prop executor partial fills: confirm-read check; DXtrade order Size semantics |
| 39 | PROP-EXIT-UNITS | M | Pre-registered prop exit units: SOL TP 3R fresh window; GTD time-close rung |
| 40 | PROP-GATE-ADA-XRP | M | Run prop survival gate for ada_pullback_2h, xrp_pullback_2h, xrp_4h |
| 41 | RM-ACTIVE-MGMT-MILESTONE | L | Every real-money leg has basic active management in production (umbrella) |
| 42 | RM-AM-ADA-TPX | S | ada_pullback_2h: declare tp_extend X6 on bybit_2/portfolio (unit passed) |
| 43 | RM-AM-DUE-COULDNOTLOOK | M | Live-review due route reads could-not-look on most packages; root-cause |
| 44 | RM-AM-STANDARD-GUARD | M | CI guard: refuse a real-money/prop leg without declared trail, TP grade, coverage row |
| 45 | RM-AM-TRAIL-EXPECTED-DETECTOR | M | Detector: MFE past trail activation but resting SL unmoved -> one red flag |
| 46 | VELO-NET-PNL-CASHTX | S | velotrade_1 close P&L is gross: net commission/financing from cashTransactions |
| 47 | PHONE-CANCEL-NOTFOUND-SKIPS-FILLED | S | Phone stale-entry cancel 'not_found' wrongly marks a FILLED ticket skipped |
| 48 | DIAG-LIVE-REVIEW-DUE-SLOW | M | /api/diag/live_review_due takes ~19 s and 502s; fix the slow read |
| 49 | TRADE-APPROVAL-PAPER-AUTO-GAP | M | Paper-auto LTR rows skip the Approve ask for their real-money/prop legs |
| 50 | CAP-TRADEIFY-TP-AMEND | M | tradeify_1 cannot move a TP (TP_AMEND_SUPPORTED False) |
| 51 | CAP-PROP-VM-CLOSE | L | Automatic close path for tradeify_1 and velotrade_1 (strategy exit, live-review close) |
| 52 | TPX-XRP-ADX25-REVISION | M | Declare a tp_revision producer for trend_donchian_xrp_adx25 (now real money) |
| 53 | PHONE-READERS-NEW-LAYOUT | M | Phone exec.js: closed-orders exit price + balance/realized readers on new layout |
| 54 | BYBIT2-MARGIN-PREFLIGHT-SAME-TICK | M | bybit_2 margin pre-flight sizes a 3rd same-tick order from stale balance |
| 55 | PROP-FIT-DONORS-PB-SQ | S | Add pullback/squeeze donors to p2_breakout_symbol_screen DONORS |
| 56 | STAGE2-OFFLINE-DEMOTION-SIGNAL | L | Offline demotion signal for Stage-2 legs: rolling Stage-0 re-measure + risk-aware early wa |
| 57 | PROMO-CHECK-ETHPROP-SOL | M | Run the promotion check for trend_donchian_eth_prop and trend_donchian_sol |
| 58 | SOL-PROP-REALMONEY-CHECK | M | Net-of-cost keep/pull check for trend_donchian_sol_prop on bybit_2 real money |
| 59 | JOURNAL-PNL-TRUTH | L | Journal exit price/PnL/label truth on remaining writer paths |
| 60 | PHONE-ORDER-FORM-NEW-LAYOUT | M | Phone: measure the new order form, lift ORDER_PATH_VERIFIED_ON_NEW_LAYOUT fence |
| 61 | LTR-ACTION-EXECUTOR-GAPS | L | Build missing live-review executors (add_size, prop VM close/reduce, Alpaca reduce/widen,  |
| 62 | PROP-GATE-UNREALIZED-DAYPNL | M | Prop status: velotrade_1 unrealized unreported; breakout_2 day_pnl unreported |
| 63 | RM-AM-PROP-TRAIL-OBSERVE | S | Prove chandelier trail amends resting SL on every prop account |
| 64 | CAP-PROP-LIVE-DRILL | M | Prove each code-only prop action once at minimum size (tradeify, velotrade, breakout_2) |
| 65 | PHONE-DRILL-TP-CLOSE | S | Phone executor: one TP-amend and one close drill on the device |
| 66 | EVIDENCE-LEVER-FORWARDING | M | Stage-0 evidence builder drops declared levers (skip_hours, trail_adx_*); fix, test, rebui |
| 67 | ETH-EXIT-TRAIL-GIVEBACK | M | Exit refinement for trend_donchian_eth 1h: random early close beats its exits by ~+155R on |
| 68 | HEALTH-20261104-LEVERAGE-PREFLIGHT-EQUITY | S | Leverage preflight sends equity symbols to Bybit every boot |
| 69 | FUT-CME-INTRADAY-HIST | L | CME micro intraday history (MES/MNQ/MGC 1m-5m, rolls, 2019+): IB or Databento |
| 70 | FUT-INTRADAY-DUKA-LANE | M | Wire Dukascopy 5m/15m into exit_lever_ablation, plus session-flat flag and per-contract co |
| 71 | RM-AM-ETH4H-ENTRYTP | M | trend_donchian_eth_4h: finite entry TP on top of measured-move (unit passed) |
| 72 | TP-PREDICT-HEAD | L | ML head that predicts move extent for a real predictive TP |

### AM-OPS (`session_01AFoLuJUGfpon2bNgwFbFmx`)

Export fix → importer race → BACKLOG-DRAIN-20261112 (p4). Governing spec for work-store rows: `docs/plans/WORK-STORE-DESIGN-2026-11.md`.

**2026-11-12**

| # | row | size | what |
|--:|---|---|---|
| 1 | HEALTH-20261111-EXPORT-READS-STALE | S | Off-VM register reads silently use the frozen export; read live store |
| 2 | WORK-STORE-IMPORTER-RACE | S | Work-store importer reverts native writes landing mid-import; fix PR #25201 |
| 3 | SEC-HOST-CHANGES-1112 | M | Four host security changes: fail2ban, gateway reboot, SSH hardening, split RSA key |
| 4 | MANAGER-VM-DIRECT-OPS | M | Direct manager-to-VM ops over HTTPS; manager reads alerts directly |
| 5 | WORK-GAP-ALERTS | S | Insight-link and topic-map gaps as numbers routed to manager alerts |
| 6 | SECURITY-HARDENING-AUDIT | S | Security audit umbrella: VMs, repos, UI |
| 7 | VENUE-KLINE-RATE-LIMIT | M | Bar-close kline fetch burst trips Bybit 10006 / Alpaca 429; stagger or share the fetch |

**2026-11-13**

| # | row | size | what |
|--:|---|---|---|
| 8 | HEALTH-20261111-IB-ACCTID-PUBLIC | S | vm-diag relay publishes the IB paper account id in public comments |
| 9 | HEALTH-20261112-JOURNAL-BAK-RETENTION | M | Cap journal-backup writers: ~12 helpers each copy the 2.6 GB journal, nothing prunes |
| 10 | PROPOSAL-ALERT-ROUTING | M | Shared awaits_operator() so every ready proposal reaches the decision queue |
| 11 | BACKLOG-DRAIN-20261112 | L | Backlog drain week of 11-12 (owned by OPDEC-P4) |
| 12 | HEALTH-20261111-LIVE-DISK-REGROWTH | M | Live VM root disk refilling |

**2026-11-14**

| # | row | size | what |
|--:|---|---|---|
| 13 | SEC-8001-LOCKDOWN | M | :8001 to HTTPS clients, bind localhost, drop firewall rule |
| 14 | ACTIONS-FROZEN-RUNS-CANCEL | S | Force-cancel ~410 stranded Actions runs |
| 15 | WORK-ROW-AGE-STALE | S | Served checklist rows carry stale updated_at |
| 16 | SEC-SELFHOSTED-RUNNER-PUBLIC | S | Non-ephemeral self-hosted runner on a public repo |
| 17 | CAP-VM-LOGS-ROOT-FIX | S | cap-vm-logs scans repo runtime_logs, not /data/bot-data |
| 18 | DEPLOY-WRAPPER-FALSE-SUCCESS | M | pull-and-deploy exits 0 when deploy_pull_restart.sh fails; restart keyed off pre-sync HEAD |
| 19 | SEC-API-OPEN-READS | S | API read surface open to the internet (site gate not armed) |

## 4. Throttle (after the surge; due 11-17 / 11-18, in order)

**AM-UI (3):** ALPACA-ORDER-HISTORY-PAGING, READ-SURFACE-CONTRACTS, DASHBOARD-RESET-ORPHANS

**AM-ML (67):** QUEUE-STALE-QUEUED-ONCE-STATUS, ML-DATA-WIRING, GRADE-EVERYTHING-CONTINUOUSLY, ML-ENTRY-DYNAMIC-SL, RESEARCH-UNIT-ID-REGEX, ML-RECIPE, KAGGLE-CPU-IDLE-20261105, ML-FS-SERVE-PARITY, EXIT-VOLTRAIL-TRAINSET-DRIVER, DATA-LABEL-TIES, IR-VOL-TARGET-SIZING-STAGE0, ML-ADVISORY-SCOPE-GUARD, ML-CONSUMER-LIVENESS, ML-DRIFT-ALERT-E2E, ML-DRIFT-COVERED-SPAN, ML-E2E-CHAIN-PROBE, ML-ENTRY-FINETUNE, ML-EXIT-ACTIONGRID-LABELS, ML-FS-ARCHIVE, ML-LINE-S2-CPCV, ML-LINE-S6-CUSUM-RETRAIN, ML-LINE-STATUS, ML-PARITY-FC-SHADOWLOG, ML-SLOT-REPORT, ML-TRAINER-TIMER-PROOF, ML-VOL-LABEL-LIVE-VERIFY, ML-VOLGATE-EXITHEAD-REPLAY, REGIME-WF-VERDICT-WRAPPER, SHORT-TF-PROGRAMME, TF-EQUITY-INTRADAY-BARS, TF-ORB-COST-STACK, TRAINER-DB-PATH-STRAY, TRAINER-SPARSE-SYNC, RESEARCH-AUTOMATION-PR-SELFHEAL, RESEARCH-OPS-HANDOFF-AGING, GRADER-INTEGRITY, TP-PREDICT-GRADER, RESEARCH-NO-WAIT, RESEARCH-TEMPLATE-LEG-GAPS, MARKET-DATA-LAKE, COST-PER-SYMBOL-SPREAD, COST-STACK-HARNESS-RESOLVER-REMAINDER, DATA-CATALOG, HARNESS-SETTLED-FUNDING, HOLDOUT-INCUMBENT-GRADE, NEWS-ALPHA-PROGRAM, NEWS-DATA-FRESHNESS, ROUTE-RESEARCH-DATA-ROUTES, RQ-470A-11-EMIT-REFUSED, AUD-20261111-PREDICATE-FALLBACK-DRIFT, RQ-EVIDENCE-006-KEYSET, RM-AM-EXIT-ML-WIRING, SIGNAL-CATALOG, M20-SWEEP-UPSTREAM-FAILURES, FRONTIER-STATIC-MARKETS, ML-QUEUE-DIVERSIFY, STRUCTURE-EXIT-ITERATE, ML-ITER-78FC-SCHEDULE, ML-TIMEFRAME, RQ-THROUGHPUT-FALSE-RED, TRAINER-REPLAY-PREGATE-OFFLOAD, PROMOTION-READINESS-CPU-GROWTH, TRAINER-MARKET-RAW-INCREMENTAL, BLOCKED-UNIT-ORPHANS, EXIT-HEAD-PULLBACK-DRIVER, ML-PRODUCERS, REGIME-WEIGHT-VARIANTS

**AM-TRADING (72):** TPX-XRP-DECLARE, AUD-20261104-FLATTEN-LABEL, AUD-20261028-MGC-JOURNAL-QTY, ORPHANWATCH-ALERT, REDUCE-LEG-PRICING, REDUCE-READERS-INCLUDE, HL-DATA-FETCHER, M18-ALLOCATOR-REEVALUATE, COVERAGE-MATRIX-REFRESH, DECISION-BAR-SESSION-INSTRUMENT, LIVE-DECAY-MONITOR, MANDATE-EVIDENCE-SNAPSHOT-CRON, SOL-PROP-REFINE, STAGE0-LONGER-WINDOW-1D, STAGE0-ROUTE-E4-DESK, BYBIT-SPOT-ADAPTER-DEAD, IB-CANCEL-TRADER-OWNED, AUD-20261104-AMENDMENTS-UNLOGGED, AUD-20261111-SIZE-UP-AT-CALLERS, LTR-WAKE-PAPER-NOISE, AUD-20261028-HOLD-VS-CLOSE-CONFLICT, DESK-FOLLOWUPS-1027, LTR-FOLLOWUPS-1028, LTR-GRADER-COVERAGE, TP-PREDICT-HEAD-GRADER, PHONE-FLAG-SECURE-FG-CHECK, DESK-MAKER-FILLS, IB-PAPER-INTRADE-EXECUTOR, LTR-CLASS-RULE-PACKAGE-N, LTR-HOLD-BIAS-BRIEF, LTR-STALL-TIMESTOP-S0, AM-REGRADE-BOOKSIM, AMEND-PARITY-ALPACA-OPTIONS, BYBIT1-SIZING-COLLATERAL-BASIS, CF-B2-BULK-LIVE, CF-C2-HARNESS-REST, CF-D1-LABELS, CF-D2-LTR-PRICING, CF-D3-BOOKSIM, CF-D4-PERFREVIEW-TABLE, DESK-1-VM-PACKETS, DESK-18G-JUDGED1-INTEGRITY, DESK-GATE-OFFLINE-PATH, DESK-V1, DESK-V1-EXPERIMENTS, DESK-V1-NO-PERBAR, DESK-V1-SCORECARD, DESK-V1-SOAK, DESK-V1-SPAWN, HARNESS-BE-RANDOM-CONTROL, LEVER-LIVE-CONSUMER-PARITY, LTR-10B-RESERVE-FOLLOWUPS, LTR-REVIEWED-AT-SECONDS, LTR-ROW-PACKET-SHA-DEFECT, LTR-TIGHTEN-WRAPPER, MOMENTUM-PARITY-FOLLOWUPS, PAPER-STOP-MISMATCH-ROOTCAUSE, PROP-BOOK-SEARCH-1095D, PROP-GATE-RECOST-AND-FLOOR, PROP-GRID-SURVIVAL-TOL, PROP-PKG-DBONLY-CLOSE, RETIRED-LEG-OPEN-TELEMETRY, RISK-OBJECTIVE-AUDIT, RM-AM-WIDEN-HARNESS, ROUTE-PROP-TRACKING, CAP-OPTIONS-ORDER-MGMT, SOAK-FAULT-INTAKE, ALPACA-CLOSE-REPRICE-NO-RESET, GLD-WEDGE-RETRO, SOAK-VOCAB-RETIRE, LTR-OPENR-ZERO-FALSE-GIVEBACK, PAPER-SPY-UNJOURNALED-1101

**AM-OPS (61):** GH-CAPACITY-INFRA-RUNNER, FREE-CAPACITY-PLAN, LIVE-PARITY-AVAX-CANDLE-MISMATCH, FUNDING-DAYS30-READ, REVIEW-COUNT-BY-DECISION, SIGNAL-AUDIT-ROTATION, VIRTUAL-LEG-POSITIONS, WORK-EXPORT-GUARDS-FROZEN, PREPUSH-TOOLCHAIN-BOOTSTRAP, SYNC-SECRETS-RESTART-OBS, WORKFLOW-PRUNE-FOLLOWUPS, TELEMETRY-HOOK-UNITS, DOC-INDEX-BASIS-RECONCILE, STRAT-ADX-DRY, SEC-OCI-INGRESS-READ, SEC-VM-POSTURE-READ, AUTOMERGE-SILENT-DISARM, SEC-DETECTORS, SEC-SSH-SINGLE-KEY, SEC-AUTH-FAIL-VISIBILITY, SEC-PAT-BLAST-RADIUS, SEC-REPO-HYGIENE, WORK-TOPIC-TAXONOMY, COMPUTE-ALLOCATION-DESIGN, AUD-20261104-TICK-SIZE-OWNERS, AUD-20261104-PIPELINE-DOC-PATH, AUD-20261104-PRODUCER-OK-OVER-CNL, AUD-20261028-NO-API-IMPORT-GUARD, AUD-20261028-TP-BASELINE-GROWS, AUD-20261111-RELAY-INVARIANTS-BRIDGE, REGISTER-CONSOLIDATION, WSD-S4-FOLLOWUPS, WSD-S6C-RECORD-LEDGERS, WSD-S5-STATE-VIEWS, SKILLS-PRUNE, COMPUTE-PREFER-KAGGLE, GUARD-PRUNE, SCOREBOARD-PCT-PERIOD, PURGE-ARTIFACTS-TRUNCATED-PAGE, AUD-20261028-DEMO-FLOOR-NO-EVAL, AUD-20261028-HEALTH-CLOSE-LIST-MISS, CLAIM-BASIS-ROWID-FP, RED-FLAG-HELPER, TICK-STAGE3-REGIME-SCORING, WSD-DRAIN-W1, BINANCE-METRICS-LOOKAHEAD, JOURNAL-OFFVM-BACKUP-DISPATCH-MODE, IB-GATEWAY-WATCHDOG-TIMER-INACTIVE, CHECKLIST-NOTE-NULLS-SUMMARY, PI-20261112-FANOUT2-0001, CONFIDENCE-AUDIT-FOLLOWUPS, CONFIDENCE-SCORE-EVERY-TRADE, GITLEAKS-HISTORY-FALSE-POSITIVES, CI-PURGE-ARTIFACTS-500, A1, SYSTEM-ACTIONS-SKIP-DISPLACES-PENDING, BACKLOG-DRAIN-2-PAUSED, CI-PLAYWRIGHT, E9, FUNDING-OI-DATASETS-ETH-SOL, LEDGER-REFRESH

## 5. Standing

CJ-7-WEEKLY-20261111 (AM-TRADING), LTR-TIGHTEN-FRESH-GO (AM-TRADING), EVIDENCE-CLASS-BACKFILL (AM-ML), AUD-20261104-ITERATION-ORPHANS (AM-ML), PROP-CANDIDATE-REVIEW (AM-TRADING), PRACTICE-REFRESH-THURSDAY-SLOT (AM-OPS), REGIME-PROGRAM (AM-ML). Plus the recurring checkups that never pause: daily review 05:52Z, research-ops 4×/day, live review + desk wakes, the weekly reviews, health checks, incident response.

## 6. Landed, observation owed (`landed_unproven`)

| row | AM | observation that closes it |
|---|---|---|
| CONFLICTING-EXPOSURE-ALERT | TRADING | /api/diag/live_review_due shows conflicting_exposure.state=read and ltr_wake_post_receipt shows one conflict sent. |
| PHONE-STALE-ENTRY | TRADING | one stale entry cancelled by the channel on a live prop ticket. Operator step on the row (cancel ETH limit 0.3936) to be re-checked by the TRADING AM. |
| ML-ENTRY-ALL-ACCOUNTS | ML | one ml_entry package per real-money account. |
| ML-ENTRY-LIVE-MONITOR | ML | the monitor reads the current served model id and a fresh data_through (diag), after the Sun 11-15 04:00Z retrain. |
| TICK-STAGE2-RECONCILE-OFFTICK | OPS | deployed sha includes it and tick_cost shows the order_monitor share moved off the tick. |
| UI-SIDEBAR-COLLAPSE-DESKTOP | UI | sidebar collapses on desktop in a browser (UI-SPA lane screenshot). |

## 7. Later (dated to a named ISO week)

| row | AM | date | reason |
|---|---|---|---|
| TRAINER-NIGHTLY-TRAIN-OFFLOAD | ML | 2026-11-16 | Re-scope after the retirement; trainer capacity only. |
| CALENDAR-EVENT-REACTION-STUDY | ML | 2026-11-23 | Weight-0 macro research, not top-line. |
| CJ-4-LABEL-VALIDATION | ML | 2026-11-23 | Blocked on CJ-3 and n accrual. |
| CJ-6-REVIEW-HOOKS | ML | 2026-11-23 | Blocked on CJ-2. |
| DATA-INTRADE-LABEL-STORE | ML | 2026-11-23 | Data plumbing for exit models; needed but not this week. |
| DESK-18D-JUDGE-2 | TRADING | 2026-11-23 | Desk edge not shown yet; operator parked it unless usage allows. |
| DESK-27-LIVE-FLOW | TRADING | 2026-11-23 | Much of the latency half now lives in TRADE-ACTION-DIRECT-PATH. Revisit after it lands. |
| FABLE-RESETS-PLAN | OPS | 2026-11-23 | Resets expire 2027-03-09; plan the spend week after this surge. |
| FRONTIER-LEVER-LEADLAG | ML | 2026-11-23 | Prior is LOW per the unit. |
| IR-INTRADAY-SEASONALITY-HARNESS | ML | 2026-11-23 | A new-idea harness, not top-line. |
| METALABEL-EMIT-REMAINING-FAMILIES | ML | 2026-11-23 | Only worth doing if 3a23-01 does not grade FAIL; wait for that grade. |
| ML-ARCH-GENERALIST-VS-SPECIALIST | ML | 2026-11-23 | A strategic ML design. The ML assistant manager should place it in the ML programme. |
| ML-DATA-XASSET-1H | ML | 2026-11-23 | Training-universe data, no live path this week. |
| ML-FS-STORE | ML | 2026-11-23 | Waits on the archive. |
| ML-HOLDBIAS-EXIT-MODEL | ML | 2026-11-23 | Needs the action-grid labels first. |
| ML-LEVER-PLAN | ML | 2026-11-23 | Waits on forward-data accrual. |
| ML-LINE-S3-GATE | ML | 2026-11-23 | Needs the two rules first; no overlay candidate this week. |
| ML-P1-COSTNET-REBUILD | ML | 2026-11-23 | p2pool-v2 is OFFLINE with no consumer (consolidation doc); not a this-week live path. |
| ML-P1-REGATE-POOLED-HEADS | ML | 2026-11-23 | Waits on the rebuild; heads have no consumer. |
| ML-RUNPOD-RESULT-LANDING | ML | 2026-11-23 | Exposure is bounded (unarmed fallback, free-only capacity plan), so it can wait. |
| OPRA-INDICATIVE-FEED | OPS | 2026-11-23 | No options leg near live. |
| OPTIONS-IV-HISTORY-GAP | OPS | 2026-11-23 | Research data gap; no option leg near live. |
| PROP-MISSION-MODEL | TRADING | 2026-11-23 | Operator said no rush. |
| SECRETS-UI-SCOPE | UI | 2026-11-23 | Scope doc after the redesign and sign-in land. |
| TF-IGNITION-HARNESS | ML | 2026-11-23 | New-strategy harness; no live path this week. |
| UI-CHART-EQUITIES-FEED | UI | 2026-11-23 | Due 11-25, after crypto phase 1; operator chose IEX free. |
| WEPE-BUILDOUT | ML | 2026-11-23 | Gated roadmap item; the gate is an operator call after a POC pass. |
| WSD-DRAIN-W2 | OPS | 2026-11-23 | After W1. |
| WSD-S6B-DESK-LTR-API | OPS | 2026-11-23 | Live-money-adjacent apply path; do after this week's desk fixes. |
| WSD-S6E-OPS-RECORDS | OPS | 2026-11-23 | Lower value than S5/S6c this week. |
| CJ-5-STUDENT-MANIFESTS | ML | 2026-11-30 | Two steps behind. |
| DESK-11-ML-FEED | TRADING | 2026-11-30 | Desk edge unproven (judged-1 INDETERMINATE); parked behind DESK-18D. |
| DESK-13-MANDATE | TRADING | 2026-11-30 | Mandate only after a desk S0 pass, none yet. |
| DESK-19-STUDENT-HANDOFF | TRADING | 2026-11-30 | Desk later phase; edge unproven. |
| DESK-20-OUTCOME-JOIN | TRADING | 2026-11-30 | Desk later phase. |
| DESK-21-NEVER-TRAINED-DETECTOR | TRADING | 2026-11-30 | Desk later phase. |
| DESK-22-SCORECARD | TRADING | 2026-11-30 | Desk later phase. |
| DESK-24-OFFLINE-SESSIONS | TRADING | 2026-11-30 | Desk later phase; would spend session capacity before edge shown. |
| DESK-25-OFFLINE-ABLATION | TRADING | 2026-11-30 | Desk later phase. |
| DESK-26-SYMBOL-ONBOARD | TRADING | 2026-11-30 | Desk later phase. |
| ML-FS-BRACKETS-HOLD | ML | 2026-11-30 | Two dependencies deep. |
| ML-PROMO-PARITY | ML | 2026-11-30 | Two dependencies unmet. |
| ML-UNIVERSE-RULE | ML | 2026-11-30 | Application is Tier 3 and waits on the a24c-01 forward read. |
| RM-AM-TP-PULLIN-PRODUCER | TRADING | 2026-11-30 | Two of the three tests failed. Build only if a real-money leg declares it. |
| WSD-DRAIN-W3 | OPS | 2026-11-30 | After W2. |
| WSD-S7-RETIRE-ARCHIVE | OPS | 2026-11-30 | Last step of the work store. |
| AMEND-PARITY-OANDA | TRADING | 2026-12-07 | Needed only when OANDA gets a roster. |
| DESK-23-COVERAGE | TRADING | 2026-12-07 | Later phase while the desk is off. |
| DESK-EVENT-LISTED-TOKEN-SCOPE | TRADING | 2026-12-07 | A low-priority universe lever. |
| ML-LINE-S5-CANARY | ML | 2026-12-07 | Three dependencies deep; Tier 3. |
| ML-NETR-RANKER | ML | 2026-12-07 | Parked by operator decision 10-22 until its gate clears. |
| UI-CHART-FUTURES-FEED | UI | 2026-12-07 | Due 12-09; spend decision with fresh quotes when it starts. |
| RESEARCH-EVIDENCE-AFTER-INPUT | ML | 2026-12-21 | Units cannot dispatch before 2027-01-04 anyway. |
| HOME-NODE | OPS | 2026-12-28 | Operator parked it. |
| DESK-EVENT-OI-FORWARD-CHECK | TRADING | 2027-10-04 | Its data does not exist until about Oct 2027. |

## 8. Closed today (close_done / superseded / duplicate)

| row | AM | reason on the terminal record |
|---|---|---|
| MGR-HANDOFF-2026-11-11 | OPS | done: successor manager 2026-11-11a took over and is running; evidence: this planning lane's dispatch 2026-11-12 |
| RENAME-SLUG-FUNCTIONAL-AUDIT | OPS | done: #24942 merged 2026-11-11T21:02Z; remaining old-slug hits are labels/fixtures per its PR table |
| DESK-18B-JUDGE-RUN | TRADING | done: judging run produced judged-1 (PR #20475); verdict INDETERMINATE recorded on the row |
| ML-RQ-RUNNER | ML | done: runner merged (#17609-#17611); ML units run through it |
| UI-UPGRADE-1 | UI | superseded_by:UI-REDESIGN-2026-11 (operator spec 2026-11-09 replaces the October upgrade) |
| HEALTH-20261111-TRAINER-NO-NEW-MODELS | ML | duplicate_of:ML-TRAINER-TIMER-PROOF: Fold into ML-TRAINER-TIMER-PROOF so one lane answers produced->labelled->trained once. |
| ML-ENTRY-EQ-REFRESHER-SILENT | ML | done: Row note 11-11: builder scored the 20:00Z bar for both legs (9 + 8 below_tau, 0 packages); mechanism works end to end; latency moved to ML-ENTRY-EQ-PRESCREEN. |
| ML-REGISTRY-LADDER-GAPS | ML | superseded_by:ML-PROGRAMME-CONSOLIDATION: Remaining unassigned rows are handled by the consolidation retire waves. |
| ML-ENTRY-EQ-STRUCTURE-RETEST | ML | superseded_by:ML-ENTRY-EQ-STRUCT-LIVE: The real-money decision this retest fed was already made on the struct model. |
| ML-ENTRY-SERVED-RECENT-NEGATIVE | ML | duplicate_of:CRYPTO-ENTRY-RETRAIN-UNIT: One diagnosis lane, one row. |
| ML-ROADMAP-MECE | ML | done: docs/plans/ML-ROADMAP-MECE-2026-11.md on main (PR #22892); row note says only operator questions 3/4/5 remain. |
| ML-LIVE-FIRST | ML | done: config/accounts.yaml: ml_entry live on bybit_2/bybit_portfolio (line 483/895) and ml_entry_eq_struct on alpaca_live/alpaca_portfolio since 11-08. |
| ML-ENTRY-RETRAIN-CADENCE | ML | done: .github/workflows/ml-entry-retrain.yml on main with cron '0 4 * * 0' and freshness.json; row note: deployed 11-06 18:38Z, freshness observed fresh. |
| ML-ENTRY-EQUITY-NATIVE | ML | done: Consolidation doc lists ml-entry-eq-v1 (alpaca_paper) and ml-entry-eq-struct-ens5-v1 (LIVE, alpaca_live) in D3; row note records the time-disjoint read n=858. |
| MARK-FLATTENED-SQLITE-PREVIEW | TRADING | done: PR #24964 (c280c2a28c) 'system-action wrappers: read-only SQL via db_read.py'; remaining sqlite3 hits in *_action.sh are python-module imports. |
| ML-LEVER-HARNESS | ML | done: scripts/research/ml_entry_levers.py on main (built 11-01 with self-test); only the b603 cadence arm is unbuilt. |
| ML-MES-REGIME-1D-SILENCE | ML | superseded_by:ML-PROGRAMME-CONSOLIDATION: If wave 2 retires it, the silence question disappears. |
| ML-REGIME-15M-DRIFT | ML | superseded_by:ML-PROGRAMME-CONSOLIDATION: Wave 2 decides these heads; separate remediation would duplicate it. Verify the live fc-pcv-v2 heads are not the 75b2 subjects before closing. |
| REGIME-EQUITY-LEG-FETCH | ML | done: research-script-run.yml:108 pins yfinance==1.7.0; exit_lever_ablation.py:719 has --non-crypto-source dukascopy; 0 c56e units remain in research/queue/blocked/. |
| REGIME-UNITS-W45 | ML | done: research/queue has regime-theme units authored 11-05 (23ca-01..05) and 11-07 (47b6-01..08), plus 11-10/11-11 batches: 19 RQ-202611* units with theme regime. |
| TEST-REVERSE-RECON-DATE-DECAY | TRADING | done: tests/test_reverse_reconciler.py on main builds created_at relative to now (comment: '2026-09-27 package aged out ... these tests went red'). |
| VOLUME-COMPOSITION-RESEARCH | ML | done: Units authored and registered: #24993 (count-vs-size units + runner) and #25161 today (RQ-20261112-0bc8-01/-02 feature-add bake-offs, before any run). |
| VENUE-SCOPE-HYPERLIQUID | TRADING | done: #24928 merged: Hyperliquid/trade[XYZ] scoping, two Stage-0 units filed (blocked on data, now served by HL-DATA-FETCHER). |
| ETF-HISTORY-PIPELINE | OPS | done: After #24847 the etf-history-pipeline.yml scheduled runs are green: 2026-11-11T19:51Z success and 2026-11-12T07:42Z success (the earlier 3 failed). That meets the row's own close condition (next |
| ML-FS-ARCHIVE-WIDE | ML | superseded_by:MARKET-DATA-LAKE: The lake is the config-driven universe archive the row asked for. |
| DATA-DERIV-ARCHIVE | ML | superseded_by:MARKET-DATA-LAKE: Close and re-point blocked da7a-03 at the lake inside ML-DATA-WIRING / MARKET-DATA-LAKE. |
| DATA-KLINE-ARCHIVE | ML | superseded_by:MARKET-DATA-LAKE: The lake is a wider version of this archive. |
| IAUM-RECORD-OR-PULL | TRADING | done: iaum_pullback_1d is no longer on alpaca_live (accounts.yaml alpaca_live = tqqq_trend_long_1d, ml_entry_eq_struct). It is on alpaca_paper, and a record was rebuilt on 2026-11-05 (comms/strategy_e |
| LIVE-BT-STAGE-B | TRADING | done: #18870 merged (live_bt_trade_join.py on main; results under comms/research/live_bt_join/2026-10-18/; PI-20261015-10152047-0001 closed). The row says the state goes to done on merge. |
| P3-QUEUE-HYGIENE | ML | done: Sampled 7 of the named units in research/queue: every duplicate/no-roster one is status retired (20261005-005, 20261010-002, 20260929-010, 20260928-017, 20261003-002); the kept ids are queued; R |
| PASS-TO-DECISION-SLO | ML | superseded_by:AUD-20261019-RESEARCH-SLO-RED: the research SLO work is owned by lane OPDEC-P7-RESEARCH-SLO (operator p7, 2026-11-12), PR #25184 'research SLOs: survivors by the operator's definition' |
| SLV-PB1D-RETENTION-T3 | TRADING | done: #19888 merged 2026-10-24: slv_pullback_1d demoted to Stage 1 (removed from alpaca_live and alpaca_portfolio); accounts.yaml confirms it is on alpaca_paper / alpaca_options_paper only. |
| SPLG-TICKER-DEAD | TRADING | done: #21006 merged 2026-10-28: config/strategies.yaml splg_trend_long_1d symbols: [SPYM] (Tier 3). |
| UI-OVERVIEW-WORK-PROP | UI | superseded_by:UI-REDESIGN-2026-11: Covered by UI-REDESIGN-2026-11 and PROP-UI-BRACKETS-CLOSED; keeping it invites a re-spec. |
| RESEARCH-SLO-CADENCE | ML | superseded_by:AUD-20261111-RESEARCH-OPS-NO-RECORD: The threshold now matches the cadence; the live breach has its own row. |
| LANE-STRUCTURE-WEEK | OPS | superseded: Manager 2026-11-11a set up four assistant managers (UI/ML/TRADING/OPS) on 2026-11-12, each owning its class's rows; this weekly planning assigns every row to one (docs/plans/weekly/2026-11 |
| REPORTS-INDEX-STALE | UI | superseded_by:UI-REDESIGN-2026-11: The operator answered the re-wire-or-retire question on 11-09; no separate row needed. |
| STOP-HOOK-ROTATION-MANAGER | OPS | done: scripts/ops/lane_report_stop_hook.py:24-25 and the self-test at :159 on origin/main cover 'You are the JTA Trader manager (rotation)'. |
| AUD-20261028-DUE-DOUBLED | OPS | duplicate_of:AUD-20261104-TWO-PICKUP-REGISTERS: Same class held by another row. |
| AUD-20261104-TWO-PICKUP-REGISTERS | OPS | superseded_by:BACKLOG-DRAIN-20261112: The design half is done; the drain has its own owner. |
| AUD-20261104-ROWS-WITHOUT-DUE-BY | OPS | superseded_by:WSD-DRAIN-W1: Same goal as the funded drain waves. |
| AUD-20261104-OWNER-LIVENESS-ZOMBIE | OPS | duplicate_of:WSD-S5-STATE-VIEWS: Same fix is in WSD-S5. |
| AUD-20261111-AUDIT-ROWS-NOT-LANED | OPS | done: weekly planning 2026-11-12 gave every queued AUD row an owner (assistant manager), week_lane or later date; docs/plans/weekly/2026-11-12/WORKPLAN.md |
| UI-CATALOG-STRATEGIES-ML | UI | superseded_by:UI-REDESIGN-2026-11: Covered by UI-REDESIGN-2026-11. |
| UI-CONSOLE-CONNECTOR | UI | done: The connector is live: this session lists JTA_Trader tools (hello, inbox, workplan, ml_roadmap, performance, system_health, data_query, work_rows); src/console_connector/ on main; UI-CONSOLE-CON |
| UI-CONSOLE-TABS-DATA | UI | done: workplan, ml_roadmap, performance, system_health and data_query (+ inbox) are live connector tools in this session; src/console_connector/tabs.py on main. |
| HOLD-MERGE-ALARM-DEAD-LETTER | OPS | done: PR #25078 merged: 'hold-merge alarm accepts a recorded operator approval and actually delivers its ping'. |
| PROMPTS-PNL-FIRST | OPS | done: 'sceptical quant' now appears in manager, health-review, ml-review, performance-review and weekly-audit SKILL.md on origin/main. |
| SHADOW-FACTORY-TEST-PATH-FLAKE | OPS | done: tests/ml/test_shadow_factory.py:389-410 now monkeypatches a PermissionError for /home/ubuntu and asserts the mirror fallback. |
| ALERT-NOISE-SUPERSEDED-CANCEL | OPS | done: claude-run-failure-alert.yml:405-459 on main has a 'superseded' step (2026-11-05 note on work-digest) that suppresses the ping. |
| AUD-20261028-LTR-CLOSE-REPLAY-MISMATCH | TRADING | done: Fix PR #21256 merged; the row says close on #21256 merge (replay_mismatch 3 to 1). Leftover: reviews.jsonl should stamp applied back. |
| KAGGLE-CPU-7B6F27-STUCK | ML | done: comms/research/RQ-20261031-7b6f-27 and research/results/RQ-20261031-7b6f-27 now exist on main. |
| LIVE-NUMBERS-STREAMING | UI | superseded_by:UI-TRADING-PUSH: Same goal, now built in UI-TRADING-PUSH. |
| LU-OBSERVATION-DRAIN | OPS | superseded_by:WSD-DRAIN-W1: Same drain. |
| PIPELINE-DUE-TRIAGE-SWEEP | OPS | superseded_by:BACKLOG-DRAIN-20261112: Duplicate scope of this week's drain. |
| RQ-470A11-RECORD-REFUSED | ML | duplicate_of:RQ-470A-11-EMIT-REFUSED: Duplicate. |
| RQ-RECEIPT-SKIP-STARVES | ML | done: research-queue-dispatch.yml (~line 703) only counts receipt PRs under 90 minutes old (fix for #20788), so a stuck PR no longer blocks. |
| UI-SPA-RETIRE-CONSOLE-PAGES | UI | superseded_by:UI-REDESIGN-2026-11: The operator's later spec replaces it. |
| VM-DISK-GROWTH-20261102 | OPS | superseded_by:HEALTH-20261111-LIVE-DISK-REGROWTH: Superseded by the newer row. |
| LTR-ROWS-BRANCH-STALE-VALIDATOR | TRADING | done: Fetched origin/live-review/rows (tip 2026-11-12 11:07). git diff against main for scripts/ci/check_live_review_records.py and the schema is empty. |
| DESK-E535-04-SCORER-DEFECT | TRADING | done: PR #20811 merged 2026-10-28 05:53Z (fixed driver, unit re-queued, verdict INDETERMINATE on re-run). |
| BOOK-CORR-VIEW-LTR | TRADING | done: scripts/ops/live_review_packet.py:1261 emits context.correlated_open_packages. |
| BOOK-SIM-REAL-SIZER | TRADING | duplicate_of:CF-D3-BOOKSIM: One row (CF-D3) owns it. |
| BRACKETS-AS-PREDICTIONS | TRADING | superseded_by:RM-ACTIVE-MGMT-MILESTONE: Two umbrellas for one goal. Keep RM-ACTIVE-MGMT-MILESTONE. |
| DESK-10-CAPACITY | TRADING | done: scripts/ops/spend_meter.py:620 prints DESK SCALE lines. The row note records costs measured 2026-10-27. |
| DESK-18E-LIVE-PROPOSAL-RATE | TRADING | done: docs/research/desk-18e-live-proposal-rate-2026-10-27.md gives the root cause (<=60 min hold prices negative) and the brief fix. |
| LTR-0-PARITY-FIXTURE | TRADING | done: tests/fixtures/ada_pullback_2h_eba2_03_trades.jsonl is on main and used by tests/test_live_review_outcomes.py. |
| LTR-4-ROUTINE | TRADING | done: comms/live_review/reviews.jsonl on main has 650 rows; the newest is reviewed 2026-11-12T08:20Z. The routine is running. |
| LTR-6-APPLY-PATH | TRADING | superseded_by:LTR-6R-APPLY-PATH: Superseded. |
| LTR-6R-COULDNOTLOOK-FIX | TRADING | done: live_review_apply.py pins LIVE_REVIEW_IB_MD_CLIENT_ID = "601" (lines ~209-215, test-pinned). A could_not_look verdict exists at :1252. |
| LTR-7-MANDATE | TRADING | done: config/mandates.yaml:1115 has MD-LIVE-TIGHTEN-SL (superseded_by MD-TRADE-DESK, :1167). |
| LTR-8-PROP-TIGHTEN | TRADING | done: src/prop/bracket_request.py uses meta.sl_floor. src/prop/phone_trail.py:601 defines request_sl_tighten. |
| LTR-COUNTERFACTUAL-PRICING | TRADING | duplicate_of:CF-D2-LTR-PRICING: One row owns it. |
| LTR-EVIDENCE-TD1H | TRADING | done: comms/strategy_evidence/trend_donchian_1h.json exists on origin/main. Not checked: whether a fresh packet carries priced_options. |
| LTR-MECHANICS-SIBLING-SLICE-FALSE-MISMATCH | TRADING | done: scripts/ops/live_review_packet.py:309 _venue_exit_prices matches by package ids. With siblings and no id match it returns level None and ambiguous, never a mismatch. |
| OVERVIEW-PROP-OPEN-TRADES | UI | superseded_by:DASH-PROP-OVERVIEW: Owned by the UI lane. |
| PHONE-TRAIL-NOHALT | TRADING | done: src/prop/phone_trail.py:236-240 drops persisted locked/ended. MAX_NO_POSITION gives one red flag and is "never ended" (:79). |
| TP-DECLARE-ALPACA-PB1D | TRADING | done: strategies.yaml: slv/ief/iaum_pullback_1d tp_r 3.5 with tp_intent basis RQ-20261016-014_pooled_kstar_3.5R. The operator decided 2026-10-22. |
| TP-REVISION-RECORD-CONTRACT | TRADING | done: scripts/research/tp_revision_sweep.py:219-242 now returns verdict, read_state, population and n. Not checked: whether --recollect-orphans is scheduled. |
| TRADEIFY-PLATFORMS | TRADING | superseded_by:TRADEIFY-FUTURES-EVAL: The in-flight lane answers it. |
| LTR-PACKET-PROP-TP-READ | TRADING | done: c26311c0a7 (#24956, merged 2026-11-12 03:41Z, after the row's 01:30Z recurrence): 'live-review packet: compare prop venue SL and TP; no vacuous match'. Deployed/observed not checked. |
| PHONE-SCREENSHOTS | TRADING | superseded_by:PHONE-SELF-DIAGNOSE: Absorbed by another row; close as superseded. |
| RESEARCH-LOSS-DETECTOR-RED | ML | superseded_by:M20-SWEEP-UPSTREAM-FAILURES: Only remaining cause is owned by another row. |
| MGR-HANDOFF-2026-11-09 | OPS | superseded_by:Manager Session 2026-11-11a: A handoff record whose successor already took over; nothing left to build. |
| PHONE-POSITIONS-EMPTY-STATE | TRADING | done: fa503e15cf (#24887): 'phone exec.js 2026-11-11.1: the empty Positions view reads flat ... not no_table'; PHONE-DRILL row says it is signed + loaded on the heartbeat. |
| BRANCH-PROT-PUT-500 | OPS | done: gh run list branch-protection-sync: schedule runs 2026-11-10 and 11-11 success (11-08/11-09 failure). |
| ML-DIRECTION-1H-NO-SKILL | ML | superseded_by:ML-RETIRE-WAVES-20261111: eth-direction-1h manifests moved to ml/configs/retired/ (#25001); 0 direction manifests outside retired/ on main |
| SYSTEM-AUDIT-REPO-FLOWS | OPS | superseded_by:WSD-S7-RETIRE-ARCHIVE: Its work lives in the WSD rows; keeping it duplicates them. |
| ETF-HISTORY-REFRESH-RED | OPS | done: gh run list etf-history-pipeline: schedule run 2026-11-12 07:42Z success, plus 3 dispatches success 11-12. |
| IAUM-6655-NAKED-FLAT | TRADING | done: Row note: measured conclusion recorded (TP leg cancel real; per-symbol re-read: 0 bare single-leg cancels, closes were ours); returned to queue only by the 11-06 lane sweep. |
| ETF-HISTORY-PIPELINE-LOWDISK | OPS | duplicate_of:ETF-HISTORY-REFRESH-RED: Duplicate and resolved. |
| ALPACA-PAPER-KEYS-R3 | ML | done: scripts/ci/check_research_script_run.py:91-92 on main allows the PAPER pair (operator 'Allow paper pair (Rec.)'); RQ-20261104-a41f-01 has results 41929994350 / 42047465240. |
| A8 | OPS | done: Live /api/bot/work/brief 2026-11-12 pipelineStats: unrouted 0, unrouted_alarm count 0 (closing test: unrouted trends to single digit). |
| E36 | TRADING | superseded: pairs sleeve retired by record (config/pairs.yaml pairs: [], #24991, operator 'Retire it'); successor idea FRONTIER-STATIC-MARKETS |
| E37 | TRADING | superseded: pairs sleeve retired by record (config/pairs.yaml pairs: [], #24991, operator 'Retire it'); no pairs leg to promote |
| ML-HYGIENE | ML | superseded_by:ML-RETIRE-WAVES-20261111: The retirement waves did this work. |
| ML-PRODUCER-FUNDING | ML | superseded_by:ML-RETIRE-WAVES-20261111: btc-regime-1h-lgbm-funding-svble-v1 retired (ml/configs/retired/, #25001) |
| PROP-GOLIVE-PREAPPROVAL | TRADING | done: breakout_1 retired 10-08 (row note); tradeify_1 is a live prop leg (config/accounts.yaml:278 names legs live on breakout_2/tradeify_1/velotrade_1). |
| ROUTE-AND-ASK-TRIAGE | OPS | done: Live /api/bot/work/brief 2026-11-12: unrouted 0, unrouted_alarm breached [] (its requirement: unrouted == 0 and no alarm). |
| VELOTRADE-API-PROBE | TRADING | done: src/prop/platform/dxtrade_api.py on main and PROP-BRACKET-APPLY (#25016) use the DXtrade API adapter (bracket_request.py names dxtrade_api). |

## 9. Kill candidates — NOT applied (for the manager's decisions page; p7: reason + data)

| row | AM | reason and supporting data (from the row note) |
|---|---|---|
| ML-P1-EXIT-CANDIDATES-BUILD | ML | Its only stated purpose was B4 (now not needed) and exit-policy-v1, which has no row or unit on main pointing at it. Data: 10-30 manager note: no longer a B4 prerequisite; exit-head unit RQ-20261101-78fc-03 is already done without it. |
| ML-P4-CONVICTION-REGATE | ML | Row's own prior p(pass) ~0.1, model is OFFLINE with no consumer, and sizing reads it in annotate mode only. Data: RQ-20261101-78fc-06 blocked_on it; consolidation: conviction-meta-v1 OFFLINE, no consumer; CONVICTION_SIZING_MODE=annotate. |
| ACCOUNT-SNAPSHOT-BALANCE-HISTORY | OPS | Close as accepted: the balances are small and already public, and a rewrite is irreversible and breaks every clone. This needs the operator's word. Data: The writer is fixed going forward (schema 2, test_committed_snapshots_carry_no_balance). History is not purged; a purge needs a force-push of main |
| MACRO-BACKFILL-E5 | ML | Kill with 010 retired. Data: the cost term is constant per entry and both graded statistics are shift-invariant, so the build buys an uninformative run (P4-MACRO-BACKLOG-1016 arithmetic). Data: RQ-20260928-010 is still in blocked/. The P4 lane showed (thesis_backtest.py) that cost is a constant per  |
| PHONE-EXEC-FLAKE | OPS | One recorded failure in about 5 weeks; kill if the 30-day pytest-run log scan shows 0 recurrences. Data: One failure 2026-10-07/08; no recurrence recorded in the row since. Check pytest-run failures mentioning test_phone_executor over the last 30 days. |
| GLD-VENUE-STOP-MISMATCH | TRADING | Kill: the leg is retired and off every roster, and the class has an owner. Data: gld_pullback_1h is enabled:false (strategies.yaml) and not on the alpaca_paper roster (accounts.yaml). The mismatch class is owned by PAPER-STOP-MISMATCH-ROOTCAUSE and SHARED-BRACKET-FIX. |
| RM-AM-ETHPROP-TRAIL45 | TRADING | Kill: the leg is off every prop and real-money roster. It can be re-proposed if the leg is promoted again. Data: trend_donchian_eth_prop is on bybit_1 only. It is on no real-money or prop roster (accounts.yaml), so the prop/real-money packet has no target. |
| RM-AM-IAUM-COSTNEUTRAL | TRADING | Kill: not a real-money leg any more, so the real-money AM confirmation does not apply. Data: iaum_pullback_1d is no longer on alpaca_live (roster tqqq_trend_long_1d, ml_entry_eq_struct). It is on alpaca_paper only. |
| RM-AM-SOLPROP-TP25 | TRADING | Kill: the pre-registered confirmation failed. sol_prop keeps tp_r 6.0 until a new candidate passes. Data: RQ-20261028-a7c3-03 status done, verdict FAIL (harness confirmation of 2.5R). |
| RM-AM-XRP4H-MM | TRADING | Kill: the pre-registered unit failed. xrp_4h keeps tp_r 3 with no revision. Data: RQ-20261028-a7c3-02 status done, verdict FAIL. |
| SOL-PROP-GATE-FIX | TRADING | Kill: the prop-gate question is moot now that the leg is off the prop books. Data: sol_prop is on no prop roster (breakout_2/tradeify_1/velotrade_1 roster eth_4h, sol_4h, ml_entry). It trades only on bybit_2/bybit_portfolio. |
| JOURNAL-LOCK-RESIDUAL | OPS | Data: pairs_tick no longer runs and the lock was seen once (n=1); re-file if tick timing shows it again. Data: The journal_sync.wait half was measured on pairs_tick, now a no-op (config/pairs.yaml pairs: [], #24991); the single 5 s lock (n=1, 11-06) holder is unnamed. |
| ML-HEAD-AGREEMENT-JOIN | ML | Data: 2 of the 3 regime heads it joins were retired 2026-11-11; the 3-head agreement instrument has no subjects. Data: RQ-20261011-17f4-03 still blocked; btc/sol regime-15m heads are on the 11-11 demote list (registry-demote-2026-11-11.txt). |

Each row stays in its state with `week_lane` cleared and due 2026-11-18 for the decision. PHONE-EXEC-FLAKE needs one more check before it is a real candidate (pytest-run failures naming test_phone_executor over the last 30 days).

## 10. Operator questions (to the manager, not the operator)

- **LIVE-DECAY-MONITOR** — Second carry-over (11-04 → 11-11 → now): schedule it as a surge row, date it to W48, or kill it?
- **PROMOTE-TLT-1H-REAL-MONEY** — tlt_pullback_1h earns only short-side; alpaca_live is long-only: keep it on paper, or open a shortable real-money path?
- **PR1111-SURVIVOR-PROMOTIONS** — slv_pullback_1h passes (365d +44.71R n69; holdout +35.99R n104) but the operator said on 2026-08-24 it 'MUST NOT BE PROPOSED BACK': keep the ban or lift it?
- **TPX-XRP-DECLARE** — b5 read-back: keep X31 on the demo floor and watch the first extend (recommended), paired test first, or remove?
- **DESK-18D-JUDGE-2** — Desk entry generation: event-driven entries, a universe change, or keep parked?
- **DESK-ENTRY-REVIEW-REDESIGN** — The 4 questions in docs/design/desk-entry-review-redesign-2026-11-11.md § 6.
- **WEPE-BUILDOUT** — World Event Prediction Engine: open stage 1 or park?
- **ML-PROGRAMME-CONSOLIDATION** — Approve wave-1 retirement of the 72 RETIRE models?
- **ML-ROADMAP-MECE (closed)** — MECE Q3 breed names, Q4 Foxhound widening, Q5 M12 reporting-only — still open.
- **ML-ADVISORY-SCOPE-GUARD / LEVER-LIVE-CONSUMER-PARITY / PROP-GATE-RECOST-AND-FLOOR / RM-AM-STANDARD-GUARD** — Each would add or tighten a CI gate: permit, or build as a report only (No new gates rule)? Lanes must NOT build the gate half until answered.
- **FUT-CME-INTRADAY-HIST** — CME intraday history: free via the IB gateway (slow) or pay for Databento GLBX.MDP3?
- **PHONE-ORDER-FORM-NEW-LAYOUT** — Operator step: open the Breakout order form by hand once (no submit) so the phone captures it; unblocks breakout_2 entries.
- **SMALL-ACCOUNT-RISK** — Max notional per position (fraction of equity) on alpaca_live?
- **ACTIONS-FROZEN-RUNS-CANCEL / SEC-8001-LOCKDOWN** — create_session was refused by the classifier this morning: operator acts in the GitHub UI / VM, or allows a session to?
- **SEC-API-OPEN-READS** — Arm SITE_AUTH_ENFORCE now, or wait for UI-OAUTH-SIGNIN?
- **SEC-PAT-BLAST-RADIUS** — BRANCH_PROTECTION_TOKEN's real scope and expiry (operator's GitHub settings).
- **PNL-GROSS-VS-VENUE-6817** — Store the venue's net closed_pnl where the venue is trusted?
- **ACCOUNT-SNAPSHOT-BALANCE-HISTORY** — Accept old balances in git history (close) or purge with filter-repo + force-push?
- **SKILLS-PRUNE** — Skills-prune decision 4 (docs/audits/2026-11-06-skills-prune.md): approve or drop?
- **UI-WORKPLAN-QUESTIONS-1111** — Answer the 8 UI questions or let the UI lane keep its defaults?
- **CAP-TRADEIFY-TP-AMEND** — Build TP amend for tradeify_1, or record a static TP?
- **FABLE-RESETS-PLAN** — Which week for the two Fable resets (before 2027-03-09)?
- **OPTIONS-IV-HISTORY-GAP** — Buy the CBOE DataShop IV sample or stay keyless?
- **LEDGER-REFRESH** — Issue a read-only SUB-account Bybit key for bybit_2 broker truth, or keep the CSV export?
- **ML-LEVER-PLAN** — Re-point b610-01 at W1 2026-10 now, or wait for forward data?
- **ml_entry on bybit_2 (a5 read-back)** — Keep both sides live + fix gate evidence + 40-trade checkpoint (recommended), shorts only, or step down to bybit_1?

Resolved by today's answers, not re-asked: DESK-V1 wake (p6, operator flips `desk_wake`), FEATURE-IMPACT-MAP confirm (m6), UI repo access (m2).

## 11. Corrections this lane made to the triage (verified)

- TRADEIFY-FUTURES-EVAL: triage said duplicate → kept surge, in_flight on lane session_01AFoLuLUwRU7eg9KzpMcxWu (operator's 11-10 item; manager 09:07Z).
- TRADE-ACTION-DIRECT-PATH: lane re-pointed from archived session_01AFoLuJRcgEM7nWVNbrYHgx to live phase-3 lane session_01AFoLuLp28byLnMmk2UZuLf (get_session 09:12Z, idle on #25187 CI).
- MANAGER-VM-DIRECT-OPS: its lane is the archived JRcg session → OPS AM.
- ML-AM-NEXT-LIVE and CJ-7-WEEKLY-20261111: blockers cleared (TMBENCH-QTM1B-BUILD done; diag token 200) → unblocked to queued.
- REGISTER-CONSOLIDATION: triage 'already_done' is wrong — it closes with WSD-S7-RETIRE-ARCHIVE (queued) → kept, throttle.
- AUD-20261104-FLATTEN-LABEL: triage 'already_done' rested on a docstring; WEEKLY-AUDIT-20261111 L0 marks it UNRESOLVED → kept, throttle.
- Merged-not-observed rows set to landed_unproven, not done: CONFLICTING-EXPOSURE-ALERT (#25022), ML-ENTRY-LIVE-MONITOR, TICK-STAGE2-RECONCILE-OFFTICK (#23200), PHONE-STALE-ENTRY (#24469), ML-ENTRY-ALL-ACCOUNTS (accounts.yaml), UI-SIDEBAR-COLLAPSE-DESKTOP (dashboard #237).
- ML-DIRECTION-1H-NO-SKILL, ML-PRODUCER-FUNDING, E36, E37: triage kill candidates → closed as superseded by existing retirement records (#25001; pairs: [] #24991, operator 'Retire it'); not new kills.
- PASS-TO-DECISION-SLO: 'superseded by an open PR' → pointed at the governing row AUD-20261019-RESEARCH-SLO-RED.
- LANE-STRUCTURE-WEEK, AUD-20261111-AUDIT-ROWS-NOT-LANED: closed by this planning's four-AM assignment.
- LTR-FAST-MOVE-LOCKIN: triage throttle → surge (operator 11-10 real-money item).
- Carry-over rows re-slotted ahead of new surge rows in each class (120 slot changes).

## 12. Follow-ups this plan creates

- Each AM reports to the manager; the throttle-down switch is recorded on WEEKLY-PLANNING with the usage reading it was made on (protocol item 4).
- Kill candidates and §10 questions → the manager's decisions page (manager skill § 'Decision docs').
- Next Thursday's step 0 grades this plan: `review_followthrough.py --window-days 7` and the surge rows' states.

