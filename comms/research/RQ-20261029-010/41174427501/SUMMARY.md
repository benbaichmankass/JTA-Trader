# Stage-0 (synthetic leg) -- pullback 15m -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 2370 | -452.7695 | -0.191 | 0/6 | 465.8002 | -0.3229 | 0.592 | 0.9999999847708694 | fail |
| ETHUSDT | 2438 | -277.858 | -0.114 | 0/6 | 307.0489 | -0.2004 | 0.569 | 0.999374571127373 | fail |
| XRPUSDT | 2406 | -97.8169 | -0.0407 | 2/6 | 183.9356 | -0.0699 | 0.581 | 0.8550210945275987 | fail |
| BNBUSDT | 2565 | -462.1354 | -0.1802 | 1/6 | 468.6376 | -0.3398 | 0.53 | 0.9999999648672178 | fail |
| **pooled** | 9779 | -1290.5789 | -0.132 | 0/6 | 1306.0202 (seq) | - | - | 0.999999999999954 | - |

Holm survivors (alpha 0.05): []

