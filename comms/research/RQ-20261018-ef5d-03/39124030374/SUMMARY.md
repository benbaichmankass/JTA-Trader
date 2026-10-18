# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm D55 passes (pooled net_r 75.5043); 2 of 2 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `D20` (arm) -- pass -- pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 45 | 18.4636 | 0.4103 | 4/6 | 7.3646 | 0.0102 | 40.267 | 0.10554328916297728 | pass |
| ETHUSDT | 46 | 12.7891 | 0.278 | 3/6 | 10.7864 | 0.0072 | 38.717 | 0.16298372694754648 | fail |
| SOLUSDT | 41 | 3.575 | 0.0872 | 3/6 | 8.9755 | 0.0023 | 38.683 | 0.3549037570285778 | fail |
| XRPUSDT | 43 | 7.9747 | 0.1855 | 4/6 | 12.199 | 0.0054 | 34.488 | 0.3055604398788302 | pass |
| ADAUSDT | 44 | 7.5845 | 0.1724 | 4/6 | 7.7063 | 0.0045 | 38.318 | 0.21257525556795098 | pass |
| AVAXUSDT | 37 | 18.0532 | 0.4879 | 4/6 | 5.5615 | 0.0114 | 42.946 | 0.09680278476694565 | pass |
| **pooled** | 256 | 68.4395 | 0.2673 | 4/6 | 25.2343 (seq) | - | - | 0.014467231449741672 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (arm) -- pass -- pooled net_r 75.5043 > 0 with 5 folds positive and 5 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 30 | 6.9504 | 0.2317 | 5/6 | 3.8309 | 0.0048 | 48.6 | 0.24562353445066992 | pass |
| ETHUSDT | 35 | 8.5468 | 0.2442 | 3/6 | 8.1859 | 0.0058 | 41.857 | 0.2046738568778445 | fail |
| SOLUSDT | 31 | 16.6313 | 0.5365 | 4/6 | 7.2057 | 0.0149 | 35.968 | 0.08892797411141623 | pass |
| XRPUSDT | 23 | 11.2345 | 0.4885 | 4/6 | 5.7155 | 0.0133 | 36.783 | 0.10872236446054051 | pass |
| ADAUSDT | 35 | 8.9762 | 0.2565 | 5/6 | 6.8171 | 0.007 | 36.886 | 0.17083695831503926 | pass |
| AVAXUSDT | 25 | 23.1654 | 0.9266 | 5/6 | 3.0451 | 0.0184 | 50.48 | 0.03924184505351671 | pass |
| **pooled** | 179 | 75.5043 | 0.4218 | 5/6 | 16.6613 (seq) | - | - | 0.0019115789290878452 | - |

Holm survivors (alpha 0.05): []

