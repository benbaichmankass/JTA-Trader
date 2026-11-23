# cf_bulk 2026-11-23b (re-run cfb-20261123b, GitHub run 45203004546, branch cf-backtest-fidelity)

Aggregate only. ESTIMATED. Same corpus as cfb-20261123, with the harness-sidecar trail geometry, the sidecar symbol/timeframe resolver and the timeout replay.
Population: 510,345 distinct replay jobs in 363 shards (all done); 468,525 graded; not graded: no_bar_source 27,979, timeframe_unresolved 7,787, symbol_unresolved 5,407, no_bars 647 (sum 41,820; 468,525 + 41,820 = 510,345).
Fidelity abs_gap_r <= 0.10 on 76.0% of graded jobs (median 0.009 R, p90 1.09 R); previous run 31.0% (median 0.514 R, p90 2.69 R).
BT per (strategy, symbol) leg, n >= 100 graded: vs original_brackets (registered rule) PASS 67 / FAIL 65 / INDETERMINATE 217; vs the replayed harness trade PASS 61 / FAIL 71 / INDETERMINATE 217. Best arm is the in-sample maximum over the arm cells and jobs from one parameter sweep are correlated: candidates, not results.
