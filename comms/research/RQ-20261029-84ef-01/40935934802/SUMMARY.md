# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: LONG: pooled net_r 180.62 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6); LONG_TR8: pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge; LONG_TS60: net_r/trade 0.3872 beats the baseline's 0.43 by -0.0428 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline LONG with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `LONG` (baseline) -- pass -- pooled net_r 180.62 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 37 | 18.093 | 0.489 | 4/6 | 8.0353 | 0.0156 | 31.27 | 0.11166384521515887 | pass |
| ETHUSDT | 36 | 13.7592 | 0.3822 | 4/6 | 6.363 | 0.0141 | 27.056 | 0.11887217887699197 | pass |
| SOLUSDT | 32 | 25.1272 | 0.7852 | 3/6 | 4.6543 | 0.0312 | 25.188 | 0.0388719590685349 | fail |
| XRPUSDT | 36 | 18.4351 | 0.5121 | 4/6 | 8.8089 | 0.0346 | 14.806 | 0.10937995846986182 | pass |
| ADAUSDT | 36 | 5.8498 | 0.1625 | 3/6 | 7.0232 | 0.0076 | 21.361 | 0.2624361029921003 | fail |
| AVAXUSDT | 34 | 22.3906 | 0.6585 | 4/6 | 7.7422 | 0.0321 | 20.5 | 0.1249544044656637 | pass |
| BNBUSDT | 32 | 33.4479 | 1.0452 | 6/6 | 2.2252 | 0.0342 | 30.594 | 0.025644678682121353 | pass |
| DOGEUSDT | 32 | 46.1321 | 1.4416 | 4/6 | 4.2292 | 0.1131 | 12.75 | 0.03884133020830305 | pass |
| LINKUSDT | 41 | -2.2345 | -0.0545 | 3/6 | 9.5811 | -0.0026 | 21.049 | 0.587493568717734 | fail |
| LTCUSDT | 35 | 1.683 | 0.0481 | 3/6 | 10.5437 | 0.0023 | 21.171 | 0.42400891412554065 | fail |
| BCHUSDT | 35 | -1.4876 | -0.0425 | 3/6 | 8.671 | -0.002 | 21.257 | 0.5710295289901537 | fail |
| DOTUSDT | 34 | -0.5761 | -0.0169 | 2/6 | 10.9541 | -0.0009 | 19.029 | 0.5224649992578535 | fail |
| **pooled** | 420 | 180.62 | 0.43 | 4/6 | 41.1119 (seq) | - | - | 0.0001587595493004396 | - |

Holm survivors (alpha 0.05): []

## arm `LONG_TR8` (candidate) -- fail -- pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 26 | 24.6122 | 0.9466 | 5/6 | 6.9802 | 0.0171 | 55.269 | 0.0723943218436523 | pass |
| ETHUSDT | 30 | 9.9773 | 0.3326 | 3/6 | 5.4927 | 0.0083 | 40.267 | 0.17916139179388474 | fail |
| SOLUSDT | 24 | 36.3469 | 1.5145 | 3/6 | 3.7042 | 0.0339 | 44.667 | 0.01852090148128726 | fail |
| XRPUSDT | 30 | 37.4918 | 1.2497 | 3/6 | 6.2183 | 0.0509 | 24.567 | 0.04526700494299078 | fail |
| ADAUSDT | 30 | 31.4884 | 1.0496 | 5/6 | 6.5052 | 0.0355 | 29.567 | 0.09545867170541883 | pass |
| AVAXUSDT | 30 | 37.5279 | 1.2509 | 4/6 | 4.1876 | 0.0508 | 24.633 | 0.05430200090483839 | pass |
| BNBUSDT | 24 | 32.9805 | 1.3742 | 5/6 | 4.1564 | 0.0263 | 52.167 | 0.04866460800177199 | pass |
| DOGEUSDT | 30 | 33.9166 | 1.1306 | 4/6 | 4.8919 | 0.0579 | 19.533 | 0.08769964645349315 | pass |
| LINKUSDT | 36 | 0.4818 | 0.0134 | 3/6 | 11.7387 | 0.0005 | 28.083 | 0.4871286263191396 | fail |
| LTCUSDT | 30 | 1.4466 | 0.0482 | 2/6 | 11.8737 | 0.0015 | 31.667 | 0.44249672507095084 | fail |
| BCHUSDT | 28 | 5.1903 | 0.1854 | 3/6 | 6.3562 | 0.0053 | 35.286 | 0.33179909936313834 | fail |
| DOTUSDT | 31 | 4.3277 | 0.1396 | 3/6 | 8.8437 | 0.0053 | 26.161 | 0.37241656271822254 | fail |
| **pooled** | 349 | 255.7889 | 0.7329 | 5/6 | 42.4908 (seq) | - | - | 1.8848151587556902e-05 | - |

Holm survivors (alpha 0.05): []

## arm `LONG_TS60` (candidate) -- fail -- net_r/trade 0.3872 beats the baseline's 0.43 by -0.0428 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 41 | 16.9893 | 0.4144 | 4/6 | 8.0353 | 0.0161 | 25.732 | 0.12066781097597834 | pass |
| ETHUSDT | 40 | 9.7342 | 0.2434 | 4/6 | 6.363 | 0.0105 | 23.275 | 0.18598436912808974 | pass |
| SOLUSDT | 34 | 24.1536 | 0.7104 | 3/6 | 5.1932 | 0.0302 | 23.5 | 0.0488065519631234 | fail |
| XRPUSDT | 37 | 15.1551 | 0.4096 | 3/6 | 12.0889 | 0.0275 | 14.892 | 0.15403613864392474 | fail |
| ADAUSDT | 37 | 6.1917 | 0.1673 | 3/6 | 7.5675 | 0.0082 | 20.459 | 0.2506207272520151 | fail |
| AVAXUSDT | 35 | 22.0514 | 0.63 | 4/6 | 7.7422 | 0.0317 | 19.857 | 0.12786067176627425 | pass |
| BNBUSDT | 36 | 26.9396 | 0.7483 | 6/6 | 2.3812 | 0.0298 | 25.083 | 0.016467824229559707 | pass |
| DOGEUSDT | 32 | 46.1321 | 1.4416 | 4/6 | 4.2292 | 0.1131 | 12.75 | 0.03884133020830305 | pass |
| LINKUSDT | 41 | -2.2345 | -0.0545 | 3/6 | 9.5811 | -0.0026 | 21.049 | 0.587493568717734 | fail |
| LTCUSDT | 35 | 2.3288 | 0.0665 | 3/6 | 9.9869 | 0.0032 | 21.086 | 0.39472575036930074 | fail |
| BCHUSDT | 36 | 1.3852 | 0.0385 | 4/6 | 8.671 | 0.0021 | 18.556 | 0.43511973101100876 | pass |
| DOTUSDT | 34 | 0.7619 | 0.0224 | 2/6 | 10.5506 | 0.0012 | 18.353 | 0.470391666513239 | fail |
| **pooled** | 438 | 169.5886 | 0.3872 | 4/6 | 41.1119 (seq) | - | - | 0.00024274586452244644 | - |

Holm survivors (alpha 0.05): []

