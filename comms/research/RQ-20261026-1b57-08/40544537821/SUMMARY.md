# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 111.7661); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 111.7661 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 228 | 41.7293 | 0.183 | 4/6 | 16.0585 | 0.0475 | 3.857 | 0.13707529499211596 | pass |
| NEARUSDT | 215 | 35.098 | 0.1632 | 4/6 | 11.9982 | 0.0419 | 3.894 | 0.15013120808535346 | pass |
| ATOMUSDT | 229 | -21.8632 | -0.0955 | 2/6 | 45.718 | -0.0304 | 3.145 | 0.7522209775972661 | fail |
| FILUSDT | 221 | 37.3729 | 0.1691 | 3/6 | 33.3866 | 0.0514 | 3.287 | 0.15867387628421376 | fail |
| TRXUSDT | 269 | -42.7156 | -0.1588 | 1/6 | 52.0589 | -0.0627 | 2.532 | 0.8870104400635059 | fail |
| ETCUSDT | 213 | 62.1459 | 0.2918 | 4/6 | 40.8152 | 0.0761 | 3.835 | 0.05018032376081971 | pass |
| **pooled** | 1375 | 111.7661 | 0.0813 | 4/6 | 67.8967 (seq) | - | - | 0.10112152006447 | - |

Holm survivors (alpha 0.05): []

