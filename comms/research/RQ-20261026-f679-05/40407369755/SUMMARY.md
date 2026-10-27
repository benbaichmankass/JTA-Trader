# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm LONG passes (pooled net_r 181.3837); 1 of 2 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 4 of 12 powered cells pass (< 6): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 45 | 15.6156 | 0.347 | 5/6 | 7.3646 | 0.0094 | 37.089 | 0.14518111828189978 | pass |
| ETHUSDT | 44 | 9.1787 | 0.2086 | 3/6 | 10.7864 | 0.0055 | 37.682 | 0.22425499471751326 | fail |
| SOLUSDT | 41 | 3.3265 | 0.0811 | 3/6 | 8.9755 | 0.0021 | 38.707 | 0.3649416157976077 | fail |
| XRPUSDT | 39 | 10.9612 | 0.2811 | 2/6 | 12.199 | 0.0077 | 36.487 | 0.24120591203905822 | fail |
| ADAUSDT | 41 | 4.6016 | 0.1122 | 4/6 | 7.7063 | 0.0028 | 39.878 | 0.3068971801404625 | pass |
| AVAXUSDT | 38 | 18.1684 | 0.4781 | 4/6 | 5.5615 | 0.0114 | 41.895 | 0.09531153349949661 | pass |
| BNBUSDT | 42 | 17.0004 | 0.4048 | 4/6 | 5.7728 | 0.0108 | 37.619 | 0.16100844376272389 | pass |
| DOGEUSDT | 40 | 29.6056 | 0.7401 | 3/6 | 11.0581 | 0.0202 | 36.575 | 0.12239670215257048 | fail |
| LINKUSDT | 47 | -9.4387 | -0.2008 | 2/6 | 15.0637 | -0.0057 | 35.043 | 0.8231431289960954 | fail |
| LTCUSDT | 41 | -6.2541 | -0.1525 | 3/6 | 13.394 | -0.0041 | 37.512 | 0.8155430371499528 | fail |
| BCHUSDT | 43 | -9.7912 | -0.2277 | 1/6 | 14.6987 | -0.0064 | 35.698 | 0.8678946867599591 | fail |
| DOTUSDT | 30 | 6.8617 | 0.2287 | 3/6 | 7.6622 | 0.0041 | 56.2 | 0.2600605570482749 | fail |
| **pooled** | 491 | 89.8351 | 0.183 | 4/6 | 57.7646 (seq) | - | - | 0.027865127137270504 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- pass -- pooled net_r 181.3837 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6); beats the baseline by 0.2489 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 37 | 18.2469 | 0.4932 | 4/6 | 7.9951 | 0.0158 | 31.27 | 0.10986558425415022 | pass |
| ETHUSDT | 36 | 13.8807 | 0.3856 | 4/6 | 6.3174 | 0.0143 | 27.056 | 0.11690436917543123 | pass |
| SOLUSDT | 32 | 25.2031 | 0.7876 | 3/6 | 4.6388 | 0.0313 | 25.188 | 0.03847056973262257 | fail |
| XRPUSDT | 36 | 18.5398 | 0.515 | 4/6 | 8.7593 | 0.0348 | 14.806 | 0.10815739086243914 | pass |
| ADAUSDT | 36 | 5.9433 | 0.1651 | 3/6 | 6.9969 | 0.0077 | 21.361 | 0.2592000125873079 | fail |
| AVAXUSDT | 34 | 22.4716 | 0.6609 | 4/6 | 7.7065 | 0.0322 | 20.5 | 0.12415504414376244 | pass |
| BNBUSDT | 32 | 33.5816 | 1.0494 | 6/6 | 2.2165 | 0.0343 | 30.594 | 0.025227247460128957 | pass |
| DOGEUSDT | 32 | 46.1321 | 1.4416 | 4/6 | 4.2292 | 0.1131 | 12.75 | 0.03884133020830305 | pass |
| LINKUSDT | 41 | -2.2345 | -0.0545 | 3/6 | 9.5811 | -0.0026 | 21.049 | 0.587493568717734 | fail |
| LTCUSDT | 35 | 1.683 | 0.0481 | 3/6 | 10.5437 | 0.0023 | 21.171 | 0.42400891412554065 | fail |
| BCHUSDT | 35 | -1.4876 | -0.0425 | 3/6 | 8.671 | -0.002 | 21.257 | 0.5710295289901537 | fail |
| DOTUSDT | 34 | -0.5761 | -0.0169 | 2/6 | 10.9541 | -0.0009 | 19.029 | 0.5224649992578535 | fail |
| **pooled** | 420 | 181.3837 | 0.4319 | 4/6 | 41.0335 (seq) | - | - | 0.00015021582448361383 | - |

Holm survivors (alpha 0.05): []

