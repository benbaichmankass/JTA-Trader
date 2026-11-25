# Desk development plan, W48 (for Thursday 2026-11-26 planning)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `DESK-DEV-W48` (row `DESK-DEV-W48`, roadmap `L-DESK-V1`)

**Gates this adds or changes: none.** Operator ask 2026-11-25: set aside capacity for desk work and desk development, to make it more functional and better.

## 1. How the desk performs now (measured 2026-11-25 on `origin/main`)

| read | population | value |
|---|---|---|
| desk decisions | `comms/desk/decisions.jsonl`, 239 rows, 2026-10-26..2026-11-20 | 207 `no_trade`, 32 `propose_entry`; **last row 2026-11-20 04:08Z** |
| priced proposals | 26 `replayed` outcomes (22 distinct symbol/side/day), every one net of the full cost stack per its `cost_policy` | mean **+0.47 R**, win 58%, ~80% lower bound **+0.16 R** (SD-based, n small, clustered same-day) |
| unpriced | 213 outcomes `not_computable` (every `no_trade`/`watch_note`) | no baseline, so no "did not trading help" read |
| routing | 32 proposals | 20 submitted, 12 route `none` |
| book | bybit_1 `claude_desk`, `SOAK-TOUCH-SPLIT.md` (generated 2026-11-23) | 9 closed trades, 0 touched; no backtest band |
| packets | `desk/decisions` branch | landing hourly through 2026-11-25 ~18Z (last one read DP-20261125T1803Z) |

Read with care: n=26 clustered replay is not the offline test. The registered Stage-0 tests say the opposite or nothing: DESK-18F judged-1 S3 +0.007 R (CI -0.22..+0.22, n=732, bar +0.25); DESK-18G E4 OI-shock +0.157 R (bar +0.25, `S3_NOT_CLEARED`); DESK-ENTRY-REVIEW-REDESIGN trigger replay, 4 of 4 families fail. 2026-10-27 to 11-20 proposals were ~all shorts on a falling tape, so the +0.47 is not evidence of edge.

**The headline gap: no desk wake has written a row for 5 days** (2026-11-20 -> 11-25), while packets land hourly and `desk_wake` is ON. **Cause established by the manager (MEASURED, ops-flags PR #17895 comments, relayed 2026-11-25 18:56Z; I did not re-read them):** desk-wake markers posted every 4 h (latest 2026-11-25 16:22Z, packet DP-20261125T1617Z-scan-1h) and no session was spawned for them, because the throttled manager handled real-money reviews only; spawning is a manager action by design (trading-desk SKILL § 6b). Not a VM fault. The manager resumed dispatching every desk-wake marker from the 20:00Z bar on 2026-11-25. The structural point stands: **a manager-dependent spawn is a single point of failure**, which `DESK-V1-SPAWN` addresses.

## 2. Ranked plan (expected effect on desk quality per effort)

| # | item | row (new = N) | effect | effort / tier | roadmap | due_by |
|---|---|---|---|---|---|---|
| 1 | **Make spawn independent of manager liveness** (scheduled task, fresh session; alert if a posted wake has no row in 15 min; the 5-day gap's cause is known, no receipt investigation needed) | `DESK-V1-SPAWN` (queued) + `DESK-V1-ALERTS` close | Without rows nothing else on this list produces data; the gap recurs whenever the manager is throttled. Highest. | ~1 d build; Tier 2 if touching VM spawn, else Tier 1 | L-DESK-V1 | 2026-11-30 |
| 2 | **Stop the known refusals before proposing**: check `system_book` opposite slice (G6, `opposite_slice_one_way_book` twice, 12 of 32 proposals route `none`) and the leg-symbol list in the packet | N `DESK-PROPOSE-PRECHECK` (fold into `DESK-FOLLOWUPS-1027`) | Turns wasted wakes into fills; 37% of proposals never routed | 0.5 d, Tier 1 (brief + packet field, no order path) | L-DESK-V1 | 2026-12-02 |
| 3 | **Price `no_trade`** (DESK-20 outcome joiner on the DESK-7 harness): 213 of 239 outcomes have no baseline, so selectivity (the desk's main product, 207 `no_trade`) is unmeasured | `DESK-20-OUTCOME-JOIN` (blocked: re-scope to the minimum, baseline bracket per packet) | Unblocks scorecard, student hand-off, DESK-22 | 1.5 d, Tier 1 (offline) | L-DESK | 2026-12-04 |
| 4 | **One desk line in the daily brief** (packets, rows, misses, proposals, routed, replayed R with n) | `DESK-V1-SCORECARD` (queued, Sonnet $4) | Makes silence like the 5-day gap visible the day it starts | 0.5 d, Tier 1 | L-DESK-V1 | 2026-12-02 |
| 5 | **Decide the event arm**: E4 +0.157 R vs bar +0.25. Retire, or register 5-min entry + 4-24 h horizon sweep, and clear the forward holdout (`DESK-EVENT-OI-FORWARD-CHECK`, data after 2026-09-30) | `DESK-18G-EVENT-ENTRIES` (due 11-06, overdue) | Only live path to positive offline edge so far; decision, not build | decision at planning; ~1 d research if registered | L-DESK | 2026-12-04 |
| 6 | **Entry-review redesign**: all 4 trigger families fail; stop spending wakes on label-only detectors, then rebuild the desk as an LTR-style entry reviewer if the operator keeps it | `DESK-ENTRY-REVIEW-REDESIGN` (due 11-25, unmapped -> map to L-DESK) | Cost saving first (4 h cadence already), design second | decision at planning | L-DESK | 2026-12-02 |
| 7 | **Live flow / windows plan** (open/close windows, 1-min cadence, measured step latencies) | `DESK-27-LIVE-FLOW` (queued) | Only after 1-4 give rows to measure; bar_close_to_decision median 175.5 s measured 10-29 | 2 d, Tier 1 plan | L-DESK | 2026-12-11 |
| 8 | **Retire or close stale rows**: `DESK-14-LIVE-WEB-CONTEXT` (due 11-03, 0 external_context rows read here: not checked), DESK-19..26 chain (blocked behind 3), `DESK-GATE-OFFLINE-PATH` | one sweep row N `DESK-ROW-SWEEP-W48` | Hygiene; stops 20+ landed_unproven rows reading as work | 0.5 d, Tier 1 | L-DESK | 2026-12-02 |

`DESK-MACRO-DAILY` belongs to the ML lane (spec PR #28840); not built here, not planned here. Parked: DESK-MAKER-FILLS (DESK-18F failed; cost lever moves desk and baseline equally), DESK-PROP-LIVE / DESK-17B / DESK-V1-CLASS-GATES (dropped).

## 3. Capacity estimate

Items 1-4 + 8 are ~4-5 working days of lane effort (Sonnet lanes, ~$4-5 each, ~$20-25 total), items 5-6 are decisions plus ~1 d research. Proposal for the reset: **one standing desk lane at ~1 day/week plus a $20/week ceiling** for four weeks, then re-judge on the first scorecard lines. Wake cost is separate: ~$0.30-0.62 per wake measured 10-26..10-30 (n=4, older).

## 4. Landed-unproven observations checked this lane

| row | check | result |
|---|---|---|
| `DESK-12-SANDBOX` | `docs/claude/work/SOAK-TOUCH-SPLIT.md` on main | first half met (file exists, generated 2026-11-23); second half NOT met: **0 touched / 1734** on bybit_1. Stays `landed_unproven`. |
| `DESK-14-LIVE-WEB-CONTEXT` | `content_sha256` count in decisions | not run here; open in item 8 |

Others not re-verified; no row closed by this lane.

## 5. Not verified

Whether the manager's account of the 5-day silence (PR #17895 comments) matches the receipts, which I did not read; whether the mirror (`decisions.jsonl` on main) lags the `desk/decisions` branch (branch tip also read 239 rows, last 2026-11-20, so it does not); any figure from before 2026-11-23 other than as dated.
