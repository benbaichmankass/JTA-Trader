# Stage-0 (synthetic leg) -- pullback 4h -- fail

FAIL: B: pooled net_r 24.2865 > 0 with 4 folds positive and 1 of 2 powered cells pass (breadth floor 1). Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 24.2865 > 0 with 4 folds positive and 1 of 2 powered cells pass (breadth floor 1)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 195 | -2.8638 | -0.0147 | 4/6 | 27.4859 | -0.0016 | 9.249 | 0.5438224227627824 | fail |
| SOLUSDT | 192 | 27.1487 | 0.1414 | 4/6 | 20.659 | 0.0153 | 9.213 | 0.15856560315140672 | pass |
| **pooled** | 387 | 24.2865 | 0.0628 | 4/6 | 30.4901 (seq) | - | - | 0.2587995967568447 | - |

Holm survivors (alpha 0.05): []

