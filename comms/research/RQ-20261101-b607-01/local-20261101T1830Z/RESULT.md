# RQ-20261101-b607-01 dev-fold result (lane ML-RECIPE)

Dev folds only; sealed windows read: 0; held-out read: none; lightgbm 4.6.0; pooled frozen-60; every arm takes the same share of rows per fold as the frozen v1 base at tau 0.10 (n about 72k per seed, min fold n 3,490-3,636); base +0.0089 (seed range 0.0019).

| arm | S0 mean (seeds/draws) | delta vs base | folds better | years delta>0 | S1-S0 | noise-immune | verdict |
|---|---|---|---|---|---|---|---|
| R1 single (colsample .5, min_child 2000, lambda 50) | +0.0204 (+0.0177/+0.0196/+0.0238) | +0.0114 | 6 | 3 | +0.0028 | yes | WIN |
| R2 single (R1 + 15 leaves, lr .02, 450 trees) | +0.0293 (+0.0261/+0.0296/+0.0324) | +0.0204 | 6 | 3 | +0.0012 | yes | WIN |
| E1 R0 K=3 ensemble | +0.0135 | +0.0045 | 5 | 3 | -0.0035 | yes | no win |
| E2 R1 K=3 ensemble | +0.0245 | +0.0155 | 6 | 3 | -0.0004 | yes | WIN |
| E3 R2 K=3 ensemble | +0.0303 | +0.0214 | 6 | 3 | +0.0031 | yes | WIN |

Rule: the common rule plus noise-immunity (S1 - S0 >= -range). Reading: REGULARISATION is the lever (R2 single +0.0293); ensembling adds little on top (E3 +0.0303 vs +0.0293; the plain R0 ensemble does not win). 5 arms tested on dev; a win is a CANDIDATE for the one combined held-out read, nothing more. The stack of recipe + cost gate + bracket is untested (interaction).
