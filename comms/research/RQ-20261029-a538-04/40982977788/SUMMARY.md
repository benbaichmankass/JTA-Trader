# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: LONG: pooled net_r 180.62 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6); BOTH: net_r/trade 0.1813 beats the baseline's 0.43 by -0.2487 < the 0.1 materiality bar; SHORT: net_r/trade -0.2297 beats the baseline's 0.43 by -0.6597 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline LONG with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

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

## arm `BOTH` (candidate) -- fail -- net_r/trade 0.1813 beats the baseline's 0.43 by -0.2487 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 45 | 15.4274 | 0.3428 | 5/6 | 7.3872 | 0.0092 | 37.089 | 0.14796444351419635 | pass |
| ETHUSDT | 44 | 9.0433 | 0.2055 | 3/6 | 10.8691 | 0.0055 | 37.682 | 0.22754331399045713 | fail |
| SOLUSDT | 41 | 3.2341 | 0.0789 | 3/6 | 9.0196 | 0.002 | 38.707 | 0.3685498316998903 | fail |
| XRPUSDT | 39 | 10.8565 | 0.2784 | 2/6 | 12.2383 | 0.0076 | 36.487 | 0.24325121064731242 | fail |
| ADAUSDT | 41 | 4.5071 | 0.1099 | 4/6 | 7.7226 | 0.0028 | 39.878 | 0.3105145209713287 | pass |
| AVAXUSDT | 38 | 18.094 | 0.4762 | 4/6 | 5.5755 | 0.0114 | 41.895 | 0.09617219669135468 | pass |
| BNBUSDT | 42 | 16.8529 | 0.4013 | 4/6 | 5.8133 | 0.0107 | 37.619 | 0.16305345733843996 | pass |
| DOGEUSDT | 40 | 29.6056 | 0.7401 | 3/6 | 11.0581 | 0.0202 | 36.575 | 0.12239670215257048 | fail |
| LINKUSDT | 47 | -9.4387 | -0.2008 | 2/6 | 15.0637 | -0.0057 | 35.043 | 0.8231431289960954 | fail |
| LTCUSDT | 41 | -6.2541 | -0.1525 | 3/6 | 13.394 | -0.0041 | 37.512 | 0.8155430371499528 | fail |
| BCHUSDT | 43 | -9.7912 | -0.2277 | 1/6 | 14.6987 | -0.0064 | 35.698 | 0.8678946867599591 | fail |
| DOTUSDT | 30 | 6.8617 | 0.2287 | 3/6 | 7.6622 | 0.0041 | 56.2 | 0.2600605570482749 | fail |
| **pooled** | 491 | 88.9995 | 0.1813 | 4/6 | 58.2085 (seq) | - | - | 0.029001882319090407 | - |

Holm survivors (alpha 0.05): []

## arm `SHORT` (candidate) -- fail -- net_r/trade -0.2297 beats the baseline's 0.43 by -0.6597 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 23 | -7.9498 | -0.3456 | 2/6 | 11.8198 | -0.0076 | 45.304 | 0.9027391929506949 | fail |
| ETHUSDT | 21 | -5.2948 | -0.2521 | 2/6 | 8.9964 | -0.0045 | 55.571 | 0.8166581306237413 | fail |
| SOLUSDT | 20 | -8.5611 | -0.4281 | 1/6 | 9.7099 | -0.0076 | 56.35 | 0.9580293601190215 | fail |
| XRPUSDT | 19 | -8.7249 | -0.4592 | 2/6 | 9.437 | -0.0067 | 68.579 | 0.9857265455483235 | indeterminate |
| ADAUSDT | 17 | 0.4148 | 0.0244 | 4/6 | 3.992 | 0.0003 | 73.941 | 0.4711256165451372 | indeterminate |
| AVAXUSDT | 16 | 2.4222 | 0.1514 | 4/6 | 3.1861 | 0.0019 | 81.812 | 0.32827931251271425 | indeterminate |
| BNBUSDT | 20 | -6.1568 | -0.3078 | 3/6 | 7.1954 | -0.0063 | 49.1 | 0.9010463214682494 | fail |
| DOGEUSDT | 18 | -4.534 | -0.2519 | 3/6 | 6.777 | -0.0033 | 76.556 | 0.8318996133593991 | indeterminate |
| LINKUSDT | 19 | -5.6426 | -0.297 | 2/6 | 8.2948 | -0.0041 | 72.947 | 0.8742372825826545 | indeterminate |
| LTCUSDT | 15 | -1.7704 | -0.118 | 2/6 | 4.8458 | -0.0013 | 90.733 | 0.6460444833022183 | indeterminate |
| BCHUSDT | 21 | -4.1666 | -0.1984 | 2/6 | 10.8044 | -0.0034 | 58.286 | 0.7405329528565425 | fail |
| DOTUSDT | 16 | -1.7095 | -0.1068 | 3/6 | 4.1163 | -0.0012 | 91.25 | 0.631317424947981 | indeterminate |
| **pooled** | 225 | -51.6735 | -0.2297 | 2/6 | 74.2282 (seq) | - | - | 0.9982572399244832 | - |

Holm survivors (alpha 0.05): []

