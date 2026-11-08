# A1 backtest-augment runner

_Generated 2026-10-26T12:01:01.468123+00:00; run-tag `a1-crypto-weekly`; 730d; manifest `setup-candidates-metalabel-p2pool-v1.yaml`_
_Output: `artifacts/a1/backtest_trades.db` — **`is_backtest=1` rows only** (temp artifact DB, never the production money DB)_

**1033** `is_backtest=1` rows recorded across **9/9** legs (0 failed).

| strategy | symbol | tf | harness | fidelity | feed | fee bps | emitted | recorded | note |
|---|---|---|---|---|---|--:|--:|--:|---|
| `trend_donchian` | BTCUSDT | 1h | trend | approximate | binance | 7.5 | 146 | 146 | omitted: exit_head_action, exit_head_model, exit_head_threshold |
| `trend_donchian` | ETHUSDT | 1h | trend | approximate | binance | 7.5 | 150 | 150 | omitted: exit_head_action, exit_head_model, exit_head_threshold |
| `trend_donchian` | SOLUSDT | 1h | trend | approximate | binance | 7.5 | 144 | 144 | omitted: exit_head_action, exit_head_model, exit_head_threshold |
| `squeeze_breakout_4h` | BTCUSDT | 4h | squeeze | faithful | binance | 7.5 | 32 | 32 |  |
| `squeeze_breakout_4h` | ETHUSDT | 4h | squeeze | faithful | binance | 7.5 | 32 | 32 |  |
| `squeeze_breakout_4h` | SOLUSDT | 4h | squeeze | faithful | binance | 7.5 | 24 | 24 |  |
| `htf_pullback_trend_2h` | BTCUSDT | 2h | pullback | faithful | binance | 7.5 | 153 | 153 |  |
| `htf_pullback_trend_2h` | ETHUSDT | 2h | pullback | faithful | binance | 7.5 | 174 | 174 |  |
| `htf_pullback_trend_2h` | SOLUSDT | 2h | pullback | faithful | binance | 7.5 | 178 | 178 |  |

**Handoff (W2.1, trainer FIFO lane — NOT this runner):** build `include_backtest=True` pooled `setup_candidates` datasets scoped to run-tag `a1-crypto-weekly`, retrain, and evaluate on a **live-only holdout**; that verdict is the A1 answer. Authors no cell; a promotion is Tier-3.

_Read-only research tooling. Writes only `is_backtest=1` rows into a temp artifact DB._