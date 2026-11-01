# RQ-20261101-fs06-01 dev-fold result

read_state: read; sealed windows read: 0

**Result:** target change does not help the dev folds; the pooled bar-level recipe has no measured edge above the seed noise

T0 S0 -0.0017687428800656872, S1 -0.0077304998359305, spread 0.023715223182320756

| target | S0 | delta vs T0 | 2x spread | folds better | S1-S0 | fold sd | verdict |
|---|---|---|---|---|---|---|---|
| T1 | +0.0263 | +0.0281 | 0.0474 | 4 | +0.0058 | 0.054 | indeterminate |
| T2 | -0.0085 | -0.0067 | 0.0474 | 3 | -0.0044 | 0.036 | reject |
| T3 | -0.0018 | +0.0000 | 0.0474 | 0 | -0.0060 | 0.056 | reject |
| T4 | +0.0082 | +0.0099 | 0.0474 | 5 | -0.0099 | 0.068 | indeterminate |

## Rule applied (RULE-20261101-fs06-01, thresholds unchanged)
Dev folds only; sealed windows read: 0; lightgbm 4.6.0; seeds 7/11/13; training target changes, scoring is always raw net R; recipe R0; spread = T0's across-seed range of S0 (0.0237). Runs are shared with fs05-01 (R0/T0 cells are the same cells).

| target | S0 mean (seeds 7/11/13) | n per seed | delta vs T0 (2x spread 0.0474) | folds better | S1-S0 | min fold n | verdict |
|---|---|---|---|---|---|---|---|
| T0 raw | -0.0018 | 58,651/71,886/39,502 | - | - | -0.0060 | 1,079 | reference |
| T1 market-neutral | +0.0263 (+0.0004/+0.0081/+0.0705) | 3,457/3,752/1,923 | +0.0281 | 4 | +0.0058 | 41 | INDETERMINATE (folds of 41-1,275 decisions) |
| T2 rank [-1,1] | -0.0085 (-0.0141/-0.0059/-0.0055) | ~25,800 | -0.0067 | 3 | -0.0044 | 1,541 | reject |
| T3 clip +-3 | -0.0018 | = T0 | 0 | 0 | -0.0060 | 1,079 | reject: **no-op, T3 == T0 by construction** (net R spans [-2.05, +1.50]; 0 of 664,786 rows clipped); not computed separately |
| T4 first-passage | +0.0082 (+0.0132/-0.0104/+0.0217) | 43,941/54,442/41,007 | +0.0099 | 5 | -0.0099 | 817 (S1) / 1,070 (S0) | INDETERMINATE (S1 cell under 1000) |

**Result as written: no target is admitted; "target change does not help the dev folds; the pooled bar-level recipe has no measured edge above the seed noise".** Nuances: T4 would not clear 2 x spread even if gradeable (+0.0099 vs 0.0474). T1's +0.026 sits on 41-1,275 decisions per fold with an across-seed range of 0.070, so it is not a reading. The cause is the same as in fs05-01: the fixed raw-net-R tau grid does not fit rescaled scores (T1 chooses tau 0.15-0.2 and leaves late folds nearly empty).

Next iteration: RQ-20261101-d507-01. Lever map: research/levers/ml-entry.yaml.
