# cf_bulk 2026-11-23b (re-run cfb-20261123b, GitHub run 45203004546, branch cf-backtest-fidelity)

Aggregate only. ESTIMATED. Same corpus as cfb-20261123, with the harness-sidecar trail geometry, the sidecar symbol/timeframe resolver and the timeout replay.
Population: 510,345 distinct replay jobs in 363 shards (all done); 468,525 graded; not graded: no_bar_source 27,979, timeframe_unresolved 7,787, symbol_unresolved 5,407, no_bars 647 (sum 41,820; 468,525 + 41,820 = 510,345).
Fidelity abs_gap_r <= 0.10 on 76.0% of graded jobs (median 0.009 R, p90 1.09 R); previous run 31.0% (median 0.514 R, p90 2.69 R).
BT per (strategy, symbol) leg, n >= 100 graded: vs original_brackets (registered rule) PASS 67 / FAIL 65 / INDETERMINATE 217; vs the replayed harness trade PASS 61 / FAIL 71 / INDETERMINATE 217. Best arm is the in-sample maximum over the arm cells and jobs from one parameter sweep are correlated: candidates, not results.

## ERRATUM (2026-11-23, lane CF-FINISH-BACKFILL-20261123) — superseded by cfb-20261123w

This run entered each replayed trade at the corpus `entry_time`, which is the signal bar's OPEN, while the harness enters at the bar CLOSE. The replay therefore saw the signal bar's own range, so some trades were stopped (or targeted) on a bar the harness trade never traded in. Fixed in `cf_harness`/`cf_bulk` by `entry_at_bar_close`; re-run as **cfb-20261123w** (GitHub run 45227696759, same corpus, same 468,525 graded / 41,820 not graded).

Re-computed on w with the same `cf_bulk.leg_verdicts` over all 349 legs (population: legs with n >= 100 graded, as above):

| Quantity | this run (b) | w (corrected) |
|---|---|---|
| bt vs original_brackets: PASS / FAIL / INDETERMINATE | 67 / 65 / 217 | **18 / 114 / 217** |
| bt vs replayed harness trade: PASS / FAIL / INDETERMINATE | 61 / 71 / 217 | **15 / 117 / 217** |
| post-exit verdict: LEAVES_R / MIXED / SAVES_R / INDETERMINATE | 46 / 82 / 1 / 220 | 51 / 79 / 0 / 219 |
| trend_donchian legs: bt PASS / FAIL / INDETERMINATE | — | 9 / 46 / 24 |
| fidelity abs_gap_r <= 0.10 (468,525 graded) | 76.0%, median 0.0087 R, p90 1.09 R | **81.3%, median 0.0082 R, p90 0.80 R** |

**Affected:** every `bt` / `bt_vs_replay` PASS in `summary.json` and the "trend PASS legs" read from it (about 49 of the 67 PASS legs do not survive); the stop-width and entry-arm figures built on it. The post-exit LEAVES_R count is little changed (46 → 51). **Not affected:** the could-not-grade counts and the resolver numbers (population is identical). The fidelity share improved, so b's 76.0% understated agreement with the harness. Use `comms/research/cf_insights/2026-11-23/` and `docs/research/cf-insights-2026-11-23.md` for current figures. ESTIMATED; in-sample.
