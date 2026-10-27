# Stage-0 (synthetic leg) -- trend 1h -- pass

PASS: arm B passes (pooled net_r 450.7171); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 450.7171 > 0 with 6 folds positive and 6 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 993 | 119.9228 | 0.1208 | 5/6 | 19.1007 | 0.1877 | 0.643 | 0.0014394227106887178 | pass |
| NEARUSDT | 974 | 47.7837 | 0.0491 | 4/6 | 22.2933 | 0.0741 | 0.662 | 0.09370286785645676 | pass |
| ATOMUSDT | 1023 | 38.9752 | 0.0381 | 4/6 | 30.0901 | 0.0582 | 0.654 | 0.1687689212914379 | pass |
| FILUSDT | 972 | 81.5323 | 0.0839 | 4/6 | 27.1872 | 0.1435 | 0.584 | 0.025657066901652842 | pass |
| TRXUSDT | 1120 | 100.9151 | 0.0901 | 4/6 | 27.282 | 0.1504 | 0.599 | 0.014246679418314609 | pass |
| ETCUSDT | 1061 | 61.5866 | 0.058 | 5/6 | 31.5935 | 0.101 | 0.575 | 0.07319621952820538 | pass |
| **pooled** | 6143 | 450.7171 | 0.0734 | 6/6 | 62.192 (seq) | - | - | 4.236254083425585e-06 | - |

Holm survivors (alpha 0.05): ['AVAXUSDT']

