# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 442.9226); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 442.9226 > 0 with 6 folds positive and 5 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 286 | 78.2643 | 0.2737 | 5/6 | 30.1373 | 0.1336 | 2.048 | 0.02935701524103857 | pass |
| DOGEUSDT | 261 | 99.4418 | 0.381 | 5/6 | 22.0325 | 0.2181 | 1.747 | 0.014305325716214002 | pass |
| LINKUSDT | 269 | 71.6637 | 0.2664 | 6/6 | 12.439 | 0.1124 | 2.371 | 0.012312500608874628 | pass |
| LTCUSDT | 259 | 75.6104 | 0.2919 | 5/6 | 11.8015 | 0.1301 | 2.244 | 0.014600066875796389 | pass |
| BCHUSDT | 274 | 71.0172 | 0.2592 | 4/6 | 17.7797 | 0.116 | 2.234 | 0.022836103678113718 | pass |
| DOTUSDT | 248 | 46.9261 | 0.1892 | 3/6 | 26.9603 | 0.0732 | 2.586 | 0.05180278567445973 | fail |
| **pooled** | 1597 | 442.9226 | 0.2773 | 6/6 | 40.1263 (seq) | - | - | 4.01199192018483e-07 | - |

Holm survivors (alpha 0.05): []

