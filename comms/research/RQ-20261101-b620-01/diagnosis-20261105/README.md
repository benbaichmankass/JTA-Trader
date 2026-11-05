# b620-01 DOES_NOT_REPRODUCE: diagnosis (lane ML-FS-RECIPE, 2026-11-05)

Dev folds only; no sealed window read (the 60-symbol fetch ends at 2026-09 but both builders clip at HOLDOUT_START before any fit, as in round 1).
The registered rule and tolerance of b620-01 are NOT changed; this is a diagnosis of why it fired.

1. `table_diff_full60.json`: ml_decision_entry.build_table (round 1) vs ml_entry_timeframe.build_table (1h/bar) on the same 60 symbols, same fetch time:
   665,156 rows each, 0 rows only in one, 0 feature or label column differing by more than 1e-5. The harness builder is NOT at fault.
2. Round 1's table had 664,786 dev rows; today's has 665,156 (+0.06%): the INPUT DATA moved since round 1 (n_train fold 0: 179,798 then, 179,804 now).
3. `round1_code_on_current_data.json`: round 1's own code path (ml_entry_recipe.run_cell R0/T0/S0, tau 0.10, seeds 7/11/13, lightgbm 4.6.0) on today's data:
   seed-mean +0.01256 (seeds +0.0166/+0.0110/+0.0101, range 0.0065, n about 71.6k). Round 1 recorded +0.0089486; b620 got +0.01078.
   So round 1's code does not reproduce round 1 on current data either: the b620 fail is data drift plus a fixed-tau metric whose seed range
   (0.0065 to 0.0136 across these runs) exceeds the registered 0.0005 tolerance, not a mechanical fault in the timeframe harness.
Not established: which months changed upstream (round 1's table is not committed), and the lightgbm/pandas build differences between hosts.
