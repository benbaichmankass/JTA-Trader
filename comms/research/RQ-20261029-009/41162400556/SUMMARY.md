# Stage-0 (synthetic leg) -- trend 15m -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 4497 | -1098.9511 | -0.2444 | 0/6 | 1105.3987 | -1.1554 | 0.211 | 1.0 | fail |
| ETHUSDT | 4499 | -629.7472 | -0.14 | 0/6 | 647.5028 | -0.6695 | 0.209 | 0.9999999999999878 | fail |
| XRPUSDT | 4619 | -718.8374 | -0.1556 | 0/6 | 723.6364 | -0.7631 | 0.204 | 0.9999999999999999 | fail |
| BNBUSDT | 4787 | -810.7288 | -0.1694 | 0/6 | 857.5493 | -0.8111 | 0.209 | 1.0 | fail |
| **pooled** | 18402 | -3258.266 | -0.1771 | 0/6 | 3308.8413 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

