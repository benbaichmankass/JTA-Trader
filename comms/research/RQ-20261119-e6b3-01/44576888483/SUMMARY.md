# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 217.739); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 217.739 > 0 with 6 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| UNIUSDT | 211 | 57.102 | 0.2706 | 4/6 | 19.7509 | 0.064 | 4.228 | 0.05982491435947013 | pass |
| ICPUSDT | 162 | 39.2915 | 0.2425 | 4/6 | 19.3167 | 0.0647 | 3.748 | 0.10277113052768916 | pass |
| GRTUSDT | 193 | 31.6575 | 0.164 | 3/6 | 26.1528 | 0.0416 | 3.946 | 0.1695245665185478 | fail |
| THETAUSDT | 230 | 19.0491 | 0.0828 | 5/6 | 12.3665 | 0.0231 | 3.581 | 0.2730705017980898 | pass |
| RUNEUSDT | 226 | 75.416 | 0.3337 | 6/6 | 17.108 | 0.0758 | 4.403 | 0.019225353503901033 | pass |
| ZECUSDT | 220 | -4.7791 | -0.0217 | 3/6 | 21.8226 | -0.006 | 3.625 | 0.5613396406009352 | fail |
| **pooled** | 1242 | 217.739 | 0.1753 | 6/6 | 33.4013 (seq) | - | - | 0.003807203628828303 | - |

Holm survivors (alpha 0.05): []

