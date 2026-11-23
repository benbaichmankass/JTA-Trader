# cf_bulk 2026-11-23 (CF-B1 backfill, run cfb-20261123, GitHub run 45190018547)

Aggregate result only (manifest.json, summary.json). Provenance ESTIMATED (engine replay with the engine's cost policy). Population: 510,547 distinct backtest replay jobs in 374 shards (all done, none missing); 346,345 graded; not graded: symbol_unresolved 96,198, timeframe_unresolved 51,031, no_bar_source 16,630, no_bars 343 (sum 164,202). Replay-vs-harness fidelity abs_gap_r <= 0.10 on 31.0% of graded jobs (median 0.514 R): arms are candidates, not results.
CF-BULK-BT per (strategy, symbol) leg (n >= 100 graded): PASS 48, FAIL 63, INDETERMINATE 213. The best arm is selected over the whole sample (23 arm cells), and jobs from one parameter sweep are correlated, so the CIs are optimistic.
