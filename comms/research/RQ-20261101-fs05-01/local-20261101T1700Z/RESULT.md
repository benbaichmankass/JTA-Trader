# RQ-20261101-fs05-01 dev-fold result

read_state: read; sealed windows read: 0

**Result:** fixed recipe = R0

| arm | S0 | S1 (noise) | S2 (F1..F5) | spread | S1-S0 | immune | S2-S0 | folds S2>S0 |
|---|---|---|---|---|---|---|---|---|
| R0 | -0.0018 | -0.0077 | -0.0337 | 0.0237 | -0.0060 | True | -0.0319 | 3 |
| R1 | +0.0286 | +0.0247 | +0.0093 | 0.0399 | -0.0039 | False | +nan | - |
| R2 | +0.0253 | +0.0257 | +0.0034 | 0.0309 | +0.0004 | False | +nan | - |
| R3 | +0.0039 | +0.0022 | +0.0195 | 0.0284 | -0.0017 | False | +nan | - |

Per-fold means over seeds (S0 / S1 / S2):

- R0 folds ['2022-01-01', '2022-07-01', '2023-01-01', '2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01', '2025-07-01']
  - S0: -0.010, -0.027, +0.065, -0.059, -0.001, +0.038, +0.054, -0.114
  - S1: -0.009, -0.031, +0.035, -0.073, +0.012, +0.014, +0.046, -0.125
  - S2: -0.056, -0.064, -0.015, -0.038, -0.002, +0.094, -0.068, -0.071
- R1 folds ['2022-01-01', '2022-07-01', '2023-01-01', '2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01', '2025-07-01']
  - S0: +0.023, +0.022, +0.043, -0.022, +0.062, +0.088, +0.103, -0.160
  - S1: +0.029, +0.004, +0.054, -0.038, +0.088, +0.077, +0.100, -0.190
  - S2: -0.010, -0.007, +0.007, -0.007, +0.030, +0.116, +0.042, -0.107
- R2 folds ['2022-01-01', '2022-07-01', '2023-01-01', '2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01', '2025-07-01']
  - S0: +0.031, +0.017, +0.078, -0.039, +0.056, +0.113, +0.033, -0.192
  - S1: +0.021, +0.016, +0.075, -0.031, +0.069, +0.185, +0.044, -0.187
  - S2: +0.010, -0.008, -0.004, -0.016, +0.007, +0.179, -0.089, -0.049
- R3 folds ['2022-01-01', '2022-07-01', '2023-01-01', '2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01', '2025-07-01']
  - S0: -0.035, -0.042, +0.035, -0.017, +0.031, +0.094, +0.053, -0.130
  - S1: -0.018, -0.014, +0.021, -0.033, +0.019, +0.082, +0.046, -0.206
  - S2: +0.028, -0.027, -0.077, +0.046, +0.091, +0.033, +0.341, -0.189

## Rule applied (RULE-20261101-fs05-01, thresholds unchanged)
Dev folds only; sealed windows read: 0; lightgbm 4.6.0; seeds 7/11/13; 36 cells. spread = across-seed range of the arm's S0 pooled LOFO mean (interpretation fixed before the run; the max over S0/S1/S2 is in result.json as a sensitivity).

| arm | S0 mean (seeds 7/11/13) | n per seed (S0) | S1 (noise) | S2 (F1..F5) | min fold n | verdict |
|---|---|---|---|---|---|---|
| R0 | -0.0018 (+0.0027/+0.0079/-0.0158) | 58,651/71,886/39,502 | -0.0077 | -0.0337 | 1,079 | noise-immune (S1-S0 -0.0060 >= -0.0237); S2 worse, 3 of 8 folds better: no family admitted |
| R1 | +0.0286 (+0.0359/+0.0449/+0.0050) | 40,819/40,620/34,362 | +0.0247 | +0.0093 | 941 | INDETERMINATE (a fold under 1000 decisions) |
| R2 | +0.0253 (+0.0453/+0.0144/+0.0160) | 24,631/34,147/44,198 | +0.0257 | +0.0034 | 250 | INDETERMINATE |
| R3 | +0.0039 (+0.0053/+0.0174/-0.0110) | 76,165/38,017/74,246 | +0.0022 | +0.0195 | 424 | INDETERMINATE |

**Result as written: fixed recipe = R0 (the only gradeable noise-immune arm), and NO family admitted.** R0's S0 mean is -0.0018: this is a bookkeeping outcome of the rule, not evidence of edge. R1/R2/R3 are not failed, they are ungradeable under the registered n clause.

## Findings beyond the rule
1. **Seed spread is 14x what the unit assumed.** Across-seed range of the pooled mean: 0.012-0.040 per cell (R0 S0 0.0237) versus the 0.0017 A-vs-A2 figure in the power basis. Any 0.01 effect is inside it.
2. **R3 shadow selection** kept 10-17 of 20 columns per fold and, on S1, still let 0-3 of the 9 noise columns through.
3. **The tau grid is the defect for regularised arms:** R1/R2/R3 push scores toward zero, the best tau lands on a few hundred decisions in the late folds, and the 1000-per-fold floor trips.
4. **Last fold 2025-07..09 is negative for every arm** (-0.11 to -0.21 on S0): unattributed.
5. Runner constraints: the `fs*` ids fail the hex id check and `timeout_minutes: 600` exceeds script_run's 330 cap (rows RESEARCH-UNIT-ID-REGEX, ML-RECIPE). Results here are local.

Next iteration: RQ-20261101-d507-01 (K-seed ensemble and per-fold score-quantile threshold). Lever map: research/levers/ml-entry.yaml.
