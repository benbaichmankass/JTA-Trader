# RQ-20261101-b606-01 dev-fold result (lane ML-RECIPE)

Dev folds only; sealed windows read: 0; held-out read: none; lightgbm 4.6.0; seeds 7/11/13; pooled frozen-60 population.

Cost-per-R gate (base +0.0089): 0.03 -0.0004 (a fold with 98 decisions), 0.04 +0.0088 (fold 380), 0.05 +0.0207 (min fold n 965, 35 short of the floor: indeterminate), 0.06 +0.0205 (delta +0.0115, 6 of 8 folds, 3 of 4 years, min fold n 1,697, n about 39.5k per seed): WIN, smooth (neighbour 0.05 within 0.01, monotone 0.10 -> 0.06), 0.08 +0.0126, 0.10 +0.0112. NOTE: 0.06/0.08/0.10 were first seen exploratorily before the rule was written; 0.03-0.05 were not.

Rule: the common rule of the unit (>= 2 x max(0.0034, base seed range), >= 6 of 8 folds, positive delta in >= 3 of 4 years, every fold >= 1000 decisions). A win is a CANDIDATE for the one combined held-out read, nothing more. Lever map: research/levers/ml-entry.yaml.
