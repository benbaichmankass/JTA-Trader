# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 350.617); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 350.617 > 0 with 5 folds positive and 5 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 275 | 65.5243 | 0.2383 | 5/6 | 16.6491 | 0.1046 | 2.277 | 0.042951252608096235 | pass |
| NEARUSDT | 248 | 102.5089 | 0.4133 | 5/6 | 8.268 | 0.1628 | 2.538 | 0.0027406031536879997 | pass |
| ATOMUSDT | 263 | 23.6981 | 0.0901 | 4/6 | 31.5305 | 0.0413 | 2.181 | 0.23637695217111043 | pass |
| FILUSDT | 258 | 80.0301 | 0.3102 | 5/6 | 20.6384 | 0.1537 | 2.019 | 0.03235781064327554 | pass |
| TRXUSDT | 299 | -3.9452 | -0.0132 | 1/6 | 35.6201 | -0.0071 | 1.847 | 0.5418451444323257 | fail |
| ETCUSDT | 254 | 82.8022 | 0.326 | 4/6 | 22.4541 | 0.1558 | 2.092 | 0.018518069670186196 | pass |
| **pooled** | 1597 | 350.617 | 0.2195 | 5/6 | 46.9633 (seq) | - | - | 8.879417286321465e-05 | - |

Holm survivors (alpha 0.05): ['NEARUSDT']

