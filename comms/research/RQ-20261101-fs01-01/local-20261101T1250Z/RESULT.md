# RQ-20261101-fs01-01 — local dev-fold family ablation (2026-11-01 ~12:50Z, lane ML-FEATURE-INFRA)

Session-local run (4-core sandbox, lightgbm 4.7.0). **Dev folds only; no sealed window read.** Table: 785,928 rows / 60 symbols (665,104 dev rows after the explicit frozen-bar mask). Rule: ADMIT iff leave-one-fold-out (LOFO) delta vs A >= max(+0.010, |A-A2|) and better than A in >= 6 of 8 folds and present on >= 40% of dev rows. **Result: no family admitted.** Arm H (order-book depth) was not run (bookDepth not fetched). The unit stays blocked for an independent runner reproduction.

## Pooled (LOFO mean net R per decision)

| Arm | features | n | LOFO mean | delta vs A |
|---|---|---|---|---|
| A baseline | 20 | 67860 | +0.0010 | +0.0000 |
| A2 baseline | 20 | 58651 | +0.0027 | +0.0017 |
| B ['F1'] | 28 | 35381 | -0.0024 | -0.0034 |
| C ['F2'] | 28 | 64719 | +0.0018 | +0.0008 |
| D ['F3'] | 30 | 68156 | -0.0281 | -0.0291 |
| E ['F4'] | 29 | 51379 | -0.0560 | -0.0570 |
| F ['F5'] | 31 | 44577 | +0.0045 | +0.0035 |
| G ['F1', 'F2', 'F3', 'F4', 'F5'] | 66 | 92589 | -0.0206 | -0.0216 |
| N9 control: baseline + 9 noise columns | 29 | 52688 | -0.0157 | -0.0167 |

## Per fold (LOFO tau chosen on the other folds)

| fold start | A | A2 | B | C | D | E | F | G | N9 |
|---|---|---|---|---|---|---|---|---|---|
| 2022-01-01 | +0.001 (n 12389, tau 0.1) | -0.004 (n 12462, tau 0.1) | +0.010 (n 8527, tau 0.2) | -0.023 (n 12391, tau 0.1) | -0.027 (n 11605, tau 0.15) | -0.019 (n 13160, tau 0.1) | -0.003 (n 9058, tau 0.2) | -0.067 (n 14580, tau 0.05) | -0.005 (n 12301) |
| 2022-07-01 | -0.020 (n 11747, tau 0.1) | -0.020 (n 11689, tau 0.1) | -0.006 (n 7795, tau 0.2) | -0.021 (n 12316, tau 0.1) | -0.120 (n 12110, tau 0.15) | -0.065 (n 13132, tau 0.1) | -0.001 (n 8224, tau 0.2) | -0.089 (n 14652, tau 0.05) | -0.024 (n 9842) |
| 2023-01-01 | +0.058 (n 10793, tau 0.1) | +0.057 (n 8854, tau 0.15) | +0.081 (n 6910, tau 0.2) | +0.072 (n 10779, tau 0.1) | +0.007 (n 12126, tau 0.1) | -0.003 (n 9746, tau 0.15) | +0.012 (n 6373, tau 0.2) | +0.012 (n 13453, tau 0.05) | +0.031 (n 8824) |
| 2023-07-01 | -0.067 (n 9074, tau 0.1) | -0.066 (n 6672, tau 0.15) | -0.061 (n 4505, tau 0.2) | -0.073 (n 9086, tau 0.1) | -0.074 (n 8889, tau 0.1) | -0.084 (n 10201, tau 0.1) | -0.033 (n 7125, tau 0.15) | -0.050 (n 12287, tau 0.05) | -0.093 (n 6824) |
| 2024-01-01 | +0.024 (n 8483, tau 0.1) | +0.054 (n 5895, tau 0.15) | -0.108 (n 1589, tau 0.3) | +0.012 (n 8512, tau 0.1) | +0.005 (n 8287, tau 0.1) | -0.220 (n 1678, tau 0.3) | +0.013 (n 4784, tau 0.2) | +0.009 (n 11554, tau 0.05) | -0.070 (n 1449) |
| 2024-07-01 | -0.006 (n 5040, tau 0.15) | +0.021 (n 5388, tau 0.15) | +0.013 (n 3263, tau 0.2) | -0.142 (n 814, tau 0.3) | +0.055 (n 4980, tau 0.15) | -0.095 (n 1457, tau 0.3) | +0.065 (n 3838, tau 0.2) | +0.052 (n 10911, tau 0.05) | +0.009 (n 3207) |
| 2025-01-01 | +0.046 (n 7669, tau 0.1) | +0.056 (n 5127, tau 0.15) | -0.006 (n 936, tau 0.3) | +0.108 (n 7001, tau 0.1) | +0.078 (n 7467, tau 0.1) | -0.115 (n 1320, tau 0.3) | +0.118 (n 3429, tau 0.2) | +0.052 (n 10116, tau 0.05) | +0.043 (n 7598) |
| 2025-07-01 | -0.100 (n 2665, tau 0.15) | -0.136 (n 2564, tau 0.15) | -0.148 (n 1856, tau 0.2) | -0.050 (n 3820, tau 0.1) | -0.176 (n 2692, tau 0.15) | -0.332 (n 685, tau 0.3) | -0.181 (n 1746, tau 0.2) | -0.072 (n 5036, tau 0.05) | -0.158 (n 2643) |

Noise floor |A − A2| (LOFO) = 0.0017. The pooled-at-fixed-tau figures move 0.003 to 0.005 between seeds A and A2 (tau 0.10: +0.0063 vs +0.0092), and c692-01's own pipeline gives +0.0154 at tau 0.10 on a table with 423 more dev rows (reproduced exactly under lightgbm 4.6.0 and 4.7.0).

Reproduce: `bash`-free runner entry `scripts/research/ml_entry_v2_run.py ablation` (this PR) or the steps `vision_streams.py` → `ml_entry_v2.py build-table / arm / combine`.
