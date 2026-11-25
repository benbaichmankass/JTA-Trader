# Health review 2026-11-25 — real money ran clean, but on ib_paper a stop fill was booked as a reconciler close and the MGC re-entry now fails every minute; the closed-flat alert path has been silently broken

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-25` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `HEALTH-REVIEW-20261125` (session_01AFoLuMH8nrsuFCQzohVsUA, dispatched by the manager session_01AFoLuKKEyjyRMDSxQ1prHf) · window 2026-11-18 19:00Z → 2026-11-25 18:30Z · record [`comms/reviews/health/2026-11-25-health-review.json`](../../comms/reviews/health/2026-11-25-health-review.json)

**Grade: investigate.** 5 concerns (H5, H6, H9, H10, H15), 6 watches, 1 could_not_look (H16), 2 stalled calls. Direct diag worked, so every live check read full payloads.

## S. Scoreboard (`/api/bot/performance?window=7d`, since 11-18 18:27Z)

| book | n | net $ | net R | PF | read-state |
|---|---|---|---|---|---|
| Real money (bybit_2, alpaca_live) | 26 | −16.05 | −7.68 | 0.39 | read; bybit_2 known-divergent |
| Mirror (bybit_portfolio, alpaca_portfolio) | 35 | −6,250.65 | +33.09 | 0.52 | read; 80% pnl coverage; slv_trend_1h +40.9 R but −1,094 $ at 44% coverage |
| General paper | 144 | +26,558.91 | +31.89 | 1.30 | read; 91% coverage; mgc_trend_1h 2 trades +44,544 $ |

% per book: "—" (balances are not published here).
**Would a sceptical quant believe it?** ml_entry makes up 23 of the 26 real-money closes (−8.21 R). Its offline record is expR +0.0271 on n = 907, with a 95% CI of [−0.042, +0.099] (quoted from PI-20261104-PREP1104-0001, not re-run here). The interval spans zero, so no. On the mirror, R and $ have opposite signs; that is a P&L-coverage defect, not edge.

## 0. Prior calls (the 11-18 record, 8 calls)

- **Hit:**
  - C2: the MGC over-cover is gone (INV-PROTECT-OVERCOVER pass).
  - C4: the manager probe reads "0 h ago over 2,103 rows".
  - C5: live-parity `real_money_legs_could_not_check` = [].
  - C8: the trainer is at 85.1%, under 86%.
- **Miss:** C1. No further out-of-hours stacking happened: 0 Alpaca false-flat rows, and INV-JOURNAL-EXCHANGE passes on n = 7. The pipeline item closed 11-19, but row `HEALTH-20261118-OOH-FALSE-FLAT` is still `queued`, 5 days past due.
- **Void:** C3. No over-cover alert in the readable ledger span.
- **Stalled:**
  - C6, `RECONCILE-LOCK-TICK`: 3 days past due. Tick time fell from 55.5 s to 35.2 s anyway, and the top cost moved to regime scoring and signal build.
  - C7: research dispatch idle (PI-…-JFWRQYOV-0001, last checked 11-18).

*Footer: 4 hit · 1 miss · 2 unresolved · 1 void; Brier INDETERMINATE (n < 10). Follow-through: the cohort is 5 filed / 2 done. The health backlog is 73 open items with a median age of 87 d.*

## 1. CHECKS

- **H1 watch.** All units are active (the ib-gateway-watchdog timer is inactive by design). 671 snapshots: 626 ok, 44 watch, 1 concern (11-19 service). Restarts: 11-24 16:41Z, 23:59Z (#28624 deploy; ib_paper unread at boot), 11-25 05:17Z.
- **H2 ok.** The trader runs `779dc01` and main is `4ab9993`. 0 src/config files differ.
- **H3 ok.** 9/9 broker-API accounts read `api_ok`. The prop accounts, ib_live and oanda have no probe (could_not_look).
- **H4 watch.** 7 pass, 1 FAIL, 4 NOT-MEASURED. The FAIL is INV-EXIT-INTERVAL: 1 of 1,571 intervals hit 61.3 s against a 60 s limit. All 4 alpaca_paper positions carry a full-quantity OCO, and ib_paper TLT is covered.
- **H5 concern.** The ib_paper `mgc_trend_1h` re-entry is rejected `status=Inactive` every minute from 14:45Z (31 signals in the 12–16Z window).
- **H6 concern.**
  - Real money is clean: SL, TP and live-review closes only.
  - Paper: MGC 8522 was a real stop fill, booked `exchange_flat_reconciled` with no price.
  - Paper: an options vertical was left open for 1 h after 8569 closed `sl_cross`, then adopted and closed with no price (8612/8613).
  - Paper: 3 pre-market SH orphans on 11-24.
- **H7 ok.** Every alerting INV reads recent = 0 (INV-2 total 124; INV-3 total fell from 76 to 45).
- **H8 watch.** 5/5 producers are fresh. news_decisions is could_not_look for the 5th week.
- **H9 concern.** The `closed_flat_invariant` alerter raised a TypeError 23 times (11-24 09:03Z to 11-25 15:23Z). None of those violations reached a channel.
- **H10 concern.** `runnable_floor` was red on 91 of 92 runs and `theme_share_min_ratio` on 92 of 92. Breaches per run rose from 4 to 6.
- **H11 watch.** 2 cycles a day with rc 0, but 0 models trained. The registry stayed flat at 100 rows all week.
- **H12 watch.** The live VM has 29.7% free (32.3% last week). The trainer is at 85.1% used, rising +1.5 points a week, which reaches 90% around 12-16.
- **H13 watch.** The ssh sweep covered the full window: 17,275 publickey accepts, all with one key (Actions), 0 unreadable windows. Secret scanning is could_not_look.
- **H14 ok.** 96 of 1,702 commits touched Tier-2/3 paths. All 4 roster commits are HELD with records. No new gates.
- **H15 concern.** The gate set is 376 items. The unrouted count is 140 (alarm at 100) and the oldest is 21 d old. The walk was not run.
- **H16 could_not_look.** Not graded.

## 2. ANALYSIS

**Trend.**
- Worsening:
  - IB futures mechanics break every week: TLT 11-04, MGC 11-17/18, MGC 11-25.
  - Research SLO breaches are rising.
  - Live disk free space is falling for the first time in 3 reviews.
- Improving: tick time.
- Real-money exits have been clean for 4 reviews running.

**Q1. Why does MGC fail every minute?**
- Sequence:
  - 14:42:55: the protective BUY stop fills.
  - 14:44:45: the snapshot reconciler closes 8522 with no price.
  - 14:45:26: the strategy re-enters sell 27 on MGCZ6. IB cancels the parent ("Warning 202", blank reason), and the order goes Inactive.
- Hypotheses:
  - H1: the contract is in its delivery-month close-out window, because MGCZ6 is physically delivered and first notice is ~11-30. **p 0.6**
  - H2: a paper margin reject (ib_paper also holds 5,536 TLT). p 0.3
  - Transient: eliminated by 30+ identical rejects.
- The discriminating read (the IB errorEvent code, or a what-if order on MGCG7) is written on the row.

**Q2. Are exits losing their prices?** Yes, on IB and on options (8522; 8612/8613). The flat and orphan reconcilers win the race against fill detection. Real money (bybit_2) closes are all priced.

**Q3. Do money-at-risk alerts arrive?** No, for this class. The cause is `closed_flat_invariant.py:688`: it calls `outcomes.report()` without its required `status`. The tests pass because they stub the alerter. **p 0.97**

**Correlation.** One mechanism, venue exits seen only by the reconcilers, explains Q1's lost price and C3. It is filed on the existing rows (cf. JOURNAL-PNL-TRUTH), not as a new structural row.

**Hunt.** I compared this week's new error signatures with last week's. One is new: "alerter failed" (Q3).
**Surprise.** alpaca_paper bought SH 0.5 shares three times pre-market on 11-24. Each was adopted as an orphan and closed 2 min later. The source of those orders is untraced.

## 3. Decisions (ranked by money at risk)

| call | decision | tier | check | ending · due_by |
|---|---|---|---|---|
| C1 MGC Inactive loop + IB SL fill booked as reconciler close | Read the IB reject code; roll off MGCZ6 if it is the close-out window; journal IB stop fills as `sl` with price | 1/2 | 0 Inactive in 24 h; next fill priced | IB-MGC-INACTIVE-1125 (note) · 11-26 |
| C2 closed-flat alerter TypeError | `report(channel, 'violation', level=…)` + a test against the real signature | 2 | 0 "alerter failed" in 24 h | HEALTH-20261125-CFI-ALERTER · 11-28 |
| C3 options journal close leaves the vertical open | Flatten venue legs on close; price the exit | 2 | spread flat within one pass | AMEND-PARITY-ALPACA-OPTIONS (note) |
| C4 #28624 sibling propagation unobserved | No real-money package since deploy | 2 | next amend/close reaches both legs | no action: PI-20261124-RORTRAIL-0001 · 11-27 |
| C5 research floor red on 91/92 runs, stalled ≥ 3 reviews | Planning decides: re-scope, supply or kill | 1 | floor green once, or retired | HEALTH-20261125-RESEARCH-SLO-STALL · 11-27 |
| C6 options capture 7 straight failures | Set a due date, or switch to OPRA-INDICATIVE-FEED | 1 | next run green | CBOE-OPTIONS-SOURCE-BLOCKED (note; no due_by) |
| C7 0 models trained this week | Hand to /ml-review | 1 | cause named | HEALTH-20261125-TRAINER-NO-TRAINS · 11-27 |
| C8 stale prior rows (OOH fixed but open; LOCK-TICK stalled) | Owners close or re-scope | 1 | each row moves | notes on both rows · 11-27 |

**Premortem C1.** Rolling to Feb could put new entries on a thin contract, and a careless roll could leave an old-month stop resting. So roll only by the venue rule, and cancel old-month orders first.
**Premortem C2.** The alert could now page on every bybit_1 netted-sibling false positive. So route it by account class: paper goes to the manager.

## 4. Not done

- The open-set walk (§ 3c): 0 of 376 items.
- H16 soak grading.
- The collaborator and deploy-key re-read.
- Matching each ssh accept to a workflow run.
- Tracing the SH pre-market orders.
- Re-measuring the dispatcher double-fire (DISPATCH-DOUBLE-FIRE-1125, due 11-28).
- PI-20261125-0261122A-0001 (the latch): the manager is reconciling it.
- Restarts before 11-24 12:14Z were not enumerated (the alert ledger is capped at 500 rows).
