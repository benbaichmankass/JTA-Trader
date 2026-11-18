# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DASHUSDT | 217 | 6.6906 | 0.0308 | 3/6 | 16.7802 | 0.0077 | 4.028 | 0.4167354783741463 | fail |
| ONTUSDT | 225 | -34.6562 | -0.154 | 3/6 | 51.8945 | -0.0381 | 4.039 | 0.8936427283720065 | fail |
| NEOUSDT | 232 | 0.3399 | 0.0015 | 3/6 | 19.8876 | 0.0004 | 3.774 | 0.49582788891870033 | fail |
| SNXUSDT | 207 | -31.6854 | -0.1531 | 2/6 | 36.7491 | -0.0343 | 4.463 | 0.8799375216782881 | fail |
| MANAUSDT | 197 | 25.744 | 0.1307 | 4/6 | 14.3726 | 0.0361 | 3.622 | 0.19535686312256173 | pass |
| SANDUSDT | 209 | 22.761 | 0.1089 | 4/6 | 25.1094 | 0.0287 | 3.801 | 0.2365486454877005 | pass |
| **pooled** | 1287 | -10.8069 | -0.0084 | 3/6 | 112.1393 (seq) | - | - | 0.5582010115092098 | - |

Holm survivors (alpha 0.05): []

