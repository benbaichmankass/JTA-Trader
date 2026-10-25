# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: D55: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `D55` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 33 | 11.1191 | 0.3369 | 3/6 | 7.1431 | 0.0111 | 30.424 | 0.2445941862982583 | fail |
| DOGEUSDT | 32 | 19.3103 | 0.6034 | 1/6 | 10.0858 | 0.0228 | 26.5 | 0.21749274733449897 | fail |
| LINKUSDT | 40 | -16.1079 | -0.4027 | 0/6 | 16.1079 | -0.0169 | 23.775 | 0.960184527556584 | fail |
| LTCUSDT | 36 | -13.59 | -0.3775 | 1/6 | 16.7409 | -0.0137 | 27.556 | 0.9846298364193524 | fail |
| BCHUSDT | 32 | -10.7476 | -0.3359 | 0/6 | 12.9112 | -0.0122 | 27.5 | 0.9134855143408545 | fail |
| DOTUSDT | 22 | 11.0122 | 0.5006 | 4/6 | 4.8139 | 0.0071 | 70.318 | 0.13318965449458575 | pass |
| **pooled** | 195 | 0.996 | 0.0051 | 2/6 | 50.863 (seq) | - | - | 0.488165495384153 | - |

Holm survivors (alpha 0.05): []

