# Planning input — week of 2026-11-26 (open items at the 11-25 reset)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · written 2026-11-25 ~17:55Z by Manager Session 2026-11-22a for Thursday planning.
> It points at the source of truth: the work store, `pipeline.py` and `docs/roadmap/milestones.yaml`. **Re-read those; never quote counts from here.**

Gates this adds or changes: none.

All numbers below were MEASURED at about 17:50Z on 11-25 from:

| Source | How it was read |
|---|---|
| Work store | `work.py list` |
| Pipeline | `pipeline.py --stats` and `pipeline.py --due --all` |
| Roadmap | `milestones.yaml` |
| Open PRs | GitHub API |
| Soak report | `SOAK-REPORT.md`, generated 11-15, so 10 days stale |

---

## 0. The headline: the backlog itself is the first planning item

| Register | Measured | What it means |
|---|---|---|
| Checklist builds: `queued` | 522 | **440 have a due date on or before today**, so due dates are mostly stale and no longer rank anything |
| Checklist builds: `landed_unproven` | 377 | 370 past due; each needs a named observation to close it |
| Checklist builds: `in_flight` | 25 | About half are owned by sessions that no longer exist (AM-OPS, AM-OPS-8/10, ML-PRIMARY-8/14/15, PITCH-DECK-V2, PROGRAMME-REPLAN); row WORK-INFLIGHT-STALE-OWNERS already names this |
| Checklist builds: `blocked` | 26 | 7 are the DESK-20..26 "later phase" rows |
| Work-store observations, queued | 652 | — |
| Pipeline items: open | 978 | 246 queued + 732 routed |
| Pipeline items: due now | **869** | — |
| Pipeline: routing alarm | **142 unrouted** | oldest 21 days (PI-20261104-PREP1104-0003) |
| Soak items in the pipeline | 51 | **The soak step was retired on 11-12** (operator: "Absolutely no steps"; `MD-PROMOTE-S1-S2 soak_step: retired`), yet `PI-SOAK-*` items still track 1-2-trade soaks. Five read "ready", one "dead" (vwap). These should be closed per the 11-12 rule, not worked. |

**Proposal for Thursday:** one BACKLOG-TRIAGE-W48 lane (Sonnet). Every rule below has an operator precedent, so this adds no gate.
1. **Close obsolete items.** That means the soak items (retired step), rows owned by archived sessions with no next action, and handover rows for past sessions (ML-PRIMARY-15-HANDOVER, ML-WEEK-PLAN-1119).
2. **Re-date or drop every stale due date.** Use the precedent BACKLOG-RESET-20261029 (bulk kill with a terminal_reason).
3. **Route the 142 unrouted pipeline items.**
4. **Re-owner the live `in_flight` rows.**

---

## 1. Roadmap: the "week priorities" are two weeks past target

`milestones.yaml` still carries three **WEEK PRIORITY** milestones, all with target **2026-11-11**:

| Milestone | Done-condition | State |
|---|---|---|
| **L-ML-LIVE** (P1) | A handful of ML models change a live decision in a trading loop, each on its own evidence record | ml_entry is live on real money; most other heads are INDETERMINATE/FAIL this week (below) |
| **L-DESK-V1** (P2) | Desk V1 runs in production without operator relay: wakes, records, grading, apply path observed end to end | Wakes run, but the desk was throttled to real-money reviews; DESK-14/18G are landed_unproven; DESK-19..26 are blocked "later phase" |
| **L-AM-STANDARD** (P3) | Every real-money leg runs active management in production | AM v2: Stage B all FAIL; iterations 3-4 running (below) |

**Decision for Thursday:** re-target, re-scope or close each of the three, and re-state this week's 1-3 priorities. The operator has signalled these:
- **Desk capacity plus DESK-MACRO-DAILY**, new 11-25.
- **Regime as a standing lever**, 11-25 (REGIME-PROGRAM).
- **The ETF leg to real money**, 11-25.

Other active milestones and their stated next steps (from `milestones.yaml`):

| Milestone | Next step |
|---|---|
| L-REGIME | Sizing forms closed on evidence. Next: state-conditioned entry per family (REGIME-PROGRAM, in_flight, ML-PRIMARY) |
| L-TIMEFRAMES | Shorter-timeframe capitulation answered: **FAIL at 1h/4h** (1e07-01..04), so the edge exists only on daily bars. Long-arm units remain |
| M28 macro sleeve | Grade the PPI set (4a4c), MACRO-BACKFILL-E5. **Re-opened through DESK-MACRO-DAILY** (teacher for the sleeve) |
| L-PROP | Programme 05 baselines and challengers; prop drills blocked (CAP-PROP-LIVE-DRILL, PHONE-*) |
| L-DESK | DESK-18 entry-generation replay; DESK-17 claude_desk leg |
| L-ML-MECE | D-slot gap: only D1 and D4 had a next unit at 11-24. **An ML-PLAN lane is due at the reset** (reset trigger) |
| M18 / M22 / M23 / M25 / M27 / M39 / M40 / L-DATA / L-ALERT-INTEGRATION / L-OPS / M6 | Active; queued rows below |
| M41, L-ML-AGGREGATOR | Backlog |
| M29 | Dormant |

---

## 2. Real money: what is live, what is about to change

- **INDEX-CAPIT-1X-LEG → alpaca_live at full size.** The operator decided this 11-25 06:28Z and reconfirmed 14:22Z after seeing the 1e06-12/13/14 out-of-time FAILs. The wiring lane starts at 18:20Z.
  - **Before its first live order:** diagnose the Alpaca stop and re-arm faults (ALPACA-PAPER-BRACKETS-GONE-1116). Today's evidence:
    - 14:34Z: USO was unprotected and the re-arm was refused.
    - 15:00Z: a QQQ trailing-stop change was accepted but never applied.
    - 17:08Z: an SLV mirror close never reached the journal.
  - **Ask the operator:** confirm they want the first live order to wait on that diagnosis.
  - Related rows: FRACTIONAL-ETF-EXECUTION (p2), SHARED-BRACKET-FIX (p2).
- **ml_entry (real money):** no demotion trigger (operator 11-24); judged in the weekly performance review. It lost 5/5 real-money trades on 11-24, so flag that there. bybit_2 lost on 4 straight days (11-21..24, $20.68, broker-measured).
- **#28624 (mirror sibling-leg re-sync):** deployed, not yet observed. PI-20261124-RORTRAIL-0001 is due 11-27. Today's SLV ghost-open counts as evidence against it.
- **Landed-unproven real-money rows at priority 1:**
  - WATCHDOG-CLOSE-RECURRENCE (closes end stuck_strategy_watchdog)
  - ALPACA-LIVE-MECHANICS
  - REAL-TP-COMPRESSED-ETH4H
  - ML-REAL-MONEY-OVERLAY
  - COST-BROKER-SOURCED (p2: 485 of 488 real rows have estimated costs)
- **Promotion candidates per the soak report (11-15, stale):** ief_pullback_1d, tlt_pullback_1d, tqqq_trend_long_1d, trend_donchian_eth_4h, trend_donchian_eth_prop, xrp_pullback_2h. Under the 11-12 rule, a Stage-0 pass goes straight to real money. Check each one's Stage-0 evidence record rather than its soak status (rows PROMO-EVIDENCE-REFRESH and PROMOTION-NO-SOAK).

---

## 3. Research and ML: where every stream stands (11-25 results)

| Stream | Latest | Next registered step |
|---|---|---|
| **AM v2 (trade management)** | Stage B all FAIL. c7e3-05 PASS **invalid** (random control saw the exit time); c7e3-06 causal fixed-age FAIL | **c7e3-08 at 19:00Z is decisive** (causal random tighten); c7e3-07 at 18:00Z; c7e3-09 at 21:00Z. If c7e3-08 fails, close the tighten lever and move to another action family or label. **Every earlier AM random control has the same leak**, so re-read old "random beats model" claims |
| **ml_entry** | f1a0-33 classification target INDETERMINATE (-0.0115 R, t -1.22); f1a0-10 best so far (+0.0087); oi_feats holdout read **deferred** (power about 0.1, read #28) | 4h/8h horizon target |
| **Regime** | R3 tilt was book quality, not regime; rostered and 3rd-population confirmations FAIL; intraday null | State-conditioned entry per strategy family |
| **INDEX-CAPIT** | Daily edge in 2010-26, concentrated; FAILS 2000-10 on every population; 1h/4h FAIL | A form that holds up across regimes and passes both windows (lane iterating) |
| **Desk** | DESK-14 (web context) and DESK-18G (event entries) landed_unproven; 18D judge-2 queued p2 | **DESK-MACRO-DAILY** (new, ML-PRIMARY after the reset): daily macro/event brief, so trades plus a teacher for the macro sleeve and the news model |
| **News** | NEWS-ALPHA-PROGRAM queued | Fed by DESK-MACRO-DAILY labels |
| **Frontier** | FRONTIER-Q-* entry-model questions queued (xsec rank, ridge/ensemble, conformal, residual target) | Rank against the ML-PLAN two-week plan |
| **Programmes** | 8 plans in `research/programmes/`: ATM, AI-trader, strategy-improvement, macro, prop, data-infra, timeframes, alpaca-live-book | Weekly programme review (Wed 19:29Z) |

Queue runway: about 18:30Z today without a refill. The research-ops pass is re-dispatched at 18:15Z (trig_018Ungk2PaQAwuZqwwm9fF7t), then QUEUE-FILL starts at the reset.

---

## 4. Ops, infrastructure and hygiene: filed and open

**Fix this week (each is a row):**
- **DISPATCH-DOUBLE-FIRE-1125**: dispatcher runs take about 37 min and start every about 15, so about 3 overlap. Units double-fire (c7e3-01..06 and a9d2-02 so far). Fix with a concurrency group or claim-before-dispatch.
- **IB-MGC-INACTIVE-1125**: the ib_paper MGC sell of 27 is rejected about every minute.
- **ALPACA-PAPER-BRACKETS-GONE-1116**: Alpaca stop and re-arm faults (above).
- **Stale latch cleanup** (PI-20261125-0261122A-0001): Tier 2, needs an operator OK.
- **AUTOMATION-DATACOMMIT-CONFLICT**: automation data PRs strand on conflict. 8 stale automation PRs are open: #26451, #27042, #27391, #27631, #26833, #27333, #27926, #28216.
- **LIVE-VM-CPU-SATURATION-1112**: the live VM runs at CPU p95 of about 99.7%.
- **CBOE-OPTIONS-SOURCE-BLOCKED**: due 11-26.
- **Security / public-repo hygiene:** SEC-GITLEAKS-BASELINE-1116, BALANCE-TIP-SCRUB-2, DIAG-RELAY-EQUITY-LEAK, CF-GRADES-EQUITY-COMMITTED, CRED-ARGV-RESIDUE, and the **history purge** (18:30Z reminder; needs the operator's branch-protection toggle plus ONE final confirmation).

**Long-open draft PRs to decide on (keep, land or close):**
- #27086 mandate_resolver S1->S2: now moot? The soak step is retired.
- #26858: a stale reset claim from 11-18.
- #26648: pitch deck v2.
- #26310: shared order_key.
- #25283: balance purge runbook.
- #25231: SPA backend routes.
- #25174: WORK-GAP-ALERTS.
- #24917: M18 re-evaluation.
- #27809: research_loss_detector.
- #27093: audit Draft 2.
- #26860: operator-asks audit.

**UI (M6):** 12 queued and 19 landed_unproven UI-* rows. The priority ones are PROP-UI-BRACKETS-CLOSED (p1), UI-CHART-BRACKET-HISTORY (p2), the UI-WQ-SPA-* work pages and PERF-PAGE-PNL-CHART.

---

## 5. Waiting on the operator

1. **Re-state this week's priorities** and decide on the three overdue WEEK-PRIORITY milestones (§1).
2. **Confirm or override** that the ETF leg's first live order waits for the Alpaca stop-fault diagnosis (§2).
3. **The history purge:** the branch-protection toggle, then one final confirmation (18:30Z).
4. **Stale latch cleanup** (Tier 2 OK).
5. **Still owed:** delete the Actions logs of run 45250700088 and branch `lane/index-leveraged-etf-roster-20261123-lintfix`; the account top-up.
6. **Open since 11-23:**
   - the promotion-rule fix (a grade-window-only number must not promote), then re-grade ml_entry under it
   - the split CF-fidelity rule
   - running the Tradeify sim
7. **Daily email digest routine:** which inbox, and should it keep running while the operator is active? Its prompt still says "away until 11-22".
8. **Backlog triage (§0):** **approved** at the 18:00Z popup and executed; the output is §7; approve the bulk-close rules (obsolete soak items, archived-owner rows, stale due dates).
9. **MGC row 4773 (Tier 3):** does the estimated-P&L ib_paper MGC row 4773 (+$249k, an ESTIMATE, not a venue-measured number; relayed by the manager from the weekly audit, not re-measured by this lane) stay in the paper corpus that feeds the scoreboard and Stage-0 evidence? Options: keep it labelled `ESTIMATED` and out of any promotion or demotion read, or exclude it from the corpus. Recommendation: exclude it from every promotion/demotion read and keep it visible with its provenance label, because one estimated row of that size dominates a paper book.
10. **Scoreboard headline:** adopt `net_usd_measured` (venue-measured net P&L) as the scoreboard headline instead of the blended figure. Recommendation: yes, with the estimated and unmeasured parts shown beside it as separate, labelled lines (provenance rule: ESTIMATED is never folded into MEASURED).

---

## 6. Scheduled at the reset (already armed)

| Time (Z) | What |
|---|---|
| 18:05 | Weekly reset protocol (trig_017hfiDAKjiZwSQncMTm4169). It now includes **desk capacity** and DESK-MACRO-DAILY |
| 18:10 | Manager rotation. The handover note is on branch `manager/handoff-2026-11-25` |
| 18:15 | Research-ops pass re-dispatch |
| 18:20 | INDEX-CAPIT-1X-LEG wiring lane |
| 18:30 | History purge |
| 20:30 | Fable R&D toolbox audit |
| Thu 06:17 | Planning |

---

## 7. Backlog triage output (lane BACKLOG-TRIAGE-W48, 2026-11-25 ~18:30-19:20Z)

Authority: operator popup 2026-11-25 ~18:00Z "Approve all" (rules a-d) plus manager scope additions. Every write went through `checklist.py` / `pipeline.py` (the work store). **Per-item receipts with old and new values are in `comms/ops/backlog_triage_w48_receipts.jsonl`** (one line per action). Counts below were re-measured from the store after the writes, not quoted from the lane row.

MEASURED after the triage (work store re-read 2026-11-25 19:01Z): open checklist builds 973 = blocked 26, in_flight 26, landed_unproven 367, queued 554; rows with a due_by before 2026-11-25: 25; rows with no due date: 0.

### 7.1 What was closed, by rule (skim this)

| Rule | What | n | Data recorded on each item |
|---|---|---|---|
| (a) soak step retired | `PI-SOAK-*` pipeline items **killed** (45 accruing, 5 ready, 1 dead = vwap `enabled: false`) | 51 | `terminal_reason`: `MD-PROMOTE-S1-S2 soak_step: retired` (config/mandates.yaml), that leg's soak_report grade, and for the 5 ready legs the Stage-0 record numbers |
| (b) finished owner, no next action | rows **dropped** (merged, never observed, no observation/next_action): `RESEARCH-OPS-20261122-0847`, `RESEARCH-OPS-20261117-1006`, `RESEARCH-OPS-20261116-0715`, `RESEARCH-OPS-20261111-2049`, `LTR-GRADE-ALWAYS-ON`, `UI-LIVE-CHART-FRAMING`, `QUEUE-GRADE-REARM-WINDOW`, `UI-CONSOLE-ARTIFACT`, `RESEARCH-SLO-SURVIVOR-CONVERSION`, `UI-SIDEBAR-COLLAPSE-DESKTOP` | 10 | owner session status, created/due dates, absence of observation fields; tier 1, outside the live-money/order-path/prop/security carve-out. Closed as **dropped, not done**: nothing claims they were verified |
| (c) past-session handover | `ML-PRIMARY-15-HANDOVER`, `ML-WEEK-PLAN-1119`, `QUEUE-FILL-STANDING-W47-HANDOVER` | 3 | owner session ARCHIVED, due date past; the items they carry stay open as named pipeline items |
| manager request | `MARKOUT-HARNESS`, `EVENT-SPAN-HISTORY` closed **done** | 2 | their re-entry units are graded: `RQ-20261118-a5b3-03` verdict pass n=2375; `RQ-20261118-a5b3-01` verdict.json, 3665 of 4076 trades priced, 2018-02-26..2021-01-01 stays `could_not_look` |

**Deliberately not closed** (outside the approved rules): every other `queued` row (a dead owner makes it an ownerless backlog item, not an obsolete one), every `landed_unproven` row that names an observation, every tier-3 row awaiting the operator (31 skipped, receipts phase `row_skip`), all live-money/order-path/prop/security rows.

### 7.2 Re-owned, routed, re-dated

- **Re-owned (in_flight with a dead owner; sessions ARCHIVED, IDLE or absent from the 307 newest sessions):** returned to `queued`, owner `manager`, lane archived, note appended: `CF-GRADES-EQUITY-COMMITTED`, `UNBLOCK-WATCH`, `QUEUE-FILL-STANDING-W48`, `AUD-20261118-STORE-WRITES-UNGUARDED`, `AUTOMERGE-OVER-RED-PYTEST`, `AUTOMATION-DATACOMMIT-CONFLICT`, `LTR-ROWS-BRANCH-STALE-VALIDATOR`, `ML-EXITHEAD-ROWS-KAGGLE`, `PITCH-DECK-V2` (idle session; draft PR #26648 awaits operator sign-off), `ML-LIVE-PARITY-ML-LEGS`, `DESK-TRIGGER-SCAN-TIMEOUT`, `GATE-AUDIT`, `WORK-GAP-ALERTS`, `SEC-GITLEAKS-BASELINE-1116`, `LTR-PROP-CLOSE-FALSE-APPLIED`, `UI-SPA-BACKEND-ROUTES`, `LIVE-VM-CPU-SATURATION-1112`, `CI-SPARSE-BOOTSTRAP-FLAKE`, `BALANCE-TIP-SCRUB-2`, `DIAG-RELAY-EQUITY-LEAK`. Left in_flight: `RESEARCH-OPS-20261125-1822` and `REGIME-PROGRAM` (owner sessions RUNNING). Queued/blocked/landed rows whose owner text names a finished session were re-owned to `manager` in the same write as their re-date (833 row writes in total).
- **Re-dated (stale due dates):** past-due or undated rows got a new `due_by` by class (a *provisional* date for the planning dialogue, not a commitment): live-money/order-path 2026-11-30, ML 12-02, risk 12-04, grading 12-07, other 12-09 (created on or before 11-12) or 12-14. Receipts hold the old and new date per row. Routed pipeline items due now were re-dated through `pipeline.py` `redate()` with an observation naming the owning row's state (752 re-dated, to 12-02..12-14); **about 100 were refused by the pipeline's structured-`due_when` contract and were left as they were**.
- **Routed (routing alarm):** 133 unrouted pipeline items routed (80 to `WEEKLY-PLANNING`, 43 research-queue items to `QUEUE-FILL-STANDING-W48`, 9 export-hold items to `STORE-EXPORT-BACKFILL-258`, 1 to `LIVE-PARITY-CANDLE-MISMATCH-AVAX-1109`). `pipeline.py --stats` now reads unrouted 0.
- **Manager request P-7:** 26 open ML pipeline items whose owner row was done/dropped were re-routed to `WEEKLY-PLANNING` (not closed; the previous owner is kept in the new `routed_to`). `FRONTIER-LEVER-TABULAR` (dropped 10-23) was **reopened as queued**, due 12-02: `RQ-20261118-dbf8-02` is blocked on it, a search for `PROBE_LEARNERS` in `comms/research` finds 0 files (the install fix was never observed on a real backend) and the Kaggle GPU tabicl arm does not exist. Retire is the alternative if planning ranks it out.

### 7.3 Promotion-candidate list (soak legs graded "ready"; Stage-0 record read; mandate resolver run)

| Leg (Stage 1) | Stage-0 record (full cost stack) | `mandate_resolver --from S1 --to S2` | Read |
|---|---|---|---|
| `trend_donchian_eth_prop` (bybit_1) | net_r_oos +10.30, n=135, folds 3/4, faithful | NEEDS-DATA: no `holdout_confirmation` | **only candidate**: needs the pre-registered holdout run |
| `xrp_pullback_2h` (bybit_1) | net_r_oos +6.56, n=53, folds 2/4, faithful | REFUSE R-FOLDS (2 of 4, not a majority) | not a candidate |
| `ief_pullback_1d` (alpaca_paper) | net_r_oos +1.03, n=6, folds 1/3, approximate | REFUSE R-B1-C5 (fidelity approximate) | not a candidate |
| `tlt_pullback_1d` (alpaca_paper) | net_r_oos -6.96, n=45, folds 2/8 | REFUSE R-B1-C4 (rule verdict fail) | fails Stage 0 |
| `tqqq_trend_long_1d` | +12.77, n=54, folds 5/8 | already production (alpaca_live + mirror) | nothing to promote |

The holdout unit for `trend_donchian_eth_prop` is the resolver's data task (`mandate_resolver.py --file-needs-data`); it could not be filed during the run because the work store was being written concurrently (mint_id refused). Re-run it once the store is quiet.

### 7.4 Flags for the manager / operator

1. `soak-book-grade-weekly.yml` ran `soak_report.py --sync-pipeline` every Sunday 03:00Z and would have **re-filed about 45 PI-SOAK items** on 11-29; this PR removes the flag. Related row: `SOAK-VOCAB-RETIRE`.
2. 213 routed pipeline items name a first row id that is now done/dropped (it can be a "was:" history reference, not the live owner); they were re-dated to 12-02 and not closed. 26 of them (ML) were re-routed above; the rest need a planning disposition.
3. `PI-20261123-NEIELEFR-0002` (next_action ask_operator): the first broker-fractional-probe run (45250700088) printed the full paper `/v2/account` JSON (account number and balances) into a run log. Routed to `WEEKLY-PLANNING`; operator attention requested.
4. `SOAK-REPORT.md` and `soak-state.json` are 10 days stale (generated 11-15); this lane re-ran `soak_report.build` live instead.
5. The open-row count grew during the run (other lanes keep filing); the figures here are the post-triage re-read.
6. "Class" in the ranking is a heuristic on tier, roadmap id and title keywords, so `live-money/order-path` over-includes every tier>=2 row. Read the order inside a class as oldest-first and re-rank at planning.
7. `prepush.py` could not complete locally: `manager-scope-guard` cannot identify its subject after the WSD-S4 freeze (row MANAGER-SCOPE-STORE-IDENTITY) and pytest `-n` is unavailable in this sandbox.

### 7.5 Ranked open list per roadmap milestone (live-money/order-path, then ML, risk, grading, then oldest; top 5 per milestone; the full list is `work.py list`)

#### unmapped (219 open; live-money/order-path 117, ML 26, risk 4, grading 5, other (oldest first) 67)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `PROP-MISSION-MODEL` | queued | live-money/order-path | 2026-11-30 | Define what the prop-mission policy model should predict (label is degenerate: 0 |
| 2 | `CI-PLAYWRIGHT` | queued | live-money/order-path | 2026-11-30 | pytest-run CI has no Playwright/Chromium, so every browser-fixture test of the D |
| 3 | `PROP-FIT-DONORS-PB-SQ` | queued | live-money/order-path | 2026-11-30 | Lever: add pullback-1h and squeeze-1h/2h donors to scripts/research/p2_breakout_ |
| 4 | `ML-PRODUCERS` | queued | live-money/order-path | 2026-11-30 | Signal-time feature producers for the 4 demoted heads (conviction-meta-v1, setup |
| 5 | `MANAGER-VM-DIRECT-OPS` | queued | live-money/order-path | 2026-11-30 | Direct manager<->VM ops channel: system-actions allowlist as authenticated HTTPS |

#### L-OPS — Manager loop, work system, cost discipline (212 open; live-money/order-path 92, ML 13, risk 1, grading 11, other (oldest first) 95)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `AUD-20261104-TICK-SIZE-OWNERS` | queued | live-money/order-path | 2026-11-26 | IB futures tick sizes are defined in 4+ places (config/instruments.yaml, src/cor |
| 2 | `UI-CHART-FUTURES-FEED` | queued | live-money/order-path | 2026-12-07 | Chart phase 3 (futures): Databento CME real-time via a thin trainer-VM relay (re |
| 3 | `WSD-S6B-DESK-LTR-API` | queued | live-money/order-path | 2026-11-30 | WORK-STORE S6b: desk decisions and live-review rows written through the API (des |
| 4 | `CAP-VM-LOGS-ROOT-FIX` | queued | live-money/order-path | 2026-11-30 | cap-vm-logs runtime_logs target scans the repo runtime_logs (26 MB), not /data/b |
| 5 | `WSD-S6C-RECORD-LEDGERS` | queued | live-money/order-path | 2026-11-30 | WORK-STORE S6c: forecast grade, counterfactual + closed-trade grades, research S |

#### L-ML-LIVE — WEEK PRIORITY 1 -- ML in live trading loops within days, plus ML infra (114 open; live-money/order-path 30, ML 84)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ML-FS-STORE` | queued | live-money/order-path | 2026-11-30 | Pooled feature store: one feature registry (name, source, window, lag, venue), o |
| 2 | `ML-AM-NEXT-LIVE` | queued | live-money/order-path | 2026-11-12 | Next ML to go live does ACTIVE MANAGEMENT (in-trade: tighten / BE / partial / cl |
| 3 | `ML-DECISION-MODELS` | queued | live-money/order-path | 2026-11-13 | Three market-context ML decision models live on real money ASAP: (1) ENTRY (take |
| 4 | `ML-ENTRY-DYNAMIC-SL` | queued | live-money/order-path | 2026-11-17 | Test dynamic SL for ml_entry (v1 live, v2 bybit_1): break-even, trailing, ML SL  |
| 5 | `ML-LINE-S5-CANARY` | queued | live-money/order-path | 2026-12-07 | [MODEL] ML line S5: reduce-only canary for the first overlay that clears S3: adv |

#### L-ATM — Active trade management -- brackets as predictions (merges M20 + M31) (71 open; live-money/order-path 71)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `LTR-ROWS-BRANCH-STALE-VALIDATOR` | queued | live-money/order-path | 2026-11-30 | Rows branch carries stale validator+schema (level: number/null); reviewers' gate |
| 2 | `AMEND-PARITY-ALPACA-OPTIONS` | queued | live-money/order-path | 2026-11-30 | alpaca_options_paper: verify/define how an open debit vertical's exit levels are |
| 3 | `AMEND-PARITY-OANDA` | queued | live-money/order-path | 2026-12-02 | OANDA: wire modify_open_order SL/TP amend before oanda_practice leaves dry_run |
| 4 | `RM-AM-TP-PULLIN-PRODUCER` | queued | live-money/order-path | 2026-12-02 | Live producer for the stall_pull_in TP retarget (src/runtime/tp_revision.py rule |
| 5 | `RM-AM-EXIT-ML-WIRING` | queued | live-money/order-path | 2026-11-30 | Wire the conservative hold-biased exit model (ML-LIVE-PROMOTION-PLAN P6, rows ML |

#### L-LADDER — The promotion ladder, mechanical (operating plan phases A-E) (64 open; live-money/order-path 64)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `COST-STACK-HARNESS-RESOLVER-REMAINDER` | queued | live-money/order-path | 2026-11-30 | Route the remaining direct DEFAULT_FEE_BPS_ROUNDTRIP readers through resolve_fee |
| 2 | `COST-PER-SYMBOL-SPREAD` | queued | live-money/order-path | 2026-11-30 | Cost-model fidelity per SYMBOL: execution_costs charges one flat 3 bps round-tri |
| 3 | `HOLDOUT-INCUMBENT-GRADE` | queued | live-money/order-path | 2026-11-30 | Holdout bar vs the incumbent: exit_lever_ablation --grade holdout must report th |
| 4 | `STAGE0-ROUTE-E4-DESK` | queued | live-money/order-path | 2026-11-30 | Give e4_oi_shock_1h and claude_desk a Stage-0 evidence route (gap: no harness ro |
| 5 | `SOL-PROP-REFINE` | queued | live-money/order-path | 2026-11-30 | Refine/improve trend_donchian_sol_prop after it FAILED the prop gate (3y EV nega |

#### L-DESK — Claude trading desk -- desk-manager session over specialist lanes, pac (57 open; live-money/order-path 57)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `DESK-27-LIVE-FLOW` | queued | live-money/order-path | 2026-11-30 | Desk LIVE FLOW plan: optimize the end-to-end flow for Claude running very short- |
| 2 | `DESK-23-COVERAGE` | queued | live-money/order-path | 2026-12-02 | Later phase: label coverage targets (role x regime x symbol class x state) + sha |
| 3 | `DESK-EVENT-LISTED-TOKEN-SCOPE` | queued | live-money/order-path | 2026-12-02 | Universe lever: do Binance new-listing announcements move the LISTED token (not  |
| 4 | `DESK-EVENT-OI-FORWARD-CHECK` | queued | live-money/order-path | 2026-12-02 | Re-run desk_event_calendar_study.py on data after 2026-09-30 (forward holdout) f |
| 5 | `ML-ARCH-GENERALIST-VS-SPECIALIST` | queued | live-money/order-path | 2026-11-30 | AI trader architecture: one generalist model over all markets vs one specialist  |

#### L-PROGRAMMES — Research programmes -- the research map plus five plans (53 open; live-money/order-path 5, ML 2, grading 8, other (oldest first) 38)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `RESEARCH-TEMPLATES-STRUCTURED` | landed_unproven | live-money/order-path | 2026-11-30 | Convert the 4 single-config research templates (roster-walkforward, prop-fit-bre |
| 2 | `PR1111-M22-PAIRS-RETIRE-CASE` | landed_unproven | live-money/order-path | 2026-11-30 | M22 pairs retire case per pair (config/pairs.yaml, Tier 3): honest-R-scale re-me |
| 3 | `EVIDENCE-FORMING-ARMS-REALMONEY` | queued | live-money/order-path | 2026-11-30 | Forming-arm Stage-0 records for trend_donchian_sol_prop (bybit_2/portfolio) and  |
| 4 | `ALPACA-PARTIAL-TP-STOP-GAP` | landed_unproven | live-money/order-path | 2026-11-30 | Alpaca brackets: the venue cancels the stop leg when the take-profit leg starts  |
| 5 | `ML-ENTRY-EQ-NEUTRAL-ARM` | queued | live-money/order-path | 2026-11-28 | Parameterize alpaca_live_book.py section_neutral (c21d-06's ATR-neutral / gross- |

#### M25 — ML promotion and consolidation (32 open; live-money/order-path 8, ML 24)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ML-DRIFT-COVERED-SPAN` | queued | live-money/order-path | 2026-11-30 | drift_clean gate: publish the COVERED reference span beside the declared one on  |
| 2 | `TRAINER-CATCHUP-0800` | landed_unproven | live-money/order-path | 2026-11-30 | Move the ict-trainer-catchup timer from 05:00Z to 08:00Z so it no longer overlap |
| 3 | `ML-SERVE-SETUP-FEATURES` | landed_unproven | live-money/order-path | 2026-11-30 | [MODEL] B2 (Tier-2, held): advisory serve row carries the setup_candidates decis |
| 4 | `ML-COVERAGE-AUDIT` | landed_unproven | live-money/order-path | 2026-11-30 | ML coverage audit: ML at decision time vs the traded roster (5/51 legs, 4/23 sym |
| 5 | `ML-PROGRAMME-PLAN` | landed_unproven | live-money/order-path | 2026-11-30 | ONE consolidated ML programme: models that MANAGE TRADES (policy over hold/tight |

#### L-PROP — Prop accounts -- automate, protect, qualify (32 open; live-money/order-path 32)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `PROP-BOOK-SEARCH-1095D` | queued | live-money/order-path | 2026-11-30 | Prop book search over the admitted ETH/SOL/XRP 4h Donchian legs at the 1095d/146 |
| 2 | `ROUTE-PROP-TRACKING` | queued | live-money/order-path | 2026-11-30 | Prop executors: exit reads, idle anchor, feed-trip classification, phone service |
| 3 | `PROP-PKG-DBONLY-CLOSE` | queued | live-money/order-path | 2026-11-30 | breakout_2 pkg-c8cf8f06ac524830 reads closed/sl_cross @2427.28 while the venue p |
| 4 | `PROP-GRID-SURVIVAL-TOL` | queued | live-money/order-path | 2026-11-30 | Build: prop_ev_grid survival clause compares per-seed p_alive with no MC-SE tole |
| 5 | `TRADEIFY-OWN-LEG-DRIVER` | queued | live-money/order-path | 2026-11-30 | Build scripts/research/tradeify_ml_leg.py: pooled ETH/SOL/XRP feature table (F0- |

#### M6 — Web app UI (Svelte SPA) and Telegram channels (25 open; live-money/order-path 8, ML 3, grading 5, other (oldest first) 9)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `TELEGRAM-CHANNELS` | landed_unproven | live-money/order-path | 2026-11-30 | Telegram channel re-plumb (3 channels, one purpose each) + in-channel notificati |
| 2 | `UI-UPGRADE-1-AUTH` | landed_unproven | live-money/order-path | 2026-11-30 | Site sign-in: Google ID token + WebAuthn passkey, 30d revocable device sessions, |
| 3 | `TELEGRAM-TRIM` | landed_unproven | live-money/order-path | 2026-11-30 | Telegram trim: recurring posts off; trades channel = one ping per order package  |
| 4 | `UI-CHART-BRACKET-HISTORY` | queued | live-money/order-path | 2026-11-30 | Charts: show past SL/TP brackets (subtle) plus a marker on the bar each update h |
| 5 | `PERF-PAGE-CATEGORY-TABLE` | queued | live-money/order-path | 2026-11-30 | Performance page: top table with one row per category (live, prop, paper portfol |

#### L-AM-STANDARD — WEEK PRIORITY 3 -- active management on every real-money strategy, as  (13 open; live-money/order-path 13)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `IB-PAPER-INTRADE-EXECUTOR` | queued | live-money/order-path | 2026-11-30 | ib_paper has NO in-trade executor (scripts/ops/live_review_apply.py::ACTION_PATH |
| 2 | `HARNESS-BE-RANDOM-CONTROL` | queued | live-money/order-path | 2026-11-30 | Matched random break-even control for the trend and pullback harnesses: a break- |
| 3 | `PAPER-STOP-MISMATCH-ROOTCAUSE` | queued | live-money/order-path | 2026-11-30 | Paper venue-stop vs package-stop mismatches: root-cause and fix (ib_paper MGC br |
| 4 | `LTR-WAKE-COALESCE` | queued | live-money/order-path | 2026-11-30 | Coalesce live-review wakes per package: when a reviewer for a package is still r |
| 5 | `CF-D4-PERFREVIEW-TABLE` | queued | live-money/order-path | 2026-11-30 | Weekly performance-review counterfactual CHECK table from counterfactual_grades |

#### L-REGIME — Regime program -- know when each strategy is primed (13 open; live-money/order-path 2, ML 11)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `IR-VOL-TARGET-SIZING-STAGE0` | landed_unproven | live-money/order-path | 2026-11-30 | Build: verdict.json grading wrapper for backtest_vol_target.py so per-leg contin |
| 2 | `REGIME-VOL-SPEC-ADVISORY-ONLY` | landed_unproven | live-money/order-path | 2026-11-30 | [STRUCTURAL FIX, Tier-2/3 held] vol_detector.resolve_vol_specs must read ADVISOR |
| 3 | `REGIME-WF-VERDICT-WRAPPER` | queued | ML | 2026-12-02 | Lever: verdict.json wrapper so regime_cell_walkforward / regime_adx_cutpoint_swe |
| 4 | `MLP-D2-ADVISORY-NO-CONSUMER` | queued | ML | 2026-12-02 | [ML dev plan line MLP-D2-ADVISORY-NO-CONSUMER] sol-regime-15m-lgbm-fc-pcv-v2 (Co |
| 5 | `MLP-D2-COLLIE-5A` | queued | ML | 2026-12-02 | [ML dev plan line MLP-D2-COLLIE-5A] btc-regime-15m-lgbm-fc-pcv-v2 (Collie-5a) -- |

#### L-DATA — Data infrastructure: ingest, process, label, learn (12 open; live-money/order-path 5, ML 7)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `MARKET-DATA-LAKE` | queued | live-money/order-path | 2026-11-30 | MARKET-DATA-LAKE: pooled-ML market data lake on HF/Kaggle (all Binance UM perps  |
| 2 | `VIRTUAL-LEG-POSITIONS` | queued | live-money/order-path | 2026-11-30 | Virtual per-leg positions for intents held by the one-way book (FLIP_POLICY=hold |
| 3 | `DATA-FEEDS-NEWS-CALENDAR` | landed_unproven | live-money/order-path | 2026-11-30 | News + economic-calendar feeds are routinely maintained and watched (not one-off |
| 4 | `TRAINER-SPARSE-SYNC` | queued | live-money/order-path | 2026-11-30 | ict-trainer-git-sync: blob-filtered fetch + sparse checkout like VM-SPARSE-SYNC  |
| 5 | `CALENDAR-FOMC-RELEASE-SPLIT` | queued | live-money/order-path | 2026-11-25 | Calendar mislabels: 'FOMC Minutes' is mapped to kind fomc (impact 1.0, same as a |

#### L-ML-MECE — Every trade-lifecycle decision has one owning model family with a regi (10 open; ML 10)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ML-SLOT-REPORT` | queued | ML | 2026-12-02 | Slot report: lifecycle_slot (D1-D10) on ml-plan-items.yaml + model_names.yaml; m |
| 2 | `EVIDENCE-CLASS-BACKFILL` | queued | ML | 2026-12-02 | Declare evidence_class (holdout + claim) on the research units that PASSed in th |
| 3 | `ML-DEV-PLAN` | landed_unproven | ML | 2026-12-02 | The full iterative ML dev plan, machine-readable and live: one line per ML model |
| 4 | `MLP-D1-UNIVERSE` | queued | ML | 2026-12-02 | [ML dev plan line MLP-D1-UNIVERSE] no model, on purpose. Which legs sit on which |
| 5 | `MLP-D5-MASTIFF` | queued | ML | 2026-12-02 | [ML dev plan line MLP-D5-MASTIFF] how >= 2 packages on one (account, symbol) are |

#### M28 — Macro/value speculation sleeve (9 open; live-money/order-path 1, ML 1, grading 2, other (oldest first) 5)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `CALENDAR-EVENT-TYPES` | landed_unproven | live-money/order-path | 2026-11-30 | Expand the economic calendar's event classes - collected and logged at weight 0, |
| 2 | `NEWS-ALPHA-PROGRAM` | queued | ML | 2026-12-02 | Research program: does news / open-source unstructured data carry STANDALONE pre |
| 3 | `NEWS-HIST-REPLAY` | landed_unproven | grading | 2026-12-07 | Make the news layer BACKTESTABLE: point-in-time historical news corpus (GDELT GK |
| 4 | `NEWS-VETO-ARMB-READ` | blocked | grading | 2027-02-08 | Confirm the news-veto result: grade Arm B (vetoed-signal counterfactual net R) o |
| 5 | `CALENDAR-EVENT-REACTION-STUDY` | queued | other (oldest first) | 2026-12-09 | Event-window reaction study for calendar classes with no consensus (fed_speak, t |

#### M39 — Measurement integrity and invariant enforcement (5 open; live-money/order-path 4, other (oldest first) 1)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `AUD-20261104-FLATTEN-LABEL` | queued | live-money/order-path | 2026-11-26 | 2 operator-flatten closes (bybit_2 real-money 6844 + mirror 6845, 11-03) carry e |
| 2 | `REDUCE-READERS-INCLUDE` | queued | live-money/order-path | 2026-11-30 | Include settled reduce legs in attribution.py and account_broker_reconcile.py (b |
| 3 | `REDUCE-LEG-PRICING` | queued | live-money/order-path | 2026-11-30 | Reduce-leg pricing: fully consumed intent_reduce parents still priced from pkg.e |
| 4 | `REDUCE-FILL-QTY` | landed_unproven | live-money/order-path | 2026-11-30 | intent_reduce shrinks parents by REQUESTED qty, not FILLED qty -> journal/venue  |
| 5 | `ORPHANWATCH-ALERT` | queued | other (oldest first) | 2026-12-09 | mirror-orphan-watch.yml has no alert step: scheduled failures ping nobody (PI-20 |

#### M18 — Portfolio allocator and arbitration (5 open; live-money/order-path 5)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `SHARED-BRACKET-FIX` | in_flight | live-money/order-path | 2026-11-30 | Shared-bracket bug PI-20261104-MXMXDI3X-0001: second same-symbol package replace |
| 2 | `NETTED-SLICES` | landed_unproven | live-money/order-path | 2026-11-30 | NETTED-SLICES: per-strategy slices with own brackets + score allocation, bybit_1 |
| 3 | `ADMISSION-JOURNAL-LAG-RACE` | landed_unproven | live-money/order-path | 2026-11-30 | Slice admission refuses on a same-tick journal-lag race (venue flatter than ledg |
| 4 | `SAME-SYMBOL-ALLOCATION` | landed_unproven | live-money/order-path | 2026-11-30 | Same-symbol legs: allocate by measured head-to-head, not by name (7 groups, 4 un |
| 5 | `M18-ALLOCATOR-REEVALUATE` | queued | live-money/order-path | 2026-11-30 | Re-evaluate M18 portfolio allocator: is the arbitration-soak dependency still re |

#### L-ALERT-INTEGRATION — Every alert and venue state reaches Claude without the operator relayi (4 open; live-money/order-path 3, other (oldest first) 1)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ALERT-LEDGER-TO-MANAGER` | landed_unproven | live-money/order-path | 2026-11-30 | Every operator alert reaches the manager: one durable alert ledger on the VM, se |
| 2 | `TICK-DURATION-115S` | landed_unproven | live-money/order-path | 2026-11-30 | Trader tick takes ~115 s (signal build 49%, order_monitor 28%): 1h closed-bar si |
| 3 | `HEALTH-20261125-CFI-ALERTER` | queued | live-money/order-path | 2026-11-28 | closed_flat_invariant alerts never send: src/runtime/closed_flat_invariant.py:68 |
| 4 | `WORK-GAP-ALERTS` | queued | other (oldest first) | 2026-12-09 | Insight-link gaps and topic-map gaps as NUMBERS routed to the manager's alert pa |

#### M23 — Meta-labeling plus the signals catalog (4 open; ML 4)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `FEATURE-IMPACT-MAP` | queued | ML | 2026-12-02 | Feature impact map: per-feature impact measures per ML x asset x market x timefr |
| 2 | `FEATURES-CATALOG-UI-VERIFY` | queued | ML | 2026-12-02 | Features catalog sub-tab (Strategies & Models): verify it exists and works corre |
| 3 | `M23-SIGNALS-CATALOG-METALABEL` | landed_unproven | ML | 2026-12-02 | M23: signals catalog plus meta-labeling, high on the ML surge list |
| 4 | `METALABEL-EMIT-REMAINING-FAMILIES` | queued | ML | 2026-12-02 | Lever: adopt the harness_decision_v1 --emit-features columns (scripts/research/h |

#### M40 — Research and testing workflow (landing, grading, throughput) (4 open; other (oldest first) 4)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ROUTE-RESEARCH-DATA-ROUTES` | queued | other (oldest first) | 2026-12-09 | Research data/run routes: funding history, 1m grid, m20 collector, scheduling cl |
| 2 | `STAMP-RACE-2` | landed_unproven | other (oldest first) | 2026-12-09 | research-queue dispatcher landings: refresh must not cancel in-flight pytest-run |
| 3 | `COMPUTE-GH-FIRST` | landed_unproven | other (oldest first) | 2026-12-09 | COMPUTE-GH-FIRST: compute review recommendation |
| 4 | `PI-20261118-EFILLW47-0005` | queued | other (oldest first) | 2026-11-25 | STAMP PRs GO DIRTY AND NOTHING EVER REFRESHES OR CLOSES THEM (2026-11-18). Four  |

#### M14 — ML optimization program (validation discipline, features, MLOps) (4 open; live-money/order-path 3, ML 1)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `ML-SHARD-TRUNCATED` | landed_unproven | live-money/order-path | 2026-11-30 | ML-SHARD-TRUNCATED: BTC/SOL 15m market_raw data.jsonl cut short (151,000 / 64,00 |
| 2 | `HF-LAKE-KAGGLE-LOADER` | landed_unproven | live-money/order-path | 2026-11-30 | ml.datasets.lake reads FROZEN months from the private Kaggle mirror (metis-marke |
| 3 | `HF-LAKE-FROZEN-DELETE` | blocked | live-money/order-path | 2026-11-30 | Delete the frozen crypto copy from HF (jta-market-lake) now that the Kaggle mirr |
| 4 | `COMPUTE-GPU-WIRE` | landed_unproven | ML | 2026-12-02 | COMPUTE-GPU-WIRE: compute review recommendation |

#### L-TIMEFRAMES — Horizon frontier -- longer (daily/weekly, weeks-long holds) and shorte (3 open; live-money/order-path 3)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `TF-EQUITY-INTRADAY-BARS` | queued | live-money/order-path | 2026-11-30 | Build: a multi-year sub-hour candle lane for the Alpaca ETFs and IBKR futures pr |
| 2 | `TF-ORB-COST-STACK` | queued | live-money/order-path | 2026-11-30 | Build: full cost stack (fee + slippage + funding in bps via execution_costs.reso |
| 3 | `TF-IGNITION-HARNESS` | queued | live-money/order-path | 2026-11-30 | Build: momentum-ignition breakout harness (scripts/backtest_ignition.py: a range |

#### M22 — Small-timeframe edge and the pairs sleeve (2 open; live-money/order-path 2)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `IR-INTRADAY-SEASONALITY-HARNESS` | queued | live-money/order-path | 2026-11-30 | Build: clock-entry harness (enter at a UTC time, exit at a UTC time or bracket)  |
| 2 | `PAIRS-ALPACA-BUILD` | landed_unproven | live-money/order-path | 2026-11-30 | Build an isolated Alpaca pairs executor for GLD/GDX (Stage-1 soak on alpaca_pape |

#### M20 — Active trade management (exits, geometry, TP doctrine) -- MERGED INTO  (2 open; live-money/order-path 2)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `COVERAGE-MATRIX-REFRESH` | queued | live-money/order-path | 2026-11-30 | Regenerate the exit-refinement coverage matrix from research/results with a stal |
| 2 | `ETH-EXIT-TRAIL-GIVEBACK` | queued | live-money/order-path | 2026-11-30 | Exit refinement for trend_donchian_eth (1h): a random early close beats the leg' |

#### L-DESK-V1 — WEEK PRIORITY 2 -- trading desk production-ready V1 by the end of the  (2 open; live-money/order-path 2)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `DESK-GATE-OFFLINE-PATH` | queued | live-money/order-path | 2026-11-14 | Desk entry gate (MD-TRADE-DESK entry_generation.blocked_until, DESK-13) restated |
| 2 | `DESK-DEV-W48` | in_flight | live-money/order-path | 2026-11-26 | Desk development W48: what would make the desk more functional |

#### M27 — Scalp expansion (ict_scalp family) (1 open; live-money/order-path 1)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `SMALL-TF-ML-RESEARCH` | queued | live-money/order-path | 2026-11-30 | Research small-timeframe MLs for scalping, breakout and VWAP-style strategies (M |

#### M21 — Entry refinement (1 open; live-money/order-path 1)
| # | id | state | class | due_by | title |
|---|---|---|---|---|---|
| 1 | `P3-STRATEGY-PROGRAMME` | landed_unproven | live-money/order-path | 2026-11-30 | 03-STRATEGY-IMPROVEMENT programme plan + first 2 weeks of pre-registered units ( |

---

## 8. Housekeeping lane: the 13 audit rows re-dated to 11-26 need a live owner or a kill

Source: row `AUD-20261125-HANDOFF-TO-DYING-LANE` (weekly audit 11-25: 0 of the rows released on 11-18 changed state in 7 days; their lane, AM-OPS-7, was archived 11-19). The lane named here is the standing HOUSEKEEPING + REVIEWS lane (manager, 11-25 19:33Z). **These are proposals for the Thursday dialogue, not dispositions**: every owner and date below is the planning decision. Kill reasons are given only where this lane can state data; otherwise the row stays and gets a lane.

| Row | Tier | Last evidence (from the row's own audit notes) | Proposed disposition | Proposed due |
|---|---|---|---|---|
| `AUD-20261104-PIPELINE-DOC-PATH` | 1 | `PIPELINE.jsonl` named in CLAUDE.md (1) and CLAUDE-RULES-CANONICAL.md (5); the store is the `docs/claude/work/pipeline/` directory | housekeeping lane: doc-only fix | 11-28 |
| `AUD-20261104-PRODUCER-OK-OVER-CNL` | 1 | reproduced in 4 consecutive audits: prints OK for 5 fresh ledgers while `news_decisions` reads could_not_look | housekeeping lane: small script fix, collapsed-state rule | 11-28 |
| `AUD-20261111-PREDICATE-FALLBACK-DRIFT` | 1 | `build_research_panel.py` fallback predicate defines a different population from `_clean_trades.py` | housekeeping lane: delete the fallbacks or fail loudly | 12-02 |
| `AUD-20261111-RELAY-INVARIANTS-BRIDGE` | 1 | 11 of 12 invariants NOT-MEASURED on 11-11 (DIAG token 401, truncated relay) | housekeeping lane: relay-to-payload extractor; first re-test whether the 401 still holds | 12-02 |
| `AUD-20261028-HEALTH-CLOSE-LIST-MISS` | 1 | the 10-24 health review missed reconciler close 6470 | housekeeping lane: fix in the health-review skill/script before Saturday's run | 12-02 |
| `AUD-20261118-LANES-ON-DEAD-SESSIONS` | 1 | 271 of 855 open rows laned to dead sessions on 11-18; this triage re-owned the dead-owner in_flight rows and the dead-owner queued rows to `manager` | housekeeping lane: build the report-only dead-lane list, then re-measure; likely closes | 12-02 |
| `AUD-20261104-ITERATION-ORPHANS` | 1 | MOVING: citing parent/map 18.8% to 43.4%, leg orphans 36 to 8, LTR orphans 5 of 7 unchanged | research-ops / programme-review owns it (the iteration loop); housekeeping re-measures | 12-02 |
| `AUD-20261104-AMENDMENTS-UNLOGGED` | 1 | 28 to 29 unlogged SKILL/BRIEF versions; its owning pipeline item was killed | operator question: one backfill pass, or retire the AMENDMENTS.md ritual? Recommend one backfill pass by the housekeeping lane | 12-04 |
| `AUD-20261104-TICK-SIZE-OWNERS` | 1 (touches `ib_client.py`) | tick constants still defined in 4+ places | build lane; config/instruments.yaml as the single owner; review before it touches the order path | 12-04 |
| `AUD-20261111-SIZE-UP-AT-CALLERS` | 1 to investigate, Tier 3 to change | 2 of 6 `legalize_qty` callers do not pass `size_up` | build lane investigates; any behaviour change goes to the operator | 12-04 |
| `AUD-20261028-DEMO-FLOOR-NO-EVAL` | 1 | 7 demo-floor legs emit no eval line | build lane (trader logging) | 12-04 |
| `AUD-20261028-HOLD-VS-CLOSE-CONFLICT` | 1 | live grader: close beat hold 26 of 27 (n=27, dR -0.80, close side charged no cost); S0 lifecycle: holds +0.142 R (n=938) | live-review / desk lane: this is a research question; the live sample is selection-biased (SL-dominated window) | 12-02 |
| `AUD-20261104-FLATTEN-LABEL` | 2 (M39) | 2 operator-flatten closes labelled `reconciler_filled`; journal payload not captured | live-ops lane: confirm trade 4935 then census | 12-02 |

Items 1 and 2 of the housekeeping lane's first batch are in flight: the research-ops cadence fix is PR #28887 (`AUD-20261125-RESEARCH-OPS-CADENCE-CONTRADICTION`) and this section is `AUD-20261125-HANDOFF-TO-DYING-LANE`'s list. Re-measure at the 12-02 audit: 0 of 13 untouched.
