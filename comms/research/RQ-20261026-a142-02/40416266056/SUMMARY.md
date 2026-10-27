# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: D20: pooled net_r 32.5697 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); TR8: pooled passes but only 1 of 6 powered cells pass (< 3): one symbol's edge. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline D20 with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `D20` (baseline) -- pass -- pooled net_r 32.5697 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 41 | 19.3842 | 0.4728 | 4/6 | 5.7728 | 0.0116 | 40.902 | 0.13051046623958834 | pass |
| DOGEUSDT | 40 | 29.6056 | 0.7401 | 4/6 | 11.0581 | 0.0202 | 36.575 | 0.12239670215257048 | pass |
| LINKUSDT | 48 | -8.623 | -0.1796 | 2/6 | 15.0637 | -0.0049 | 36.667 | 0.7882649789752034 | fail |
| LTCUSDT | 40 | -7.5899 | -0.1897 | 2/6 | 13.394 | -0.0046 | 41.7 | 0.8723847120877928 | fail |
| BCHUSDT | 43 | -7.0688 | -0.1644 | 1/6 | 14.6987 | -0.0042 | 39.372 | 0.7821280215925688 | fail |
| DOTUSDT | 30 | 6.8617 | 0.2287 | 4/6 | 7.6622 | 0.0041 | 56.2 | 0.2600605570482749 | pass |
| **pooled** | 242 | 32.5697 | 0.1346 | 4/6 | 45.4948 (seq) | - | - | 0.18106956401383628 | - |

Holm survivors (alpha 0.05): []

## arm `TR8` (candidate) -- fail -- pooled passes but only 1 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 33 | 29.6811 | 0.8994 | 3/6 | 8.6234 | 0.0157 | 57.152 | 0.16835697162374869 | fail |
| DOGEUSDT | 33 | 16.9925 | 0.5149 | 3/6 | 14.5497 | 0.0109 | 47.03 | 0.24314295644092615 | fail |
| LINKUSDT | 35 | -2.8754 | -0.0822 | 2/6 | 17.5412 | -0.0016 | 52.571 | 0.560873038734143 | fail |
| LTCUSDT | 30 | 6.1805 | 0.206 | 4/6 | 7.9346 | 0.0033 | 62.367 | 0.2590387566536571 | pass |
| BCHUSDT | 38 | -0.8625 | -0.0227 | 3/6 | 14.1635 | -0.0005 | 46.0 | 0.5219860774978512 | fail |
| DOTUSDT | 26 | 5.9914 | 0.2304 | 3/6 | 7.8074 | 0.0035 | 66.654 | 0.27515763108328495 | fail |
| **pooled** | 195 | 55.1075 | 0.2826 | 4/6 | 45.8554 (seq) | - | - | 0.12334053604386574 | - |

Holm survivors (alpha 0.05): []

