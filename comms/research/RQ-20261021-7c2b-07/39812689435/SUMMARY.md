# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 72 | 5.8504 | 0.0813 | 2/6 | 7.1319 | 0.0575 | 1.414 | 0.2997529049979478 | fail |
| DOGEUSDT | 74 | 5.5619 | 0.0752 | 3/6 | 8.1623 | 0.053 | 1.419 | 0.3080343643506521 | fail |
| LINKUSDT | 65 | 8.4205 | 0.1295 | 3/6 | 6.0868 | 0.0676 | 1.915 | 0.22117737287339695 | fail |
| LTCUSDT | 72 | 18.6887 | 0.2596 | 4/6 | 5.1501 | 0.1168 | 2.222 | 0.07994280992804337 | pass |
| BCHUSDT | 80 | 21.1796 | 0.2647 | 6/6 | 6.9877 | 0.1368 | 1.935 | 0.08787330581340752 | pass |
| DOTUSDT | 71 | 13.5787 | 0.1912 | 5/6 | 3.4584 | 0.0867 | 2.207 | 0.1084863167474166 | pass |
| **pooled** | 434 | 73.2806 | 0.1688 | 3/6 | 26.4458 (seq) | - | - | 0.007168705932078597 | - |

Holm survivors (alpha 0.05): []

