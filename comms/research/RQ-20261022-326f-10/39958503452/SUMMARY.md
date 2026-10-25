# Stage-0 (synthetic leg) -- squeeze 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 1166 | -2.2501 | -0.0019 | 4/6 | 46.8533 | -0.0021 | 0.922 | 0.5193474613862337 | fail |
| LTCUSDT | 1174 | -44.506 | -0.0379 | 1/6 | 57.9231 | -0.0398 | 0.953 | 0.8438717253031829 | fail |
| BCHUSDT | 1183 | -45.928 | -0.0388 | 2/6 | 72.2863 | -0.043 | 0.904 | 0.8395149769558987 | fail |
| DOTUSDT | 1098 | 30.1529 | 0.0275 | 3/6 | 34.665 | 0.0276 | 0.997 | 0.25063915133289033 | fail |
| BTCUSDT | 1221 | -45.237 | -0.037 | 1/6 | 52.8695 | -0.0402 | 0.923 | 0.8255961821080995 | fail |
| **pooled** | 5842 | -107.7685 | -0.0184 | 2/6 | 145.0116 (seq) | - | - | 0.8527942027338546 | - |

Holm survivors (alpha 0.05): []

