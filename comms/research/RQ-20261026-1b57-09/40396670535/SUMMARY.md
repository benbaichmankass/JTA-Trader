# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 72.7968); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 8 majority 5, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 72.7968 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 72 | 5.8504 | 0.0813 | 3/8 | 7.1319 | 0.0575 | 1.414 | 0.2997529049979478 | fail |
| DOGEUSDT | 75 | 5.0781 | 0.0677 | 4/8 | 8.1623 | 0.0478 | 1.418 | 0.32370639982546995 | fail |
| LINKUSDT | 65 | 8.4205 | 0.1295 | 5/8 | 6.0868 | 0.0676 | 1.915 | 0.22117737287339695 | pass |
| LTCUSDT | 72 | 18.6887 | 0.2596 | 6/8 | 5.1501 | 0.1168 | 2.222 | 0.07994280992804337 | pass |
| BCHUSDT | 80 | 21.1796 | 0.2647 | 5/8 | 6.9877 | 0.1368 | 1.935 | 0.08787330581340752 | pass |
| DOTUSDT | 71 | 13.5787 | 0.1912 | 5/8 | 3.4584 | 0.0867 | 2.207 | 0.1084863167474166 | pass |
| **pooled** | 435 | 72.7968 | 0.1673 | 5/8 | 26.4458 (seq) | - | - | 0.007505978174420608 | - |

Holm survivors (alpha 0.05): []

