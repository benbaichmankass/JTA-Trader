# trend_donchian_xrp_4h: the book engine mis-simulates holds; the Stage-0 record is not wrong (2026-11-26)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `XRP-BACKTEST-HOLD-FIDELITY` (Tier 1, diagnostic; no config/runtime touched). Pipeline item `PI-20261120-D3GR4UKX-0003`.
Gates this adds or changes: none.

## Verdict: ENGINE BUG in `scripts/backtest_system.py` (stale-stop age counted in clock bars). Stage-0 record stands.

## What was measured (MEASURED, reproduced locally)

Re-ran `trend_donchian_xrp_4h` solo exactly as `scripts/research/same_symbol_head_to_head.py` does (Binance-Vision 5m XRPUSDT, 15m clock,
live risk basis, full cost stack, end 2026-10-30). Population: the leg's 114 engine trades since 2023; OOS = entries on/after 2025-01-01.

| arm | OOS n | net R | capital-days | mean hold |
|---|---|---|---|---|
| engine as committed (stale_exit_bars 8) | 65 | -9.1745 | 3.3958 | 1.25 h |
| same, `stale_exit_bars` overridden to 9999 | 62 | +3.3185 | 69.11 | 26.8 h |

The first row reproduces the run-44756285851 numbers to the 4th decimal. In it 60/65 OOS trades exit `stale_stop` (mean 0.93 h, most after
ONE 15m bar, `bars_held 1`), sum -772.7 USD; the 2 `tp` trades carry +140 USD at 7.6 h. Only the stale-stop changes between the rows.

## Cause

`scripts/backtest_system.py` ~L1308 hands the owner's `monitor()` a window of the **15m clock** frame (`clock.iloc[i-300:i+1]`) while the
trade's `meta.timeframe` is `4h` and `meta.entry_time` is the 4h signal-bar OPEN (e.g. entry_ts 2023-02-16 00:00, entry_time 2023-02-15 20:00).
`src/runtime/exit_levers.py::stale_stop_verdict` counts `age_bars = len(since_entry(closed_frame(frame))) - 1` in **frame rows**. On a 15m
frame the 16 clock bars of the entry's own 4h bar already exceed `stale_exit_bars: 8`, so any trade whose first close is below entry
(`stale_exit_below_r: 0.0`) is cut on the first clock bar. Live and `backtest_trend` pass the leg's native 4h frame, where 8 bars = 32 h.

Stage-0 ledger, same leg (`comms/strategy_evidence/runs/2026-11-06/trend_donchian_xrp_4h__trades.jsonl`, 46 trades, 4 OOS folds 2022-11..2026-10):
`stale_stop` 11 trades, mean hold 40.7 h, -3.23 R; overall mean hold of entries since 2025-01-01 (n 25) is 24 h, net +4.23 R. The record's holds
are the 4h-native behaviour; the record is faithful.

## UPDATE 2026-11-26 (fix lane): a SECOND defect, and the fixed-engine numbers

The n62-vs-n25 gap was a second engine defect: `backtest_system` never applied `side_filter`. `trend_donchian_xrp_4h` is `side_filter: short`
live (strategy_signal_builders gate), but the engine traded BOTH sides: of 63 OOS trades 38 were longs the bot never takes.
All 25 short entries match the Stage-0 ledger's 25 entries since 2025-01-01 one-for-one (signal-bar open stamps; 0 ledger-only).

Fixes in `scripts/backtest_system.py` (the engine; no runtime/config): (a) monitor() gets the leg's closed NATIVE-tf frame when the leg's
tf is coarser than the clock; (b) the signal stream applies the live `_resolve_side_filter`/`_side_filter_suppresses`; signal-cache key GRID bumped.
Regression test `tests/test_backtest_system_grid.py::test_monitor_gets_native_tf_frame_and_side_filter_is_applied` (fails on the old engine:
frame spacing 15m; passes now).

Same population (XRPUSDT, OOS entries >= 2025-01-01, full cost stack, bybit_1 risk basis), solo trend_donchian_xrp_4h:

| engine | n | net R | capital-days | note |
|---|---|---|---|---|
| committed (e9b5-03) | 65 | -9.17 | 3.40 | stale_stop on 15m rows |
| native frame only | 63 | -6.84 | 53.85 | 37 sl, 12 tp, 11 stale_stop; 38 longs -6.87 R, 25 shorts +0.03 R |
| native frame + side_filter (as live) | 25 | +0.03 | 20.50 | same 25 entries as the ledger |
| Stage-0 ledger (backtest_trend, since 2025-01-01) | 25 | +4.23 | n/a (avg hold 24 h) | |

Note the 9999-override figure (+3.32 R, n62) above disabled the stale-stop outright; it is not the fixed-engine number (-6.84 R at n63).

**Still open (honest):** entries now agree 25/25, holds agree (avg 20.5 h engine vs 24 h ledger), but R differs: +0.03 (engine, 15m intrabar
SL/TP, full cost stack, USD-sized then /risk) vs +4.23 (4h-bar harness). That residual is an exit-resolution/cost-basis difference and is NOT
resolved here. It does not move the Stage-0 record (the 46-trade 4-fold record is `harness: trend`, faithful); it does mean the engine reads this
leg ~4 R lower than the Stage-0 harness on identical entries, so the engine and the harness must not be compared leg-by-leg without that bridge.

## Blast radius

Legs declaring `stale_exit_bars` whose `timeframe` != the run's clock: `trend_donchian_xrp_4h`, `trend_donchian_xrp_adx25` (4h),
`gld_pullback_1h` (1h); `ict_scalp_eth_15m` is native at 15m. Any `backtest_system` / same-symbol head-to-head figure for those legs,
including RQ-20261015-1631-02 and RQ-20261120-e9b5-03, is invalid for hold-dependent exits and must not feed the allocator. The earlier
-2.96 R/18.95 cap-days old-engine figure has the same cause class (not re-run).

## Decision

No Tier-3 proposal about the leg: its Stage-0 evidence is not contradicted. Engine fixed (row `BACKTEST-SYSTEM-MONITOR-NATIVE-FRAME`); re-runs queued as RQ-20261126-a1f0-01 (re-run of e9b5-03), -02 (of e9b5-02), -03 (of e9b5-05); e9b5-04 was retired. Other `backtest_system` consumers listed by `grep -l backtest_system research/queue/*.yaml` (RQ-20260922-007, 20261018-001, 20261101-78fc-12, 20261114-82fd-02, 20261115-a474-02, 20261119-c8e2-02, 20261122-fa22-06, e9b5-01) ran on the old engine and are NOT re-run here: any leg of theirs with tf coarser than 15m or a side_filter is affected; the manager should triage them.
