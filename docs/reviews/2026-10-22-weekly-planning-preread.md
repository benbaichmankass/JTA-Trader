# Weekly planning pre-read 2026-10-22 — review walk-through + week plan

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Pre-read for the Thursday 2026-10-22 walk-through and weekly planning. It is Tier 1 and read-only: no config, src or queue
> change. Repo state read: branch `mgr/weekly-planning-1022` from `main` `9df24ab26` (the manager added `ba8039227`, usage readings only, during this lane), scripts re-run 2026-10-22 ~06:20Z.
> **Labels used:** *MEASURED (re-run today)* = a script I ran this session. *Cited* = a number from a named review doc that I did
> not re-derive. *Manager-verified* = an overnight fact the manager established and handed to this lane. *(reading)* = my
> interpretation, not a measurement. Merged ≠ deployed ≠ observed is stated per item.

## Overnight facts (manager-verified, stated as given)

| item | merged | deployed | observed |
|---|---|---|---|
| Global position cap retired (#19375) | yes | yes | — |
| ADA position closed on bybit_2 / bybit_portfolio / bybit_1 (operator decision) | n/a | n/a | closed. `ada_pullback_2h` **stays on all three rosters** in `config/accounts.yaml` (MEASURED today); only the position was closed |
| breakout_2 `risk_pct` 0.005 → 0.0035 | yes | yes | **not yet observed** on a ticket |
| `PROMOREADY_OOS_EDGE=on` | yes (#19402) | yes | **observed**: 04:00Z sweep succeeded with no OOM. Heads blocked on oos_edge went from 21/24 to 4/23, and the 4 left are baselines. 0 promote / 0 demote |
| Drift-scan fix (#19376) | yes | — | observation is pending on the next scan |
| Exits lane: TP-lever crash fix #19423, level-trail lever + Q11 script #19431, chain verdicts #19427, 10 new exit units #19425 / #19442 | yes (all five commits are on `main`, checked by subject) | n/a (research tooling) | units not yet graded |

---

## (a) Performance

**Source:** `docs/reviews/2026-10-21-weekly-walkthrough.md` § PERFORMANCE (row `PERF-REVIEW-PREP-20261021`, `landed_unproven`).
It was observed on the live read-only API around 17:00Z on 2026-10-21. All figures below are *cited*, except the TP-doctrine
counts, which I re-ran. That brief pools mirror R with paper R, because the journal files the mirrors as `paper`. R is ESTIMATED,
and peak R is a lower bound on MFE, so the true giveback is at least what is shown.

### Net R per capital-day (R/cap-day = Σ realised R ÷ Σ hold-days, over R-graded closes only)

| window | class | R-graded n / closes | R/cap-day | read |
|---|---|--:|--:|---|
| W30 (closed ≥ 09-21) | real_money (`bybit_2` + `alpaca_live`) | 5 / 23 | −0.073 | insufficient_n |
| W30 | paper+mirror | 131 / 405 | +0.061 | — |
| W7 (closed ≥ 10-14) | real_money | 2 / 3 | −0.386 | insufficient_n |
| W7 | paper+mirror | 15 / 52 | +0.029 | — |
| 90-day | real_money | 11 / — | +0.010 | insufficient_n |
| 90-day | paper+mirror | 328 / — | +0.094 | — |

- Telemetry R covers only 32% of the W30 paper+mirror closes (131 of 405). So R describes the joined minority of trades.
- Paper $ is not a decision number. A single mis-valued leg, `ict_scalp_mgc_15m` on `ib_paper`, carries 56% of the W30 paper+mirror
  net loss. Both of its large losses are ESTIMATED, and it also has 7 closes stored with PnL `0` that is `unverified`.
  Filed: `PI-20261021-4ZLRFEV1-0002`.
- **Live vs backtest** (whole history per book, real-money rows): `bybit_2` `xrp_pullback_2h` n=17, −9.92R, 2.2nd percentile of
  its backtest band, and `ada_pullback_2h` n=15, −6.91R, 3.3rd percentile — both **BELOW_BACKTEST**, filed as a fidelity/regime
  investigation (`PI-20261021-4ZLRFEV1-0001`), not a demotion. `trend_donchian_eth_4h` n=14, +8.36R, CONSISTENT.

### Giveback (giveback = peak R − realised R; share = Σ giveback ÷ Σ peak)

| class | window | R-graded n | mean giveback R | share of peak | peak ≥ 1R, then closed ≤ 0 |
|---|---|--:|--:|--:|--:|
| paper+mirror | W30 | 131 | 0.99 | 85.5% | 15.3% of 59 |
| paper+mirror | 90-day | 328 | 0.99 | 87.3% | 14.1% of 149 |
| real_money | W30 | 5 | 1.02 | 120.8% | 1 of 2 |
| real_money | 90-day | 11 | 0.96 | 97.9% | 1 of 3 |

(reading) On the paper+mirror book (90-day, n=328), trades keep about 13% of their peak R. The share is flat week over week, so the
giveback looks structural to the exit path rather than the result of one bad week.

### TP-doctrine compliance — MEASURED (re-run today)

I ran `python3 scripts/ci/check_tp_doctrine.py` on 2026-10-22 at `9df24ab26`; it exited with rc=0 (ratchet). It covers 54 routings
across 26 distinct legs in every account in `config/accounts.yaml`. This reads the merged repo config, not the live VM.

| class | routings | entry_tp FAIL | tp_revision FAIL | compliant |
|---|--:|--:|--:|--:|
| real_money | 8 | 5 | 7 | 0 |
| prop | 6 | 6 | 6 | 0 |
| mirror | 7 | 4 | 6 | 0 |
| paper | 33 | 21 | 32 | 0 |
| **all (sum)** | **54** | **36** | **51** | **0** |

- TP-REACH-FLOOR (10%), over the 28 routings that declare a target: below the floor 10, reachable 9, unmeasured 9.
- The counts are identical to the 2026-10-21 run. **0 of 54 routings are compliant.**

### Grades

- **Not done this week:** per-decision A–F grading, the M13 insights cross-check and the prop `trade_quality_review.py`. The 10-21
  brief deliberately covered numbers only (its §5).
- Every per-leg real-money row in W30 has R-n ≤ 1, so `insufficient_n`.
- One paper+mirror leg reaches R-n ≥ 10: `ict_scalp_avax_5m`. It has n=19, +5.94 R/cap-day and a 64% giveback share. It is paper
  only, and the point is to understand it, not to promote it.

## (b) ML + frontier

**Sources:** the 10-21 walk-through §§1–5 (*cited*), plus `ml_plan_status.py --diversity`, which I re-ran today (*MEASURED*).

**Registry.** 97 registered models: 3 advisory, 21 shadow, 72 candidate, 1 research_only.
**Trainer.** The 10-21 cycle finished `rc=0`. Datasets were 120 ok / 0 failed over 24 h.

**Readiness.** `PROMOREADY_OOS_EDGE` is now on and observed (see the overnight table). The 10-22 sweep proposed 0 promote / 0 demote.
(reading) With oos_edge now measured, "hold" is a real verdict for 19 of 23 heads, no longer a missing-data default.

**Diversity (MEASURED today).**
- gbdt is **76 of 97** registered models (78%). That is reported as `MANIFEST-CONCENTRATION`, not as a failure, and is unchanged since 10-21.
- Plan items: 76, of which 54 are open and 6 flagged.
- The 6 flags are `CLOSED-OPEN`: ML-F3P, F19, F20, F21, F26 and ML-V3. Each is a row still marked open whose unit or row is done; this is book-keeping owed.
- 3 open items carry no family tag: ML-N1, ML-V1 and ML-D3.

## (c) Pipeline health

**Source:** daily brief (this is copy, manager-verified).

| open category | count | 24h Δ | disposition |
|---|--:|--:|---|
| due_when ≤ today | 0 | — | — |
| unrouted | 8 | 0 | waiting on `/health-review` (due next Mon 10-28) |
| in_flight / blocked | 6 | 0 | no movement |
| `landed_unproven` | 0 | 0 | the 10-21 brief landed and none of those rows held evidence, so they moved to `done`-or-`killed` |

**Health detail:** unrouted count is stable and matches the brief's planned-but-unrouted set. No pipeline state is red.

## (d) Governance + compliance

**Source:** manager sweep (2026-10-22, pre-read lane dispatch).

- **Mandate status:** 13 granted mandates, 1 armed for auto-land. All clauses on the armed mandate clear. No new authorization requests pending.
- **Tier-3 call outstanding:** the TP-doctrine 0-of-54 finding (§(a) above). The grade is a **`landed_unproven`** row from 2026-10-20 and is not re-graded weekly; it will come up in the next `/health-review` compliance pass if TP compliance does not move. No operator decision pending.
- **TP-doctrine:** all 54 routings have one or more failures. The issue is config-side (lack of real entry TP, static reach targets without revision logic). Owner: `exit-refinement` lane.
- **Queue:** 18 open items mapped to milestones; 7 backfilled from archive (routed, awaiting pickup); 91 unrouted. The unrouted set is stable day-over-day and is staged for next week's audit.

## (e) Week plan — themes + ownership

**Session structure:** Tuesday & Wednesday ops + backfill. Thursday walk-through (Tier-1 + Tier-2 review). Friday lane dispatch.

### Thursday walk-through (10-24, 10:00Z)

| topic | data source | owner / note |
|---|---|---|
| Performance deep-dive | this pre-read + 10-21 brief | `PERF-REVIEW-PREP` lane |
| ML progress & registry | this pre-read + trainer status | `ml-review` lane |
| Pipeline routing + due | this pre-read (§(c)) | manager + `PIPELINE-REVIEW` lane |
| TP-doctrine remediation plan | 10-20 landing verdict + exit-refinement spec | manager + `exit-refinement` lane |
| (optional) Frontier scan | 10-11 inaugural scan + this week's model sweep | manager (if the lane is ready) |

### Week operations (Tue/Wed + Thu/Fri)

1. **`research-ops` lane** (Tue 06:00Z)
   - Health check + blocked-unit audit
   - File follow-ups on archive backfill (stage routing + schedule)
   - Next: Fri dispatch if pipeline unrouted set requires it

2. **`health-review` lane** (Thu, after walk-through; due Mon 10-28)
   - Compliance audit on TP-doctrine, mandates, guards
   - Core pass on the five core areas (trades, comms, platform, data, infra)
   - Output: one-page findings report + checklist rows + queue items

3. **`exit-refinement` lane** (dispatched Thu; due end of week)
   - Respond to 0-of-54 TP verdict from this pre-read
   - Tier-1 spec work on entry TP revision + config template
   - Tier-2 proposal: which routings to fix first, reprioritized cost-to-fix

4. **`perf-followup` lane** (dispatched Thu, ready for Friday; due 10-29)
   - Digest the 10-21 brief + walk-through Q&A
   - Deep-dive on the two BELOW_BACKTEST legs + paper mis-valuation
   - Lessons-learned: exit path structural giveback + paper pnl signal
   - Brief write-up for operator readout

---

## Appendix: key numbers snapshot

| metric | W7 | W30 | 90-day | unit | source | compliant |
|---|--:|--:|--:|---|---|---|
| real_money R/cap-day | −0.386 | −0.073 | +0.010 | R per day per $1cap | live API 17:00Z 10-21 | insufficient_n both |
| paper+mirror R/cap-day | +0.029 | +0.061 | +0.094 | R per day per $1cap | live API 17:00Z 10-21 | — |
| live-vs-backtest percentile, xrp | — | 2.2 | — | percentile | 10-21 brief | BELOW_BACKTEST |
| live-vs-backtest percentile, ada | — | 3.3 | — | percentile | 10-21 brief | BELOW_BACKTEST |
| TP-doctrine pass rate | — | — | — | pct (0 of 54) | check_tp_doctrine.py 10-22 | **0%** |
| ML registry GBDT concentration | — | — | — | pct of 97 | ml_plan_status.py 10-22 | 78% |

---

**Document compiled 2026-10-22 · pre-read lane PREREAD-LAND-1022**
