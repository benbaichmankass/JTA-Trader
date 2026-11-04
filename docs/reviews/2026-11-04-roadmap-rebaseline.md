# Roadmap re-baseline 2026-11-04 — 30 of 33 milestones are past their review date, three week-priority targets end today or have already passed, and nine entries carry a status, `where` or `no_rows_reason` that their own counts contradict

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-04` · lane `ROADMAP-REBASELINE` (monthly reset job `roadmap-rebaseline`, `config/reset_protocol.yaml`; dispatched by Manager Session 2026-11-04a under row RESET-JOBS-20261104) · tree `origin/main` @ `5da5ac35e` (2026-11-04 ~19:50Z)

## Gates this adds or changes

None. This is a **proposal**. `docs/roadmap/milestones.yaml` is **not edited**. Per manager SKILL § "The roadmap loop", the yaml changes only once the edits are agreed in Thursday planning (2026-11-05, part B2). Nothing here authorizes work.

## 0. How to read this

- **MEASURED** means a command was run in this session on the tree above, and the population is named.
- **Not re-measured** means no command run here could re-measure it. The reason is given each time.
- The headline report is `python3 scripts/ops/roadmap_map.py --report` on `origin/main` @ `5da5ac35e`. In that report:
  - "live rows" means `queued`, `in_flight`, `blocked` or `landed_unproven`.
  - "closed" means `done` only (`scripts/ops/roadmap_map.py:51-52,128-132`).
- Where this doc says **open rows**, it means `queued` + `in_flight` + `blocked` only. That is the subset someone still has to work.

**Report (MEASURED):** 33 milestones: active 21, dormant 5, backlog 1, closed 6 (21 + 5 + 1 + 6 = 33, counted from the yaml parse). Other report results:
- Orphan live rows: 0. Orphan open units: 0. Dangling refs: 0.
- **30 of 33 `reviewed` dates are flagged OVERDUE** against `review_cadence_days: 8`. The 3 that are not are L-AM-STANDARD, L-ML-LIVE and L-DESK-V1, all reviewed 2026-10-28. Check: `grep -c OVERDUE` = 30, and table rows without the flag = 3.
- The file-level `reviewed:` field reads `2026-10-22`, which is 13 days old.

## 1. Goal baselines — re-measured with their own commands

| goal | baseline as written (date) | re-measured 2026-11-04 | state |
|---|---|---|---|
| G1 | "To be measured by the 2026-10-15 perf-review prep". It also cites the TP doctrine as "0 of 50 routings compliant" (2026-10-14). | **TP doctrine** (`python3 scripts/ci/check_tp_doctrine.py`, population 75 routings / 54 distinct legs across every account in `config/accounts.yaml`): compliant = real_money 1/7, prop 0/3, mirror 1/7, paper 1/58. That is **3 of 75 overall**. TP-REACH-FLOOR covers 47 declared-target routings: 7 below floor, 6 reachable, 34 unmeasured. Baselined debt is 72. **Roster** (`config/accounts.yaml`, `len(strategies)`): bybit_2 6, bybit_portfolio 6, alpaca_live 1, alpaca_portfolio 1. **Net P&L per capital-day: not re-measured.** It needs the live journal through the diag relay, which this lane did not pull. The baseline text is stale: the measure was taken in `docs/reviews/2026-10-15-weekly-walkthrough-perf.md` § 2, but the yaml never recorded it. This week's figure belongs to perf review PR #22930 (open). | TP + roster MEASURED; P&L **not re-measured** |
| G2 | "3 prop accounts live with 2 legs each" (2026-10-11) | `config/accounts.yaml`: breakout_2, tradeify_1 and velotrade_1 are `mode: live` with **1 leg each**. breakout_1 is `dry_run` with 0 legs. Prop positions are partly unreadable: tradeify_1 and velotrade_1 status carries no `positions` field. Root cause is at `src/prop/prop_executor.py:1259-1263` (PR #22905 F5, merged; row `AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE`, due 11-07). | MEASURED (config); the visibility gap is quoted from #22905, **not re-measured** |
| G3 | "FIX-CA-01..32 ... most at landed_unproven" | Checklist rows with id prefix `FIX-CA-` / `FIX-SA-`: **10 total = 3 done, 7 landed_unproven**. The 32 FIX-CA findings were folded into area rows (FIX-CA-EXEC/-OM/-RISK/…), so "01..32" no longer names rows. Positive control: the same `ls | grep` finds FIX-CA-01, -01b and -01c. Also new since 10-28: 3 money-path defects from the deep audit. TLT over-cover, MGC journal 14 vs venue 11, and 2 mislabelled flatten closes (PR #22902), all filed under **L-OPS**, not G3 (see § 4). | MEASURED |
| G4 | "regime weight 5, 0 queued regime units; ml_health 1 queued" (2026-10-11) | `research/THEMES.yaml` gives regime weight 5, new_strategy_prop 6, live_strategy 4, ml_health 3, infra 2, macro 1, timeframes 1. Units by theme (research/queue/**/*.yaml, 1,932 units): regime **7 queued + 13 blocked**, ml_health 21 queued + 35 blocked, live_strategy 129 + 39, new_strategy_prop 35 + 9. **The weight-vs-work gap persists**: the theme with the second-highest weight has the second-fewest queued units (7, above only timeframes 0 and macro 6). | MEASURED |
| G5 | 475 units; 415 rows; 15 mandates (2026-10-11) | Queue: **1,932 units = 1,539 done, 215 queued, 120 blocked (dir), 58 retired** (1,539 + 215 + 120 + 58 = 1,932 ✓). Checklist: **1,294 rows = 515 done, 288 landed_unproven, 279 queued, 45 in_flight, 24 blocked, 143 dropped** (sum 1,294 ✓). `config/mandates.yaml`: **21 granted, 1 proposed**. The deep audit (PR #22902) adds that 549 of 617 open rows carry no `due_by`, and that the pipeline has 577 due and 166 unrouted. Both are quoted, **not re-measured** here. | MEASURED (counts) |
| G6 | alpaca_options_paper 3 legs (2026-10-11) | `config/accounts.yaml`: alpaca_options_paper `live`, **3 legs** (unchanged). | MEASURED |
| G7 | SPA on Pages; Workflow page serves checklist + brief | **Not re-measured.** There is no command for it. PR #22905 F7 and F10 (merged) found two problems: the work-queue card is stale because the register is stale (33/38 in_flight rows untouched > 48 h), and `/work/brief` is 60.9 s cold. | not re-measured (quoted) |

## 2. Milestone by milestone

Open-row age comes from the row's `updated_at` (open = queued / in_flight / blocked; refs resolve through the explicit `roadmap` field first, then `docs/roadmap/backfill-2026-10-11.json`). The columns are open rows, then rows aged 7–14 d, then rows aged > 14 d.

| milestone | status / reviewed | report live·closed·units | open (7–14d / >14d) | finding |
|---|---|---|---|---|
| L-AM-STANDARD | active, target **2026-11-04 (today)** | 28·6·12 | 18 (0/0) | **`no_rows_reason` is stale**: it says rows "are filed at the 06:17Z planning session", and 28 live rows now exist. Done-condition check, MEASURED over `comms/live_review/reviews.jsonl` since 2026-10-28 (292 records): reviews exist for bybit_2 (35), bybit_portfolio (34) and alpaca_portfolio (10). **alpaca_live has 0 records.** I did not establish whether alpaca_live held any open package in the window, so this is a gap with no denominator, not proof of a miss. `applied` is True on **0 of 292**. Actions: hold 205, flag_mechanics 41, close 22, no_recommendation 12, tighten_sl 11, partial_close 1. Target reached with the done-condition **not shown met** → needs a disposition. |
| L-ATM | active, 10-14 | 96·38·41 | 47 (12/1) | `where` quotes "0 of 50 routings compliant" (10-14). Re-measured: 3 of 75. Rewrite `where`. |
| L-LADDER | active, 10-22 | 74·56·32 | 25 (2/3) | `where` not re-measured (no single command; the ladder state is `strategy_status.py`, not run here). |
| M20 | **closed** (merged into L-ATM) | 7·2·**46** | 2 (0/1) | A closed milestone holds 46 open units and 2 open rows. The 10-14 merge note says they are "read as L-ATM's history", but the report still counts them under M20. Proposal: re-point the 2 open rows to L-ATM, and add a `queue_rules` mapping M20 → L-ATM for units. |
| M21 | **dormant**, 10-16 | 5·2·2 | 2 (0/1) | Dormant, yet holds open work. Dormant sweep: this is its 2nd pass without a fresh reason → close it and re-point its rows (§ 3). |
| M22 | active, 10-17 | 7·2·5 | 5 (1/3) | 3 of 5 open rows untouched > 14 d. |
| M27 | active, 10-16 | 2·2·0 | 0 (0/0) | **Active with 0 open rows and 0 open units**. Its 2 "live" rows are landed_unproven. Either name the observation that closes them or go dormant. |
| M18 | active, 10-22 | 6·2·2 | 2 (0/0) | PR #22892 proposes pointing M18's `where` at L-ML-AGGREGATOR. Agreed (§ 3). |
| M16 | **dormant**, 10-22 | 1·0·1 | 1 (0/1) | The unified confidence-risk question is the aggregator question in another form. Propose folding it into L-ML-AGGREGATOR and closing it. |
| M24 / M15 | closed 10-22 | 0·0·0 | — | Fine. |
| L-TIMEFRAMES | active, 10-18 | 3·2·2 | 3 (0/**3**) | All 3 open rows are untouched > 14 d. Active in name only; this week's PR #22907 (Tier-3 results read, timeframe) is the live evidence. Rewrite `where` from that once it lands. |
| L-PROP | active, 10-22 | 41·43·35 | 23 (2/**18**) | **18 of 23 open rows untouched > 14 d**, the largest stale share. The G2 baseline is wrong (1 leg, not 2), and prop positions are partly unreadable (#22905 F5). |
| M39 | active, 10-22 | 33·13·0 | 7 (3/2) | The deep audit's money-path defects belong here (§ 4). |
| M31 | closed (merged into L-ATM) | 0·1·1 | 0 | 1 open unit on a closed milestone → re-point it to L-ATM. |
| L-ML-LIVE | active, target **2026-11-01 (passed)** | 49·5·40 | 42 (0/0) | **`no_rows_reason` is stale** (49 live rows). The target passed 3 days ago and no `where` records the outcome. New rows ML-UNIVERSE-RULE (rank 2, in_flight, PR #22928 Tier-3 HOLD) and ML-ROADMAP-MECE (rank 1, PR #22892 draft HOLD) both ref it. |
| L-DESK-V1 | active, target **2026-11-04 (today)** | 1·1·0 | 1 (0/0) | A week priority carried by 1 live row. `no_rows_reason` is stale. Needs a disposition at the target. |
| L-REGIME | active, 10-16 | 8·2·13 | 5 (2/2) | Regime theme weight 5 vs 7 queued units (§ 1, G4). This is still the finding. |
| M25 | active, 10-22 | 51·31·12 | 32 (7/**11**) | 11 open rows untouched > 14 d. L-ML-MECE (proposed) overlaps its "consolidation" scope (§ 3). |
| M26 | closed 10-22 | 0·0·0 | — | Fine. |
| M23 | active, 10-14 | 9·3·4 | 0 open | Its live rows are all landed_unproven. Each needs the observation that closes it. |
| M14 | **dormant**, 10-22 | 5·1·0 | 2 (0/1) | Dormant with 2 open rows. Its validation discipline is the MECE per-slot harness spec → fold into L-ML-MECE and close. |
| M9 | **dormant**, 10-22 | 0·0·0 | — | Dormant across ≥ 2 passes with no work → **close** (dormant sweep). |
| L-DATA | active, 10-14 | 12·3·1 | 10 (0/3) | Not re-measured. |
| M41 | backlog, 10-22 | 0·0·0 | — | Fine (has a reason). |
| L-DESK | active, 10-26 | 76·18·15 | 37 (3/0) | Not re-measured; PRs #22909 and #22924 (desk mirrors) merged today. |
| L-PROGRAMMES | active, 10-14 | 21·13·22 | 8 (0/0) | Not re-measured; the programme review (Wed 19:29Z) owns the `where`. |
| M40 | active, 10-22 | 12·13·0 | 5 (2/2) | Research SLO red (`AUD-20261019-RESEARCH-SLO-RED`, stalled across 2 audits; #22902). |
| L-OPS | active, 10-22 | **123**·50·16 | 76 (2/3) | The catch-all. All 11 new deep-audit rows plus SYSTEM-AUDIT-INTEGRATION, REGISTER-CONSOLIDATION and the alert/latency rows land here. See § 4. |
| M28 | active, 10-14 | 8·8·7 | 5 (2/1) | Not re-measured. |
| M29 | **dormant**, 10-14 | 1·1·0 | 0 open | Its 1 live row is landed_unproven. Name the observation, then keep it dormant with a fresh reason. |
| M36 | closed 10-22 | 0·0·0 | — | Fine. |
| M6 | active, 10-15 | 9·4·0 | 1 (1/0) | The SPA's staleness and latency findings (#22905 F7/F10) belong here as well as under L-OPS. |

**Architecture check** (each `architecture:` ref vs `docs/ARCHITECTURE-CANONICAL.md` headings): the guard `roadmap-map-guard` enforces the headings and passed on main at the report run (0 dangling refs). Two contract changes landed or are pending this week with no `arch` write-back named yet:
- "an account configures strategies, never symbols" (PR #22914, open; ML-UNIVERSE-RULE). It touches the roster/gate contract → `docs/ARCHITECTURE-CANONICAL.md` § "The two execution gates" is the section to check when it lands.
- The prop executor status contract (`positions` absent; #22905 F5) → "Prop ticket flow".

## 3. Proposed `docs/roadmap/milestones.yaml` diff (NOT applied)

Agree, amend or reject each item in Thursday planning. Items marked † reword another lane's entry, so the owning lane (or planning) applies them.

```diff
 version: 1
-reviewed: 2026-10-22
+reviewed: 2026-11-05          # set when planning applies this pass (2026-11-04 re-baseline: docs/reviews/2026-11-04-roadmap-rebaseline.md)

 goals:
   G1:
     baseline: >-
-      To be measured by the 2026-10-15 perf-review prep (...)  TP doctrine (...2026-10-14 06:40Z): 0 of 50 routings compliant.
+      Net P&L per capital-day: first measured 2026-10-15 (docs/reviews/2026-10-15-weekly-walkthrough-perf.md § 2); the
+      current figure is the weekly perf review's (2026-11-04: PR #22930) -- re-read, never quoted. TP doctrine
+      (check_tp_doctrine.py, 2026-11-04): 3 of 75 routings compliant (real_money 1/7, prop 0/3, mirror 1/7, paper 1/58).
+      Roster 2026-11-04: bybit_2 6 legs, bybit_portfolio 6, alpaca_live 1, alpaca_portfolio 1 (re-parse; never quote).
   G2:
     baseline: >-
-      3 prop accounts live with 2 legs each (config/accounts.yaml, 2026-10-11). (...)
+      2026-11-04: breakout_2, tradeify_1, velotrade_1 live with 1 leg each; breakout_1 dry_run, 0 legs (config/accounts.yaml).
+      tradeify_1/velotrade_1 positions unreadable in executor status (src/prop/prop_executor.py:1259-1263; PR #22905 F5).
   G3:
     baseline: >-
-      The 2026-09-27 code audit produced FIX-CA-01..32 (...)
+      2026-11-04: FIX-CA-*/FIX-SA-* area rows 10 = 3 done, 7 landed_unproven (the 32 findings were folded into area rows).
+      Open money-path defects from the 2026-11-04 deep audit (PR #22902): IB TLT over-cover, MGC journal-vs-venue qty,
+      2 flatten closes labelled reconciler_filled.
   G4:
     baseline: >-
-      (...) on 2026-10-11 the queue holds 0 queued units under theme regime and 1 under ml_health (...)
+      2026-11-04 (research/queue, 1,932 units): regime (weight 5) 7 queued + 13 blocked; ml_health (weight 3) 21 + 35;
+      live_strategy (4) 129 + 39; new_strategy_prop (6) 35 + 9. The regime weight still does not reach work.
   G5:
     baseline: >-
-      research/queue 2026-10-11: 475 units (...) 15 mandates granted (config/mandates.yaml).
+      2026-11-04: queue 1,932 = 1,539 done, 215 queued, 120 blocked, 58 retired. Checklist 1,294 = 515 done,
+      288 landed_unproven, 279 queued, 45 in_flight, 24 blocked, 143 dropped. Mandates 21 granted, 1 proposed.

 milestones:
   - id: L-AM-STANDARD
-    no_rows_reason: >- (rows filed at the 06:17Z planning session ...)
+    # no_rows_reason removed: 28 live rows exist (roadmap_map --report 2026-11-04)
+    # where/status: DISPOSITION AT TARGET (planning decides): extend target with the gap named
+    #   (alpaca_live: 0 live-review records since 10-28, denominator unread; applied = 0 of 292), or close as met.
   - id: L-ATM
     where: >-
-      (...) python3 scripts/ci/check_tp_doctrine.py reports 0 of 50 routings compliant (...)
+      (...) 2026-11-04: 3 of 75 routings compliant (real_money 1/7); TP-REACH-FLOOR 7 below / 6 reachable / 34 unmeasured.
   - id: M20            # closed
+    # route its open work to L-ATM: re-point 2 open rows; add queue_rules entry M20 -> L-ATM for its 46 open units
   - id: M31            # closed
+    # re-point 1 open unit to L-ATM
   - id: M21
-    status: dormant
+    status: closed     # dormant sweep: 2nd pass with no fresh reason; re-point its 2 open rows to L-ATM (entry exits) or close them
   - id: M27            # †
+    # 0 open rows / 0 open units: name the observation closing its 2 landed_unproven rows, or go dormant with a reason
   - id: M18            # † (proposed by PR #22892 § 7)
+    where: "... the next M18 question is the position aggregator: see L-ML-AGGREGATOR."
   - id: M16
-    status: dormant
+    status: closed     # folded into L-ML-AGGREGATOR (unified confidence -> one net position); re-point its 1 row + 1 unit
   - id: L-ML-LIVE
-    no_rows_reason: >- (...)
+    # no_rows_reason removed: 49 live rows
+    # where: record the 2026-11-01 target outcome (planning); add ML-UNIVERSE-RULE (PR #22928, Tier-3 HOLD on #22900)
   - id: L-DESK-V1
-    no_rows_reason: >- (...)
+    # no_rows_reason removed: 1 live row. DISPOSITION AT TARGET 2026-11-04 (planning): met / extend / fold into L-DESK
   - id: M14
-    status: dormant
+    status: closed     # folded into L-ML-MECE (validation discipline = the per-slot harness spec); re-point its 2 open rows
   - id: M9
-    status: dormant
+    status: closed     # dormant sweep: >= 2 passes, 0 rows, 0 units
+  # NEW (from PR #22892 § 7, with two corrections: status must be one of active|dormant|backlog|closed -- the
+  # proposed `status: proposed` is not in roadmap_map.py STATUSES and would fail roadmap-map-guard; and with no
+  # rows/units yet each needs a no_rows_reason)
+  - id: L-ML-MECE
+    goal: G4
+    status: active
+    no_rows_reason: "rows ML-SERVING-INVENTORY / ML-SLOT-REPORT / WHIPPET-FILL-REPLAY and units RQ-20261105-mece-* are filed in Thursday planning 2026-11-05 (PR #22892 § 9)"
+    # name/where/next/owner exactly as PR #22892 § 7
+  - id: L-ML-AGGREGATOR
+    goal: G4
+    status: backlog    # research-before-build; becomes active when RQ-20261105-mece-01 (VOI census) is filed
+    no_rows_reason: "VOI census unit RQ-20261105-mece-01 filed in Thursday planning; build rows only if concurrent episodes are material"
+  # NEW (G3): the integration/alerting gap is plumbing, not ops process
+  - id: L-ALERT-INTEGRATION
+    goal: G3
+    name: Every alert and venue state reaches Claude without the operator relaying it
+    status: active
+    where: >-
+      2026-11-04 (PR #22905): 0 of 30 VM operator alerts reached /work/report or /work/brief (F1); 37 of 82 Telegram
+      senders have no durable sink (F2); prop executor status omits positions (F5); trader tick 115 s mean (F8);
+      21 restarts 00:00-18:18Z (F9). Design pending (SYSTEM-AUDIT-INTEGRATION, after DEEP-AUDIT-20261104).
+    next: rows ALERT-LEDGER-TO-MANAGER, TICK-DURATION-115S, AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE re-pointed here from L-OPS
+    architecture: ["Prop ticket flow"]
+    owner: manager
+    reviewed: 2026-11-04
   - id: L-OPS
+    where: "... 2026-11-04: REGISTER-CONSOLIDATION (operator 'One register', design-only, blocked until approved) is the
+      lever for the 549/617 undated open rows and the 577-due/166-unrouted pipeline (PR #22902)."
```

**Rows to re-point** (a `roadmap` field edit through `scripts/ops/checklist.py set`, done in the same planning PR):
- To M39 (G3): `AUD-20261104-IB-TLT-DOUBLE-PROTECT`, `AUD-20261028-MGC-JOURNAL-QTY` and `AUD-20261104-FLATTEN-LABEL` are live-money integrity defects filed under L-OPS (#22902).
- To L-ALERT-INTEGRATION (if agreed): `ALERT-LEDGER-TO-MANAGER`, `TICK-DURATION-115S`, `AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE`, `SYSTEM-AUDIT-INTEGRATION`.
- L-OPS drops from 123 live rows only by these moves. The rest are process rows and stay.

## 4. Findings for planning (not decisions)

1. **The weekly pass has not run for 13 days.** File-level `reviewed: 2026-10-22`; 30 of 33 milestones are overdue. The 10-28 planning set three week priorities without a full pass. This re-baseline stands in for it. Planning applies § 3 and sets `reviewed`.
2. **Week-priority targets have lapsed without an outcome recorded.** L-ML-LIVE (2026-11-01, passed); L-AM-STANDARD and L-DESK-V1 (2026-11-04, today). All three still carry a `no_rows_reason` that their row counts contradict.
3. **G3 money-path defects are filed under G5's L-OPS.** The roadmap then reads them as process work, and the "live-money defect under G3 first" prioritisation rule cannot see them.
4. **Stale open work**: L-PROP has 18 of 23 open rows > 14 d, M25 has 11 of 32, L-TIMEFRAMES 3 of 3. Combined with #22902 (549 of 617 open rows undated), "active" does not mean "being worked". REGISTER-CONSOLIDATION is the lever. This doc does not propose a second one.
5. **Theme weights vs work**: regime (weight 5) has 7 queued units; live_strategy (weight 4) has 129. The gap from 10-11 persists. Planning should set unit authoring for L-REGIME or lower the weight.
6. **PR #22892's yaml proposal would fail the guard as written** (`status: proposed`; no `no_rows_reason`). Corrected in § 3.

## 5. Method and what was not done

- Commands run (all on `origin/main` @ `5da5ac35e`):
  - `roadmap_map.py --report`
  - `check_tp_doctrine.py`
  - Python parses of: `config/accounts.yaml`, `docs/claude/work/checklist/*.json` (state, `updated_at`, `roadmap` + backfill), `research/queue/**/*.yaml` (status, theme), `research/THEMES.yaml`, `config/mandates.yaml`, `comms/live_review/reviews.jsonl` (records with `reviewed_at ≥ 2026-10-28`)
- Inputs read: PR #22892 (draft, hold), #22902 (merged), #22905 (merged), #22916 (open; rows ML-UNIVERSE-RULE and REGISTER-CONSOLIDATION read from its head), #22928 (open).
- **Not re-measured:**
  - G1 net P&L per capital-day (live journal; perf review #22930 owns it)
  - G7 surface latency
  - every `where` on L-LADDER, L-DATA, L-DESK, L-PROGRAMMES, M28, M22 and M40 (no single command; owning reviews this week)
  - whether alpaca_live had any open package since 10-28
- No checklist row, queue unit or yaml entry was changed by this lane.
