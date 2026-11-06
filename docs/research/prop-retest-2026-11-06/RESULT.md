# Prop superset re-test: trend_donchian_eth_4h and trend_donchian_sol_4h (2026-11-06)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-06` · lane `SOAK-BACKLOG-REVIEW` (Manager Session 2026-11-06a)

**Gates this adds or changes: none.** No roster changes. Both legs stay on `breakout_2` / `tradeify_1` / `velotrade_1` under the operator's
recorded exception (2026-11-05, *"Baseline at min size (Rec.)"*, reconfirmed ~20:50Z), and the operator's 2026-11-06 popup *"Keep both for now"*.

## Result (rule RULE-P5-GATE-BRK-PER-LEG-V3, registered 2026-10-31; primary cell = 3y window, current-stack arm)

| leg | n (3y) | Stage 0 at the prop stack | V2 | edge mean R [95% CI] | **V3** | 365d |
|---|---:|---|---|---|---|---|
| `trend_donchian_eth_4h` | 136 | +28.26 R, 3/4 folds (pass) | PASS on all 3 accounts × both arms | +0.212 [−0.127, +0.551] | **FAIL_EDGE** (6/6 cells) | n 53, −13.79 R: INDETERMINATE (floor 88), net negative |
| `trend_donchian_sol_4h` | 103 | +6.25 R, 3/4 folds (pass) | **FAIL** on all 3 accounts × both arms (EV = −eval fee; p(pass eval) ≤ 0.002) | +0.067 [−0.086, +0.219] | **FAIL** (6/6 cells) | n 31, −0.01 R: INDETERMINATE |

**What changed since 2026-10-30:**
- `eth_4h` is unchanged in kind: V2 passes, but the edge CI crosses zero, as in the 10-31 regrade.
- `sol_4h` got worse. In the 10-31 regrade it was the only V3 survivor, at n=115 with a 3y edge of +0.365 R. Today its ledger carries
  the leg's current exits, now modelled by the harness: `structure_exit pivot=5` and `trail_decay_arm_r 5.57`. The 3y net drops from +41.18 R
  to +6.25 R. The account almost never breaches, but it almost never reaches the evaluation target either, so every life loses the evaluation fee.

## Per cell (5 seeds × 1000 lives each)

| leg | account | arm | n | median B / worst B vs ceiling | EV median / worst $ per life | p(pass eval) | v2 | edge mean R [95% CI] | V3 |
|---|---|---|---|---|---|---|---|---|---|
| eth4h | breakout_2 | cur | 136 | 0.323 / 0.327 vs 0.889 | 35.81 / 33.1 | 0.416 | PASS | +0.212 [-0.127, +0.551] | FAIL_EDGE |
| eth4h | breakout_2 | ven | 136 | 0.307 / 0.332 vs 0.889 | 42.42 / 35.86 | 0.421 | PASS | +0.222 [-0.117, +0.561] | FAIL_EDGE |
| eth4h | tradeify_1 | cur | 136 | 0.203 / 0.207 vs 0.75 | 112.57 / 100.77 | 0.495 | PASS | +0.212 [-0.127, +0.551] | FAIL_EDGE |
| eth4h | tradeify_1 | ven | 136 | 0.192 / 0.217 vs 0.75 | 121.47 / 107.76 | 0.502 | PASS | +0.222 [-0.117, +0.561] | FAIL_EDGE |
| eth4h | velotrade_1 | cur | 136 | 0.167 / 0.179 vs 0.73 | 74.79 / 68.78 | 0.579 | PASS | +0.212 [-0.127, +0.551] | FAIL_EDGE |
| eth4h | velotrade_1 | ven | 136 | 0.163 / 0.172 vs 0.73 | 77.97 / 74.16 | 0.603 | PASS | +0.216 [-0.122, +0.554] | FAIL_EDGE |
| sol4h | breakout_2 | cur | 103 | 0.05 / 0.056 vs 0.889 | -20.0 / -20.0 | 0.001 | FAIL | +0.067 [-0.086, +0.219] | FAIL |
| sol4h | breakout_2 | ven | 103 | 0.055 / 0.072 vs 0.889 | -20.0 / -20.0 | 0.0 | FAIL | +0.068 [-0.084, +0.221] | FAIL |
| sol4h | tradeify_1 | cur | 103 | 0.01 / 0.016 vs 0.75 | -120.0 / -120.0 | 0.002 | FAIL | +0.067 [-0.086, +0.219] | FAIL |
| sol4h | tradeify_1 | ven | 103 | 0.008 / 0.012 vs 0.75 | -120.0 / -120.0 | 0.001 | FAIL | +0.068 [-0.084, +0.221] | FAIL |
| sol4h | velotrade_1 | cur | 103 | 0.003 / 0.005 vs 0.73 | -54.0 / -54.0 | 0.0 | FAIL | +0.067 [-0.086, +0.219] | FAIL |
| sol4h | velotrade_1 | ven | 103 | 0.003 / 0.007 vs 0.73 | -54.0 / -54.0 | 0.0 | FAIL | +0.063 [-0.090, +0.215] | FAIL |

## Method (reproducible)

The pipeline is `docs/research/prop-replacement-2026-10-30` unchanged, on a fresh window:

1. **Ledgers:** `exit_lever_ablation.py --leg <leg> --arm "P=--fee-bps-roundtrip=8;--slippage-bps-roundtrip=3;--funding-bps-per-window=5;--funding-window-hours=24" --days 1110 --start 2023-11-05 --end "2026-11-05 20:00" --grade stage0 --baseline P --delta-r 0 --folds 4 --fold-majority 3 --n-floor 30`. The configs are as on `main` (1d52e2294); the 365d slice is entry_time ≥ 2025-11-05 20:00.
2. **Cells:** `run_cells.sh`, identical to the 10-30 copy except for its directory. It covers 3 accounts × {cur, ven} × seeds 1–5 on the 3y ledger. The 365d windows are below the rule's n floor of 88, so they grade INDETERMINATE and were not simulated.
3. **Grade:** `scripts/research/prop_gate.aggregate_v2` + `edge_ci` + `grade_v3`, the one implementation, written to `summary_v3.json`.
