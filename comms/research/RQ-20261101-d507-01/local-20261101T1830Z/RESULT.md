
## Rule applied (RULE-20261101-d507-01, thresholds unchanged)
Dev folds only; sealed windows read: 0; lightgbm 4.6.0; K=3 seed ensembles, three draws; per-fold score-quantile threshold with leave-one-fold-out q.
**INDETERMINATE.** E0 (single model) -0.0030 (range 0.0091, down from 0.024 under the fixed tau grid). E1 (R0 ensemble) +0.0077, noise-immune (S1-S0 +0.0051), 6 of 8 folds, delta +0.0107 < 2 x E0 range 0.0183: no win. E2 (R1 ensemble) +0.0210, delta +0.0240 >= 0.0183 but only 5 of 8 folds and a fold at 986 decisions: indeterminate. E3 (R2 ensemble) +0.0095, 7 of 8 folds, delta +0.0125 < 0.0183, a fold at 933: indeterminate. The last dev fold (2025-07..09) is negative for every arm (-0.141 to -0.174).
Finding: the per-arm leave-one-fold-out threshold choice is itself a noise source (draw ranges 0.0136-0.0293, no smaller than the single model's). Next test at a MATCHED decision share: RQ-20261101-b607-01 (result: regularised recipes win; see its record).
