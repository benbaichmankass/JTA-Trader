# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 424.775); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 424.775 > 0 with 6 folds positive and 5 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 286 | 73.6905 | 0.2577 | 5/6 | 30.9369 | 0.1258 | 2.048 | 0.037457712692873395 | pass |
| DOGEUSDT | 261 | 96.8575 | 0.3711 | 5/6 | 22.2897 | 0.2124 | 1.747 | 0.016465168236847613 | pass |
| LINKUSDT | 269 | 69.1078 | 0.2569 | 6/6 | 12.6383 | 0.1084 | 2.371 | 0.015070896541056557 | pass |
| LTCUSDT | 259 | 72.5904 | 0.2803 | 5/6 | 11.9852 | 0.1249 | 2.244 | 0.018097138257011418 | pass |
| BCHUSDT | 274 | 67.968 | 0.2481 | 4/6 | 18.0715 | 0.111 | 2.234 | 0.027850250846673242 | pass |
| DOTUSDT | 248 | 44.5596 | 0.1797 | 3/6 | 28.2854 | 0.0695 | 2.586 | 0.06105676658690201 | fail |
| **pooled** | 1597 | 424.775 | 0.266 | 6/6 | 41.2054 (seq) | - | - | 1.0959636725031254e-06 | - |

Holm survivors (alpha 0.05): []

