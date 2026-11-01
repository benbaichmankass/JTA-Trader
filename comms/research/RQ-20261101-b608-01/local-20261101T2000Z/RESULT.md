# RQ-20261101-b608-01 dev-fold result (lane ML-RECIPE): the ENTRY v2 stack on dev

Dev folds only; sealed windows read: 0; lightgbm 4.6.0; seeds 7/11/13; pooled frozen-60; base v1 +0.0089 (n about 72k per seed). Rule registered before the run (commit 1b5af9d6d).

| level | dev mean (seeds) | delta vs base | marginal on previous | folds better | years delta>0 | min fold n | accepted |
|---|---|---|---|---|---|---|---|
| S1 R2 recipe (matched share) | +0.0293 (+0.0261/+0.0296/+0.0324) | +0.0204 | +0.0204 | 6 | 3 | 3,490 | yes |
| S2 S1 + cost gate 0.06 | +0.0430 (+0.0401/+0.0442/+0.0447) | +0.0341 | +0.0137 | 8 | 4 | 1,725 | yes |
| S3 S2 + bracket 2/4 | +0.0478 (+0.0461/+0.0470/+0.0503) | +0.0388 | +0.0048 | 8 | 4 | 1,572 | yes |

Winning stack: S3 (R2 + cost gate 0.06 + 2/4). INTERACTION: stand-alone deltas R2 +0.0204, gate +0.0115, bracket +0.0037 (sum +0.0356); on the stack the marginals are +0.0204, +0.0137, +0.0048 (sum +0.0388): slightly SUPER-additive, no negative interaction. Traded-5 by level (3-seed pooled): base -0.0405, S1 -0.019, S2 +0.019, S3 +0.0315.
Dev-selected stack of dev winners: optimistic by construction; the one W1 read (b609-01) is the test.
