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

## Not explained (say so)

n differs by population, not reconciled: engine solo 62 vs Stage-0 25 entries since 2025-01-01. The engine takes every raw signal on a
15m clock under its own sizing/daily-loss rules; the harness folds/filters differ. Fix row below asks for the per-trade comparison once the
frame is fixed. Trail ratchet on the same 15m window was not isolated here.

## Blast radius

Legs declaring `stale_exit_bars` whose `timeframe` != the run's clock: `trend_donchian_xrp_4h`, `trend_donchian_xrp_adx25` (4h),
`gld_pullback_1h` (1h); `ict_scalp_eth_15m` is native at 15m. Any `backtest_system` / same-symbol head-to-head figure for those legs,
including RQ-20261015-1631-02 and RQ-20261120-e9b5-03, is invalid for hold-dependent exits and must not feed the allocator. The earlier
-2.96 R/18.95 cap-days old-engine figure has the same cause class (not re-run).

## Decision

No Tier-3 proposal about the leg: its Stage-0 evidence is not contradicted. Fix row `BACKTEST-SYSTEM-MONITOR-NATIVE-FRAME` filed.
