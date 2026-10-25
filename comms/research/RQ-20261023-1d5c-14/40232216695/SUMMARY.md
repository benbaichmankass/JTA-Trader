# Stage-0 (synthetic leg) -- squeeze 4h -- indeterminate

INDETERMINATE: B: pooled net_r 62.617 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); BE1: net_r/trade 0.0397 beats the baseline's 0.0381 by 0.0016 < the 0.05 materiality bar; WIDE: only 0 powered cell(s) (< 2): breadth cannot be read; STOP35: net_r/trade 0.0247 beats the baseline's 0.0381 by -0.0134 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 62.617 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 272 | -15.745 | -0.0579 | 1/6 | 27.5432 | -0.0161 | 3.594 | 0.790074609624344 | fail |
| NEARUSDT | 274 | 14.5245 | 0.053 | 4/6 | 15.8249 | 0.014 | 3.796 | 0.25332606696380194 | pass |
| ATOMUSDT | 292 | 9.0123 | 0.0309 | 3/6 | 32.2157 | 0.0079 | 3.919 | 0.3436595615730941 | fail |
| FILUSDT | 262 | 50.562 | 0.193 | 4/6 | 15.3906 | 0.0489 | 3.944 | 0.019415772215669116 | pass |
| TRXUSDT | 241 | 19.2802 | 0.08 | 4/6 | 15.8991 | 0.0212 | 3.765 | 0.16830933387757963 | pass |
| ETCUSDT | 304 | -15.0186 | -0.0494 | 3/6 | 34.1451 | -0.0135 | 3.648 | 0.7617858877493817 | fail |
| **pooled** | 1645 | 62.617 | 0.0381 | 4/6 | 43.1417 (seq) | - | - | 0.11834765322204172 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0397 beats the baseline's 0.0381 by 0.0016 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 277 | -16.9855 | -0.0613 | 1/6 | 25.932 | -0.0175 | 3.504 | 0.8125090122864027 | fail |
| NEARUSDT | 275 | 8.5828 | 0.0312 | 4/6 | 15.9496 | 0.0083 | 3.741 | 0.34080191407753846 | pass |
| ATOMUSDT | 295 | 7.8814 | 0.0267 | 4/6 | 30.6516 | 0.007 | 3.838 | 0.3609912458248347 | pass |
| FILUSDT | 268 | 50.6614 | 0.189 | 3/6 | 12.1742 | 0.0499 | 3.787 | 0.021330528706211938 | fail |
| TRXUSDT | 250 | 22.8569 | 0.0914 | 4/6 | 14.4384 | 0.0252 | 3.631 | 0.13166229737573726 | pass |
| ETCUSDT | 308 | -6.58 | -0.0214 | 2/6 | 28.8429 | -0.0061 | 3.526 | 0.6216264589749018 | fail |
| **pooled** | 1673 | 66.4176 | 0.0397 | 4/6 | 44.7132 (seq) | - | - | 0.10394327686797372 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 21 | 1.4072 | 0.067 | 1/6 | 8.004 | 0.0241 | 2.778 | 0.43085487094364294 | indeterminate |
| NEARUSDT | 22 | -3.5814 | -0.1628 | 2/6 | 9.6556 | -0.0528 | 3.083 | 0.7377034458326002 | indeterminate |
| ATOMUSDT | 15 | -7.4808 | -0.4987 | 1/6 | 8.1614 | -0.1626 | 3.067 | 0.9677796660893214 | indeterminate |
| FILUSDT | 28 | -6.9551 | -0.2484 | 2/6 | 9.9708 | -0.0873 | 2.845 | 0.8704866960835492 | indeterminate |
| TRXUSDT | 22 | 10.4004 | 0.4727 | 4/6 | 2.6227 | 0.1193 | 3.962 | 0.1172823685152678 | indeterminate |
| ETCUSDT | 36 | 11.7187 | 0.3255 | 4/6 | 5.508 | 0.1258 | 2.588 | 0.10922331083825326 | indeterminate |
| **pooled** | 144 | 5.5096 | 0.0383 | 5/6 | 17.0026 (seq) | - | - | 0.37713037341253947 | - |

Holm survivors (alpha 0.05): []

## arm `STOP35` (candidate) -- fail -- net_r/trade 0.0247 beats the baseline's 0.0381 by -0.0134 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 256 | -14.5735 | -0.0569 | 1/6 | 23.8476 | -0.0145 | 3.933 | 0.8459615179417408 | fail |
| NEARUSDT | 256 | 13.5047 | 0.0528 | 3/6 | 13.4188 | 0.0123 | 4.28 | 0.20071202881711486 | fail |
| ATOMUSDT | 280 | 1.7758 | 0.0063 | 4/6 | 21.7618 | 0.0015 | 4.187 | 0.456965667816708 | pass |
| FILUSDT | 249 | 33.1472 | 0.1331 | 4/6 | 11.6611 | 0.0311 | 4.28 | 0.025264900863521057 | pass |
| TRXUSDT | 235 | 5.201 | 0.0221 | 4/6 | 14.7267 | 0.0057 | 3.867 | 0.3627048689783153 | pass |
| ETCUSDT | 285 | -0.4986 | -0.0017 | 2/6 | 17.1285 | -0.0004 | 3.984 | 0.5125916352600782 | fail |
| **pooled** | 1561 | 38.5568 | 0.0247 | 4/6 | 30.1803 (seq) | - | - | 0.1585271126725229 | - |

Holm survivors (alpha 0.05): []

