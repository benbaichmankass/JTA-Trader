# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: B: pooled net_r <= 0 or folds short; LONG: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 42 | 17.0004 | 0.4048 | 4/6 | 5.7728 | 0.0108 | 37.619 | 0.16100844376272389 | pass |
| DOGEUSDT | 40 | 29.6056 | 0.7401 | 4/6 | 11.0581 | 0.0202 | 36.575 | 0.12239670215257048 | pass |
| LINKUSDT | 47 | -9.4387 | -0.2008 | 2/6 | 15.0637 | -0.0057 | 35.043 | 0.8231431289960954 | fail |
| LTCUSDT | 41 | -6.9064 | -0.1684 | 3/6 | 13.394 | -0.0045 | 37.39 | 0.8396868210849646 | fail |
| BCHUSDT | 43 | -9.7912 | -0.2277 | 1/6 | 14.6987 | -0.0064 | 35.698 | 0.8678946867599591 | fail |
| DOTUSDT | 30 | 6.8617 | 0.2287 | 4/6 | 7.6622 | 0.0041 | 56.2 | 0.2600605570482749 | pass |
| **pooled** | 243 | 27.3313 | 0.1125 | 3/6 | 45.4948 (seq) | - | - | 0.22077918890592219 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 32 | 33.5816 | 1.0494 | 6/6 | 2.2165 | 0.0343 | 30.594 | 0.025227247460128957 | pass |
| DOGEUSDT | 32 | 46.1321 | 1.4416 | 4/6 | 4.2292 | 0.1131 | 12.75 | 0.03884133020830305 | pass |
| LINKUSDT | 41 | -2.2345 | -0.0545 | 3/6 | 9.5811 | -0.0026 | 21.049 | 0.587493568717734 | fail |
| LTCUSDT | 35 | 1.683 | 0.0481 | 3/6 | 10.5437 | 0.0023 | 21.171 | 0.42400891412554065 | fail |
| BCHUSDT | 35 | -1.4876 | -0.0425 | 3/6 | 8.671 | -0.002 | 21.257 | 0.5710295289901537 | fail |
| DOTUSDT | 34 | -0.5761 | -0.0169 | 2/6 | 10.9541 | -0.0009 | 19.029 | 0.5224649992578535 | fail |
| **pooled** | 209 | 77.0986 | 0.3689 | 3/6 | 20.5286 (seq) | - | - | 0.016856143142498704 | - |

Holm survivors (alpha 0.05): []

