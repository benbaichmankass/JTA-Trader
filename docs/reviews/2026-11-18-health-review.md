# Health review 2026-11-18 — out-of-hours Alpaca orders are booked "flat" before they fill, so 1h equity legs re-enter and stack positions the journal does not track

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-18` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `HEALTH-REVIEW-20261118` (session_01AFoLuK2LjVstJhrbRyYqmu, dispatched by the manager session_01AFoLuHbhd9wFuGJfWRqyoV) · window 2026-11-11 20:00Z → 2026-11-18 18:20Z · record [`comms/reviews/health/2026-11-18-health-review.json`](../../comms/reviews/health/2026-11-18-health-review.json)

**Grade: investigate.** 3 concerns (H4, H5, H15), 9 watches, 1 could_not_look (H16), 1 stalled call. Direct diag worked this week (no relay truncation), so `system_invariants.py` ran on full payloads.

## S. Scoreboard (`/api/bot/performance?window=7d`, since 11-11 18:10Z)

| book | n | net $ | net R | PF | read-state |
|---|---|---|---|---|---|
| Real money (bybit_2, alpaca_live) | 30 | −15.44 | −6.61 | 0.61 | read; bybit_2 known-divergent, alpaca_live unrecorded |
| Mirror (bybit_portfolio, alpaca_portfolio) | 34 | +99.81 | −3.91 | 1.01 | read |
| General paper | 128 | +56,206 | +35.85 | 1.47 | read; 91% pnl coverage; one mgc_pullback_1d trade is +45,529 |

% per book: "—" (no balance read). The 11 false `exchange_flat_reconciled` closes on 11-18 have no price, so they are excluded from these figures.
**Would a sceptical quant believe it?** ml_entry makes up 25 of the 30 real-money closes (−6.63 R). Its offline record is expR +0.0271 on n = 907, with a 95% CI of [−0.042, +0.099]. That figure is quoted from PI-20261104-PREP1104-0001 and was not re-run here. The interval spans zero, so no.

## 0. Prior calls (the 11-11 record, 7 calls)

- **Hit:**
  - C2: `--stats` now reads the work store.
  - C5: 0 unmasked IB account ids in the relay reply.
  - C6: the 04:05Z boot logged 0 "symbol invalid" lines (row closed).
  - C7: reconciler closes continued, and that call is **stalled**. PAPER-MECHANICS was closed 11-15, but the same class came back with a new cause (C1 below).
- **Miss** (better than predicted):
  - C1: disk is 32.3% free, so the 85% crossing did not happen (row closed).
  - C3: 4 research SLO breaches on 11-18 (the call said ≥ 8).
  - C4: the registry has 100 rows (the call said it would stay at 98).

*Footer: 4 hit · 3 miss; Brier INDETERMINATE (n < 10). Follow-through: the cohort is 4 filed / 2 done. The health backlog is 75 open items, 95% of them older than 14 d.*

## 1. CHECKS

- **H1 watch.** All units are active. 778 snapshots: 762 ok and 16 watch (all of them git_drift). The trader restarted 7× on 11-17, and ict-web-api wedged twice on 11-17.
- **H2 ok.** The trader runs `e0c1a09` and the web-api runs `e66d3b3` (= main). 0 src/config files differ.
- **H3 ok.** 9/9 broker-API accounts read `api_ok`. The prop accounts have no probe on this route.
- **H4 concern.** `system_invariants`: 2 FAIL, 3 NOT-MEASURED, 7 pass.
  - ib_paper MGC is short 27 with 70 lots of stops resting across 4 OCA groups.
  - The journal and the venue disagree on alpaca_paper QQQ (2 vs 1981) and alpaca_portfolio SLV (6 vs 877). Venue brackets do cover both in full.
- **H5 concern.** Same-signal re-entry on the 1h equity legs: 7× SLV and 4× QQQ on 11-18, plus QQQ trade 7712 on 11-17 21:01Z (root cause in Q1).
- **H6 watch.**
  - Real money is clean: SL 15, live-review 10, TP 3, max-hold 2.
  - Paper has 4 `stuck_strategy_watchdog` closes and 11 false-flat closes.
  - Orphan: MGC 7735.
- **H7 watch.** INV-3 alerts on 7735 (an adopted orphan with no package link). Every other alerting INV reads recent = 0 (report-only INV-2b reads recent = 2).
- **H8 watch.** 5/5 producers are fresh. news_decisions is could_not_look for the 4th week.
- **H9 watch.** `ib_stop_over_cover` CRITICAL fired twice and was `suppressed_by_policy` both times. The stray long followed 3.7 h later.
- **H10 watch.** Breaches per day fell from 9 to 2–4. The dispatcher runs about hourly, with 2 h gaps.
- **H11 watch.** 2 cycles per day with rc 0. The last cycle trained 0 models; the registry grew from 98 to 100 rows.
- **H12 watch.** The live VM has 32.3% free. The trainer is at 83.6% used, rising +1.8 points a week, which reaches 90% around 12-13.
- **H13 watch.** Secret scanning is could_not_look (GHAS off). The ssh sweep was not run.
- **H14 ok.** 204 of 1,661 commits touched Tier-2/3 paths. All 20 roster/config commits carry a hold or decision record.
- **H15 concern.** The gate set is 261 items; the open-set walk was not run.
- **H16 could_not_look.** Not graded this run.

## 2. ANALYSIS

**Trend.**
- IB over-cover keeps recurring: TLT (11-04), then MGC 6/16 (11-17), then MGC 27/70 (11-18).
- Disk and SLOs improved.
- Real-money exits have been clean for 4 reviews running.

**Q1. Why do 1h equity legs re-enter?**
- Hypotheses: an intra-bar re-fire; a partial-fill top-up; restore-on-refusal; or the row closing while its order was still pending.
- Eliminated:
  - Re-fire: the 13:05–13:09Z ticks logged `open_package_exists` and skipped.
  - Partial fill: filled_qty equals qty.
  - Restore-on-refusal: none of these orders was refused.
- **Survivor (p 0.85):** the legs fire before the open (SLV 13:03Z, QQQ 14:01Z) and after the close (QQQ 21:01Z). Alpaca holds each market bracket until 14:30Z. After the 300 s grace, `order_monitor._reconcile_orphan_exchange_positions` sees no position; the per-symbol check returns 404 and closes the row as `exchange_flat_reconciled`. The monocle then sees no open package and re-enters.
- **Arithmetic:** SLV 794+53+2+19+2+2+5 = **877**, and QQQ 1182+735+55+7+2 = **1981**. Both equal the venue quantities. Every order filled at 14:32–14:34Z.
- alpaca_live got the SLV short and stayed dry because of its long-only side filter. A pre-market **long** on real money would stack the same way.

**Q2. Where did the stray MGC long come from?** The 6-short vs 16-stop over-cover alerted at 03:58Z, and a 5-lot long was adopted at 07:42Z. **Survivor (p 0.75):** a stop fill flipped the position. The over-cover is now larger (27 vs 70).

**Q3. Is the "manager" 71 h alarm real?** No. `probe_manager` dates the register by git commits to the frozen checklist files. Pointed at the store, it reads 0 h over 1,941 rows (p 0.95). **Fixed here.**

**Correlation.** One mechanism, a row closed while its broker order is still pending, explains H4's journal mismatch, H5's re-entries and H6's unpriced closes. That is one structural call (C1).

**Hunt.**
- `tick_cost`: the tick mean is 55.5 s. `reconciliation_loop` holds `journal_sync` for 40.7 s on average, and the main tick waits 15.9 s (36% of its time). That is C6, for the audit.
- Surprise: 7 restarts on 11-17, and each restart wipes the reconciler's in-memory confirm state.

## 3. Decisions (ranked by money at risk)

| call | decision | tier | check | ending · due_by |
|---|---|---|---|---|
| C1 out-of-hours false-flat stacking (paper and mirror now; alpaca_live exposed on longs) | Before arming the snapshot close, treat a resting entry order as not flat, and/or no market brackets outside RTH; adopt or flatten the 871 SLV / 1979 QQQ untracked shares | 2 | 0 false-flat rows < 15 min old; INV-JOURNAL-EXCHANGE pass | HEALTH-20261118-OOH-FALSE-FLAT · 11-20 (PI-…-JFWRQYOV-0004) |
| C2 MGC 27 vs 70 over-cover | Cancel the excess OCA groups; name why old groups survive a flip | 2 | INV-PROTECT-OVERCOVER pass ×2 | HEALTH-20261118-MGC-OVERCOVER-STRAY · 11-19 |
| C3 paper over-cover CRITICAL is not seen by a human | Carried on C2; paging on paper is the operator's preference | 1 | each alert acted on < 2 h | on HEALTH-20261118-MGC-OVERCOVER-STRAY |
| C4 the manager alarm reads frozen git | **Fixed in this PR** (merged, not yet observed) | 1 | detail names updated_at, age < 30 h | this PR |
| C5 ict_scalp_eth_15m has no parity check on real money | Replay support for unit ict_scalp | 1 | `real_money_legs_could_not_check` = [] | PI-20261118-LRP-40FCC9DD · 11-25 |
| C6 tick 55 s from journal-lock contention, plus the restart cadence | Thu–Sun system audit | 1 | audit names cause and target | HEALTH-20261118-RECONCILE-LOCK-TICK · 11-22 |
| C7 research dispatch leaves runners idle | Existing item | 1 | < 30 min idle per hour | PI-20261118-JFWRQYOV-0001 · 11-20 |
| C8 trainer disk +1.8 points a week | No action: `ict-trainer-disk-alarm.timer` is the detector | 1 | < 86% on 11-25 | re-grade next review |

**Premortem C1.** A "resting order means not flat" rule could leave a row stuck open after its entry was cancelled at the venue. So resolve on the order's terminal status (filled or cancelled), never on its age.
**Premortem C2.** Cancelling the wrong group could leave the short with no stop. Cancel only after the remaining group is confirmed at qty 27.

## 4. Not done

- The open-set walk (§ 3c): 0 of 261 items, because the budget went to C1's root cause.
- H16 soak grading. The ssh sweep. Collaborator and deploy-key re-read.
- The full `tests/test_attention_watch.py` run fails 2 tests locally. Both fail on clean main too, because `fastapi` is not installed in this container, so it is not a code defect.
- For the Thu–Sun audit: C6 (tick and lock), the restart cadence, the ict-web-api wedges, and why `PAPER-MECHANICS-20261104` closed without a detector.
