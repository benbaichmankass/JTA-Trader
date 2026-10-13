# Tune sweep — `ada_pullback_2h.atr_stop_mult`

- **Target:** `config/strategies.yaml::ada_pullback_2h.atr_stop_mult`
- **Harness:** `scripts/backtest_pullback.py`  ·  fee 7.5 bps round-trip
- **Current value:** 1.5
- **Generated:** 2026-10-12T08:51:33.990401+00:00
- **Walk-forward (k-fold anchored):** 4 folds over [2024-10-12, 2026-10-11], train_frac 0.4 — metrics below are the **OOS aggregate** (net Σ, exp μ).

## Grid (net-of-fee · OOS aggregate across folds)

| value | OOS trades | OOS net Σ | OOS exp μ | OOS maxDD | folds+ | train net Σ |
|---|---|---|---|---|---|---|
| 1.500 | 50 | 14.970 | 0.450 | 6.349 | 3/4 | -3.094 |
| 2.000 | 48 | 11.268 | 0.372 | 6.269 | 3/4 | 2.710 |
| 2.500 | 45 | 6.070 | 0.234 | 5.218 | 3/4 | 24.534 |
| 3.000 | 45 | 3.051 | 0.145 | 4.218 | 3/4 | 31.540 |

## Picks

- **Best net_total:** value=1.500 (net_total=14.970, trades=50)
- **Best net_expectancy (≥20 trades):** value=1.500 (exp=0.450, trades=50)

## Recommendation (advisory — Tier-3)

- **action:** `hold_current`
- **proposed value:** `1.5`
- **YAML line:** `config/strategies.yaml::ada_pullback_2h.atr_stop_mult : 1.5`
- **beats baseline:** False
- **train/OOS consistent:** False
- **robust across folds:** False (3/4 OOS-positive)
- ADVISORY — applying this is a Tier-3 config/strategies.yaml change the operator approves; this harness never writes config. Metric basis: OOS (k-fold walk-forward). ⚠ OOS pick is not net-positive in-sample — treat as weak. ⚠ OOS pick positive in only 3/4 folds — not robust across regimes.
