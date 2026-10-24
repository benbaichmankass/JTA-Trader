# ADA live exit review: the open ada_pullback_2h short, and what it teaches the exit (2026-10-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `ADA-LIVE-EXIT-REVIEW-1024`, dispatched by Manager Session 2026-10-24 on the operator's request at about 15:25Z:
*"the ADA trade right now is doing very well, and the stop loss has moved, but way not enough … review it: (A) what should we do, and (B) what can we learn"*.
The lane was read-only on the venue: it placed no order and amended no stop. Every number below is tagged **MEASURED** with its locator, or **INFERRED**.
Prices and R only; no balances.

## Part A — the live position (snapshot 2026-10-24 15:20–15:25Z)

| field | value | source |
|---|---|---|
| leg | `ada_pullback_2h` (module `htf_pullback_trend_2h`), **not** trend_donchian | MEASURED, `/api/diag/position_telemetry` row `pkg-a828b3dd55674bca`, trade 6726 |
| accounts | bybit_2 (real money), plus bybit_portfolio and bybit_1 (paper); all three carry the same brackets | MEASURED, `/api/diag/bybit_open_orders` captured 15:20:22Z |
| side | short ADAUSDT | MEASURED, same |
| entry | package 0.2162; bybit_2 venue average 0.2158 | MEASURED, telemetry `entry`; open_orders `entry_price` |
| opened | 2026-10-23 08:01Z (bracket created at 08:01:52Z) | MEASURED, order `created_time` |
| bars held | 17 × 2h at 15:20Z | MEASURED, telemetry `bars_held` |
| 1R | 0.00436071 = 1.5 × entry ATR 0.002907 | MEASURED `risk_per_unit`; ATR INFERRED from `atr_stop_mult` 1.5 |
| initial SL | about 0.2206 | INFERRED, entry + 1R |
| last price | 0.2012 (15:20Z), 0.2022 (15:25Z) | MEASURED, telemetry `last_price` |
| open R / peak R | +3.44 / 3.51 at 15:20Z; +3.21 / 3.58 at 15:25Z (peak is a lower bound) | MEASURED, telemetry |
| SL | 0.2154 on all three accounts, last amended 15:17:46Z | MEASURED, open_orders `PartialStopLoss.trigger_price`, `updated_time` |
| locked by SL | +0.18 R from the package entry (about +0.27 R on the bybit_2 fill) | arithmetic |
| TP | 0.1988 = 4.0 R (`tp_r: 4`); 0.56 R from price at 15:20Z | MEASURED, `PartialTakeProfit.trigger_price`; telemetry `r_to_target` |
| trail in force | `trail_mult: 5.0` × entry ATR (frozen in the package meta), Chandelier from the since-entry extreme; no decay, vol, ADX, stale or giveback lever is declared for this leg | MEASURED, `config/strategies.yaml::ada_pullback_2h`; `src/units/strategies/htf_pullback_trend_2h.py` monitor |

### Does the live SL match the deployed code? Yes, to the tick

The since-entry low implied by peak 3.51 R is 0.2162 − 3.51 × 0.00436 ≈ 0.2009. The trail is 0.2009 + 5.0 × 0.002907 = 0.2009 + 0.01454 = **0.2154**, which is the venue SL.
So this is not a bug, not a failed venue amend and not a closed-bar wait.

**PR #19856 did not affect this trade.** It changed `trend_donchian._trail_verdict`, and `exit_levers.stale_stop_verdict`, to closed bars.
`htf_pullback_trend_2h.monitor` carries its own inline Chandelier, which #19856 left unchanged: `git show --stat 23c415ae` and the module's log, where the last change is #19615.
The stale lever is undeclared on this leg, so the `stale_stop_verdict` change cannot fire here.

### Why the stop "moved, but way not enough": a structural fact about this leg

The trail sits 5.0 ATR behind the extreme, and the initial stop is 1.5 ATR, so **the trail is always 5.0 / 1.5 = 3.33 R behind the best price**. The target is 4 R.
That means **the trail can never lock more than 4 − 3.33 = +0.67 R before the target fills**.
On this leg the trail is effectively not a profit-lock; each trade either reaches TP or gives the move back. MEASURED on the A arm of `RQ-20261022-eba2-03` (n=402, 2020-07-01..2026-10-15): exits were 253 stop, 127 take_profit, **21 trail_stop**, 1 timeout.

### Options, and what the history says about each

R is measured from the package entry 0.2162. The bybit_2 fill adds about +0.09 R.

| option | worst case | best case | expected, from history (see below) |
|---|---|---|---|
| (a) leave it | +0.18 R | +4.0 R | **+3.19 R** |
| (b) SL to 0.2053 (1.5 ATR above the 0.2009 low) | +2.50 R | +4.0 R | about **+2.96 R** |
| (c) SL to 0.2031 | +3.0 R | +4.0 R | worse than (b); only 0.65 ATR of room |
| (d) close 50% now plus (b) on the rest | +2.97 R | +3.72 R | — |
| (e) close all now | +3.44 R less cost | — | — |

**History conditional on this state.** These are trades on the A arm whose MFE reached at least 3.4 R, n=32, net of fee 7.5 + slippage 3 bps round trip + funding 1 bps/8h:
- 26 of 32 (81%) reached the target.
- The other 6 left on the trail at +0.28 to +0.55 R.
- Holding gave mean +3.19 R, sd 1.35, worst +0.28 R.

**Exploratory tighten run.** An exploratory run in this lane tested the rule form of (b): from peak ≥ 3.4 R, tighten the trail to 1.5 ATR (arm `D34T15`). On the same 32 trades:
- mean +2.96 R, sd 0.56, worst +2.32 R;
- it clipped 16 target hits and rescued the 6 givebacks.

Over the whole leg:

| arm | net R | delta | folds ≥ A | maxDD R | take_profit exits |
|---|---|---|---|---|---|
| A (declared) | +92.09 | — | — | 21.25 | 127 |
| D34T15 (arm 3.4 R, tight 1.5 ATR) | +90.11 | −1.98 | 5/6 | 21.25 | 113 |
| D30T20 | +87.08 | −5.01 | 2/6 | 21.30 | 113 |
| D30T15 | +84.16 | −7.93 | 3/6 | 20.98 | 106 |
| D25T20 | +78.80 | −13.29 | 2/6 | 19.72 | 103 |

The verdict is `fail` / `incumbent_stands` for all four. Record: [`evidence/ada-live-exit-review-2026-10-24-exploratory.json`](evidence/ada-live-exit-review-2026-10-24-exploratory.json).
⚠️ This was **EXPLORATORY**: the lane picked the arms to mirror the live question, and it was not pre-registered. It is evidence for Part A, not a promotable result.
The harness fills a stop at the stop price, which flatters the tight arms, so the real cost of tightening is, if anything, larger.

The command was `python3 scripts/research/exit_lever_ablation.py --leg ada_pullback_2h --arm A= --arm D34T15='--trail-decay-arm-r=3.4;--trail-decay-tight-mult=1.5' --arm D30T15=… --arm D30T20=… --arm D25T20=… --days 2330 --start 2020-07-01 --end '2026-10-15 23:59' --grade replace --baseline A --delta-r 0 --delta-r-per-trade 0.02 --folds 6 --fold-majority 5 --dd-tol-frac 0.35 --n-floor 39`.
Baseline A reproduced the committed eba2-03 A arm exactly: n 402, +92.09 R, 127/253/21/1.

**Recommendation sent to the manager.** The first wake at 15:22Z recommended (b), before the data was read. The correction at 15:28Z said: **leave it (a)**, and tighten to 0.2053 only if the operator prefers lower variance to expected R.
Tightening costs about 0.23 R of expectation on this trade and removes the giveback tail. This is a preference, and no further data settles it.
Any amend is Tier-3 on the order path. To keep the mirrors equal, it would go to bybit_2 **and** bybit_portfolio through the sanctioned path. The trader's trail only ratchets toward price, so it would not loosen a manual tighten.

## Part B — lessons for this strategy's exit

1. **The giveback the operator saw is real, but it is small.** On the A arm, 105 trades reached 2 R. 79 hit target, and 26 gave back to between −1.09 and +0.55 R. At 3.0 R the split is 38 target to 9 giveback (+0.55 R at most); at 3.4 R it is 26 to 6.
   About 12% of trades ever reach 3 R. So a lever that protects givebacks pays on at most about 9 trades in 402, while it can clip the about 38 trades that would have hit target.
2. **About thirty exit levers have already been tried on this leg, and the declared exit has beaten every one.** They include:
   - R-armed tight trails (eba2-03, and this lane's D-arms);
   - fractional giveback (eba2-05);
   - banking and partials (eba2-12, fd06-01, b7e1-08);
   - a BE floor (a1f3-07);
   - ADX, momentum-stale, stale, time and level trails (RQ-20261018-015/016/017, RQ-20261019-004/005, RQ-20261022-001..006);
   - path-state, ER and chop gates (b7e1-*);
   - stall decay (RQ-20261018-009, *the same question on the previous open bybit_2 ADA short, 6 days ago*).

   The pattern is consistent: **with a 4 R capped target, anything that tightens before the target cannibalises target hits.** This matches the diagnosis in [`exit-failed-levers-diag-2026-10-24.md`](exit-failed-levers-diag-2026-10-24.md).
3. **Two exit questions are untested on this leg.** This lane registered both as units, with no config change:
   - [`RQ-20261024-4ef5-01`](../../research/queue/RQ-20261024-4ef5-01.yaml) — a **profit-lock STEP**: once a trade has seen m R, the stop may not sit below +k R. Arms m/k = 2.5/1.5, 3.0/1.0, 3.0/2.0, 3.4/2.5.
     A floor does not follow price, so a winner that pulls back less than (peak − k) R is untouched. That is the difference from the tight trails that failed.
     It needed a harness flag: `scripts/backtest_pullback.py --be-floor-lock-r` (byte-identical at 0; tests in `tests/test_be_floor_lock_step.py`). The flag ships in this PR.
   - [`RQ-20261024-4ef5-02`](../../research/queue/RQ-20261024-4ef5-02.yaml) — the **base trail width**: un-armed `trail_mult` 2.5/3.0/3.5/4.0 against 5.0. Every prior unit added a lever on top of 5.0, and the M8 tune (RQ-20261007-022) pinned trail_mult at 5.0.

   Both pre-register the f08c rule: replace grade; net R > A; delta ≥ 0.02 R × n(A); at least 5 of 6 folds; maxDD ≤ 1.35 × A. The window is 2020-07..2026-10, at the venue cost stack, roadmap L-ATM/M20.
   A pass is a discovery that needs one disjoint confirmation and a gap-adjusted re-run before any Tier-3 note.
4. **Not filed, because the queue already covers them:**
   - an R-armed tighter trail (f08c-01);
   - a partial at nR (f08c-07, which widens the target so a bank has a tail to pay for);
   - ADX or momentum decay (RQ-20261018-015/016; f08c-11..14 on donchian);
   - giveback near target (f08c-02);
   - a predictor-gated tighten (9a7e-01).
5. **The doctrine-level reading (INFERRED).** If the step floor also fails, this leg's exit is not leaking money. A 4 R target that 81% of 3.4 R trades reach is doing the job, and the discomfort of a wide stop on a big open winner is the cost of that design.
   The open question that remains is the **target, not the trail**: f08c-07's A6 control (target 6 R) and the TP-doctrine `tp_extend` work. This lane does not duplicate them.

## What this lane did not do

- It changed no config, placed no order and amended no stop.
- The exploratory run is not a promotion record.
- `peak_r` in telemetry is a lower bound on true MFE.
- The telemetry giveback counts in the manager wake were n=18 closed live/paper rows. They are illustrative only; the harness population (n=402) is the evidence.
