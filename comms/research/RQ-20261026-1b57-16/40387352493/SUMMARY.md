# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: D20: pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3); L100: pooled passes but only 0 of 3 powered cells pass (< 2): one symbol's edge. Thresholds: n_floor 15, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline D20 with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `D20` (baseline) -- pass -- pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

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

## arm `L100` (candidate) -- fail -- pooled passes but only 0 of 3 powered cells pass (< 2): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 18 | 5.1894 | 0.2883 | 2/6 | 4.0053 | 0.0072 | 40.0 | 0.2626763224064703 | fail |
| ETHUSDT | 18 | 9.8275 | 0.546 | 3/6 | 2.4059 | 0.017 | 32.056 | 0.14590452281253657 | fail |
| SOLUSDT | 13 | 12.8197 | 0.9861 | 2/6 | 2.4739 | 0.0335 | 29.462 | 0.08444290926514653 | indeterminate |
| XRPUSDT | 12 | 13.5716 | 1.131 | 3/6 | 3.4338 | 0.1028 | 11.0 | 0.10406527523660958 | indeterminate |
| ADAUSDT | 16 | 10.0287 | 0.6268 | 3/6 | 3.4175 | 0.0313 | 20.0 | 0.13732264116469467 | fail |
| AVAXUSDT | 12 | 13.3183 | 1.1099 | 3/6 | 2.2592 | 0.0516 | 21.5 | 0.14128392440137205 | indeterminate |
| **pooled** | 89 | 64.755 | 0.7276 | 4/6 | 9.5462 (seq) | - | - | 0.002761804722236456 | - |

Holm survivors (alpha 0.05): []

