# RQ-20261101-a508-01 dev-fold result (lane ML-RECIPE)

Dev folds only; sealed windows read: 0; held-out read: none; lightgbm 4.6.0; seeds 7/11/13; pooled frozen-60 population.

Traded slice (dev, seeds 20261101/7/11/13): traded-5 -0.0411 vs other 55 +0.0123; cost-neutral re-price -0.0262 so NOT cost-driven; BTC+ETH -0.0974 vs ADA+SOL+XRP -0.0103, gap -0.0871 >= 2 x 0.0058 so COIN-driven; cadence untested (needs b603-01). Flags: BTC HARM (-0.1291, t -3.6, negative 4 of 4 years), ETH HARM (-0.0722, t -2.2, negative 4 of 4 years), XRP/ADA/SOL UNDETERMINED. A HARM flag is a no-go PROPOSAL to the operator, never applied by the lane.

Rule: the common rule of the unit (>= 2 x max(0.0034, base seed range), >= 6 of 8 folds, positive delta in >= 3 of 4 years, every fold >= 1000 decisions). A win is a CANDIDATE for the one combined held-out read, nothing more. Lever map: research/levers/ml-entry.yaml.
