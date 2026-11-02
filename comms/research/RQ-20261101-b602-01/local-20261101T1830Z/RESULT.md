# RQ-20261101-b602-01 dev-fold result (lane ML-RECIPE)

Dev folds only; sealed windows read: 0; held-out read: none; lightgbm 4.6.0; seeds 7/11/13; pooled frozen-60 population.

Selectivity (13 arms, base +0.0089): ONE win, abstain in the lowest vol24 tercile +0.0220 (delta +0.0131, 6 of 8 folds, 4 of 4 years, min fold n 2,128). Cap q0.90 +0.0104, tau 0.15 +0.0079, tau 0.05 +0.0008: no win. Side: drop long +0.0239 rejected by the registered stability condition (long is negative in only 2 of 4 years); drop short -0.0181. Attribution: the gross edge is the same in the low-vol tercile (+0.0748) and the rest (+0.0724); cost per R is 0.0922 vs 0.0466, so the loss is COST SHARE. 12 arms tested: selection risk noted.

Rule: the common rule of the unit (>= 2 x max(0.0034, base seed range), >= 6 of 8 folds, positive delta in >= 3 of 4 years, every fold >= 1000 decisions). A win is a CANDIDATE for the one combined held-out read, nothing more. Lever map: research/levers/ml-entry.yaml.
