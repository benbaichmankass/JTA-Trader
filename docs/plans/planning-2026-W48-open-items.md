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
8. **Backlog triage (§0):** approve the bulk-close rules (obsolete soak items, archived-owner rows, stale due dates).

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
