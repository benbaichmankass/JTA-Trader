# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: L20: pooled net_r 180.62 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6); L30: net_r/trade 0.4213 beats the baseline's 0.43 by -0.0087 < the 0.1 materiality bar; L55: net_r/trade 0.4794 beats the baseline's 0.43 by 0.0494 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline L20 with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `L20` (baseline) -- pass -- pooled net_r 180.62 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6)

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

## arm `L30` (candidate) -- fail -- net_r/trade 0.4213 beats the baseline's 0.43 by -0.0087 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 34 | 12.0521 | 0.3545 | 3/6 | 5.1637 | 0.0116 | 30.588 | 0.18210076128653563 | fail |
| ETHUSDT | 30 | 16.2374 | 0.5412 | 3/6 | 4.2163 | 0.018 | 30.133 | 0.06719887547789416 | fail |
| SOLUSDT | 29 | 23.9188 | 0.8248 | 4/6 | 5.9706 | 0.0365 | 22.586 | 0.06487732559201059 | pass |
| XRPUSDT | 27 | 19.2334 | 0.7123 | 3/6 | 7.1375 | 0.0578 | 12.333 | 0.09034582807930208 | fail |
| ADAUSDT | 29 | 3.3012 | 0.1138 | 4/6 | 7.1128 | 0.0063 | 18.103 | 0.36379395125637337 | pass |
| AVAXUSDT | 26 | 27.5189 | 1.0584 | 3/6 | 6.8167 | 0.0616 | 17.192 | 0.057997579003118416 | fail |
| BNBUSDT | 29 | 23.1414 | 0.798 | 4/6 | 4.2278 | 0.0287 | 27.828 | 0.0772130097365531 | pass |
| DOGEUSDT | 29 | 34.2168 | 1.1799 | 4/6 | 4.7215 | 0.1021 | 11.552 | 0.09194837799762962 | pass |
| LINKUSDT | 33 | -1.5961 | -0.0484 | 3/6 | 7.2628 | -0.0024 | 20.394 | 0.5655754586414699 | fail |
| LTCUSDT | 35 | -6.6469 | -0.1899 | 1/6 | 13.0156 | -0.0125 | 15.171 | 0.8182761045069167 | fail |
| BCHUSDT | 27 | -1.9715 | -0.073 | 3/6 | 8.0851 | -0.0031 | 23.815 | 0.6106875525425319 | fail |
| DOTUSDT | 28 | 0.5671 | 0.0203 | 2/6 | 9.5949 | 0.001 | 19.429 | 0.4752385470623717 | fail |
| **pooled** | 356 | 149.9718 | 0.4213 | 4/6 | 36.8341 (seq) | - | - | 0.0008386085491149697 | - |

Holm survivors (alpha 0.05): []

## arm `L55` (candidate) -- fail -- net_r/trade 0.4794 beats the baseline's 0.43 by 0.0494 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 22 | 11.0516 | 0.5023 | 4/6 | 3.9431 | 0.0135 | 37.091 | 0.1401185288619013 | pass |
| ETHUSDT | 23 | 10.3037 | 0.448 | 3/6 | 3.3379 | 0.0138 | 32.478 | 0.12389063929377664 | fail |
| SOLUSDT | 22 | 17.4969 | 0.7953 | 3/6 | 4.7334 | 0.0365 | 21.773 | 0.06382660095191739 | fail |
| XRPUSDT | 18 | 10.9248 | 0.6069 | 3/6 | 5.488 | 0.0473 | 12.833 | 0.1038113485471433 | indeterminate |
| ADAUSDT | 20 | 7.8205 | 0.391 | 4/6 | 3.9879 | 0.0244 | 16.05 | 0.15291102717555788 | pass |
| AVAXUSDT | 16 | 33.6918 | 2.1057 | 4/6 | 2.255 | 0.1046 | 20.125 | 0.016582185398569916 | indeterminate |
| BNBUSDT | 24 | 17.6996 | 0.7375 | 4/6 | 3.5272 | 0.0304 | 24.292 | 0.13458600574396917 | pass |
| DOGEUSDT | 24 | 33.5154 | 1.3965 | 5/6 | 3.8553 | 0.1566 | 8.917 | 0.09675961163175673 | pass |
| LINKUSDT | 28 | -8.4363 | -0.3013 | 2/6 | 11.4142 | -0.0199 | 15.107 | 0.8211361589009287 | fail |
| LTCUSDT | 27 | -14.1437 | -0.5238 | 1/6 | 16.5411 | -0.0351 | 14.926 | 0.9988557390550861 | fail |
| BCHUSDT | 20 | -6.5386 | -0.3269 | 2/6 | 6.779 | -0.0144 | 22.7 | 0.8879561774812866 | fail |
| DOTUSDT | 15 | 10.7703 | 0.718 | 4/6 | 3.5243 | 0.0288 | 24.933 | 0.13319704838884927 | indeterminate |
| **pooled** | 259 | 124.1561 | 0.4794 | 4/6 | 20.1872 (seq) | - | - | 0.0016944211466833402 | - |

Holm survivors (alpha 0.05): []

