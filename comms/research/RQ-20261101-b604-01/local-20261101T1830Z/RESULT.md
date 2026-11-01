# RQ-20261101-b604-01 dev-fold result (lane ML-RECIPE)

Dev folds only; sealed windows read: 0; held-out read: none; lightgbm 4.6.0; seeds 7/11/13; pooled frozen-60 population.

Calibration: base score NOT calibrated. Decile Spearman 0.83-0.89 (pass) but slope of realised on predicted 0.16-0.19 (needs 0.7-1.3): predicted net R is about 5x too large; the score is a ranking, not an expected R. Isotonic +0.0120 (delta +0.0031, a fold with 200 decisions): indeterminate; binned remap +0.0028: no win. No confidence-scaled sizing on this score.

Rule: the common rule of the unit (>= 2 x max(0.0034, base seed range), >= 6 of 8 folds, positive delta in >= 3 of 4 years, every fold >= 1000 decisions). A win is a CANDIDATE for the one combined held-out read, nothing more. Lever map: research/levers/ml-entry.yaml.
