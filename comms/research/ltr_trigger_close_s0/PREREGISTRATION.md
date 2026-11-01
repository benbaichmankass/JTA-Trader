# LTR-TRIGGER-CLOSE-S0 — pre-registration (committed BEFORE any trigger outcome is computed)

Lane LTR-CLASS-GRADE (follow-on, manager ask 2026-11-01 13:09Z). Registered ~13:20Z. At this point only population COUNTS
had been read (no deltas, no prices along any trade path).

Gates this adds or changes: none. A PASS is a candidate MECHANICAL exit rule; real money is a Tier-3 proposal the manager brings.

## Question
Does closing a trade the first time a live-review trigger fires beat holding it, net of cost? Is that better than closing at a
random time inside the same trade? This is the same test as the live review, with the reviewer removed.

## Population
Every CLOSED, non-backtest trade in the VM journal (`/api/diag/journal`, table trades) whose `strategy_name` is on a
`strategies:` roster in `config/accounts.yaml` today, on a crypto USDT symbol, whose order package is readable (initial stop
from `exit_plan.stop.price`, else `entry ∓ meta.risk_per_unit`, else `sl`). At the count read: 1,103 trades, 880 packages,
2026-05-26 → 2026-11-01, accounts bybit_1 / bybit_2 / bybit_portfolio. The UNIT is the ORDER PACKAGE: one trade per package
(the lowest trade id), because a package's accounts share one geometry and one decision. Equity/futures legs are out of scope
(no historical candle source here); this is stated, not hidden.

Candles: data-api.binance.vision spot klines at the package's timeframe (the DESK-LIFECYCLE-S0 precedent). STATED BIAS: these
are spot prices against perp fills. The basis hits the trigger arm and the random arm equally, which is why P3 is the control
comparison.

## Arms (per package, per trigger type T, first firing of T only)
- **HOLD** = the realised net R (journal fills, `net_r_for_trade` on the initial stop). This is what holding actually produced,
  including every exit the leg really took.
- **CLOSE@T** = exit at the OPEN of the bar after the first CLOSED bar on which T fires, net of the harness cost stack
  (`live_review_counterfactual.cost_legs` / `net_of_costs`, funding pro-rata to the held fraction). It counts only when that
  open is before the realised close; otherwise T "did not fire in time" and the package is not in T's sample.
- **RANDOM** = the same exit at the open of a bar drawn uniformly from the package's eligible bars (the bars after entry and
  before the realised close: the same set T could fire on). The average over 50 draws per package (seed 20261101) is the
  matched random-time-close control.
- ΔT = CLOSE@T − HOLD; ΔR = RANDOM − HOLD; edge = ΔT − ΔR (paired per package).

## Triggers replayed (config/live_trade_review.yaml `due.events`, thresholds unchanged)
These are evaluated on bar CLOSES from entry. ATR is Wilder-14 on the candles. peak_r is the max favourable CLOSE in R
(ESTIMATED; live uses telemetry passes).
`adverse_r_0.5`, `adverse_r_0.75` (close-based crossing) · `giveback` (peak ≥ 1.0, giveback ≥ max(0.5, 0.3·peak)) · `new_peak`
(peak ≥ 0.5, the first step) · `r_milestone` (≥ 1.0) · `near_target` (r_to_target ≤ 0.5) · `swing` (|Δclose| ≥ 2·ATR) · `stall`
(bars ≥ bars_by_timeframe with peak < 0.5) · `momentum_flip` (3 closes against, net ≥ 1·ATR) · `structure_break` (close beyond the
since-entry extreme close against the position by > 0.1·ATR, after 3 bars). K = 10 trigger types.
Not replayable offline, so not tested: vol_regime, funding, calendar, mechanics, daily_floor, judgement_cadence.

## Pass rule, per trigger type T (all must hold)
- P1 n ≥ 20 packages in T's sample.
- P2 mean ΔT > 0, with a bootstrap CI (package resampling, 10,000 draws) at level 1 − 0.05/K = 99.5% whose lower bound is > 0
  (Bonferroni over the 10 triggers).
- P3 mean edge (ΔT − ΔR) > 0, with its 99.5% CI lower bound > 0. The trigger's TIMING must beat closing at a random time in the
  same trade.
- P4 regime: mean ΔT > 0 in a majority of calendar months holding ≥ 5 packages, AND mean ΔT > 0 after dropping the best month.
- P5 legs: mean ΔT > 0 after dropping the single leg (strategy_name) with the largest positive sum.
Verdicts: PASS (all), FAIL (P2's CI entirely ≤ 0 or mean ΔT ≤ 0), INDETERMINATE (otherwise). Reported for every T: n, mean ΔT,
mean ΔR, mean edge, CIs (95% and 99.5%), per month, per leg, per account class, and the share of packages where T never fired
in time.
