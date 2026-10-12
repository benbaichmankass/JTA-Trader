# Tune sweep — `ada_pullback_2h.adx_min`

- **Target:** `config/strategies.yaml::ada_pullback_2h.adx_min`
- **Harness:** `scripts/backtest_pullback.py`  ·  fee 7.5 bps round-trip
- **Current value:** 28.0
- **Generated:** 2026-10-12T08:52:08.230171+00:00
- **Walk-forward (k-fold anchored):** 4 folds over [2024-10-12, 2026-10-11], train_frac 0.4 — metrics below are the **OOS aggregate** (net Σ, exp μ).

## Grid (net-of-fee · OOS aggregate across folds)

| value | OOS trades | OOS net Σ | OOS exp μ | OOS maxDD | folds+ | train net Σ |
|---|---|---|---|---|---|---|
| 22.000 | 77 | 30.447 | 0.529 | 12.402 | 3/4 | 11.727 |
| 25.000 | 65 | 0.813 | 0.073 | 10.204 | 2/4 | -56.359 |
| 28.000 | 50 | 14.970 | 0.450 | 6.349 | 3/4 | -3.094 |
| 32.000 | 32 | 20.465 | 0.759 | 3.187 | 4/4 | 18.904 |
| 36.000 | 25 | 21.358 | 1.262 | 3.112 | 4/4 | 27.389 |

## Picks

- **Best net_total:** value=22.000 (net_total=30.447, trades=77)
- **Best net_expectancy (≥20 trades):** value=36.000 (exp=1.262, trades=25)

## Recommendation (advisory — Tier-3)

- **action:** `propose_value`
- **proposed value:** `36.0`
- **YAML line:** `config/strategies.yaml::ada_pullback_2h.adx_min : 36.0`
- **beats baseline:** True
- **train/OOS consistent:** True
- **robust across folds:** True (4/4 OOS-positive)
- ADVISORY — applying this is a Tier-3 config/strategies.yaml change the operator approves; this harness never writes config. Metric basis: OOS (k-fold walk-forward).
