# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 72.6081); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 72.6081 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 78 | 13.2441 | 0.1698 | 2/6 | 6.5747 | 0.0964 | 1.761 | 0.20483743297763524 | fail |
| NEARUSDT | 56 | 22.1967 | 0.3964 | 4/6 | 2.5486 | 0.2006 | 1.976 | 0.01799574676502016 | pass |
| ATOMUSDT | 70 | -6.7491 | -0.0964 | 2/6 | 12.5451 | -0.0506 | 1.907 | 0.7473159156172767 | fail |
| FILUSDT | 69 | 24.0314 | 0.3483 | 5/6 | 4.6479 | 0.1657 | 2.102 | 0.053053024896361656 | pass |
| TRXUSDT | 80 | 2.8007 | 0.035 | 5/6 | 7.6898 | 0.025 | 1.4 | 0.4085798969478384 | pass |
| ETCUSDT | 75 | 17.0838 | 0.2278 | 5/6 | 6.5069 | 0.149 | 1.529 | 0.1268039998789227 | pass |
| **pooled** | 428 | 72.6081 | 0.1696 | 5/6 | 25.0546 (seq) | - | - | 0.01259645807932504 | - |

Holm survivors (alpha 0.05): []

