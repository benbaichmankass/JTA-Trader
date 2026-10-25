# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r 92.4085 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); DIA: net_r/trade 0.0632 beats the baseline's 0.0383 by 0.0249 < the 0.05 materiality bar; DIAB: net_r/trade 0.0665 beats the baseline's 0.0383 by 0.0282 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 92.4085 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 405 | 44.2427 | 0.1092 | 5/6 | 16.6769 | 0.0257 | 4.252 | 0.12252496614617409 | pass |
| NEARUSDT | 397 | -3.1837 | -0.008 | 3/6 | 31.5965 | -0.0019 | 4.207 | 0.5388194609522874 | fail |
| ATOMUSDT | 402 | 21.6155 | 0.0538 | 3/6 | 31.5933 | 0.0119 | 4.537 | 0.29244302443533166 | fail |
| FILUSDT | 389 | 12.4429 | 0.032 | 4/6 | 85.2986 | 0.0074 | 4.295 | 0.38619585775085447 | pass |
| TRXUSDT | 397 | 49.98 | 0.1259 | 4/6 | 24.9551 | 0.0273 | 4.613 | 0.09127958111800544 | pass |
| ETCUSDT | 424 | -32.6894 | -0.0771 | 3/6 | 69.8307 | -0.0178 | 4.332 | 0.8297422227718592 | fail |
| **pooled** | 2414 | 92.4085 | 0.0383 | 4/6 | 118.1288 (seq) | - | - | 0.1580025041405949 | - |

Holm survivors (alpha 0.05): []

## arm `DIA` (candidate) -- fail -- net_r/trade 0.0632 beats the baseline's 0.0383 by 0.0249 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 326 | 62.2676 | 0.191 | 5/6 | 16.1178 | 0.0442 | 4.323 | 0.04725629369424267 | pass |
| NEARUSDT | 311 | 1.5581 | 0.005 | 4/6 | 30.7178 | 0.0012 | 4.298 | 0.47807695194175215 | pass |
| ATOMUSDT | 323 | -1.2548 | -0.0039 | 3/6 | 32.7957 | -0.0008 | 4.613 | 0.5165572760971071 | fail |
| FILUSDT | 315 | 26.5854 | 0.0844 | 3/6 | 50.3604 | 0.0192 | 4.387 | 0.2567042392051019 | fail |
| TRXUSDT | 309 | 26.544 | 0.0859 | 4/6 | 22.9811 | 0.0188 | 4.569 | 0.21096557738931881 | pass |
| ETCUSDT | 328 | 5.2266 | 0.0159 | 4/6 | 44.467 | 0.0034 | 4.655 | 0.4363603993895957 | pass |
| **pooled** | 1912 | 120.9267 | 0.0632 | 4/6 | 96.2864 (seq) | - | - | 0.07263391567999183 | - |

Holm survivors (alpha 0.05): []

## arm `DIAB` (candidate) -- fail -- net_r/trade 0.0665 beats the baseline's 0.0383 by 0.0282 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 360 | 48.9617 | 0.136 | 5/6 | 15.0503 | 0.0379 | 3.588 | 0.08777129734484945 | pass |
| NEARUSDT | 343 | 2.0644 | 0.006 | 4/6 | 25.4886 | 0.0016 | 3.66 | 0.4699017716399757 | pass |
| ATOMUSDT | 352 | 2.5738 | 0.0073 | 2/6 | 30.8263 | 0.0018 | 3.976 | 0.46539969439323103 | fail |
| FILUSDT | 347 | 37.6609 | 0.1085 | 3/6 | 41.4529 | 0.0288 | 3.767 | 0.1727355967850056 | fail |
| TRXUSDT | 333 | 35.3913 | 0.1063 | 4/6 | 20.2955 | 0.027 | 3.942 | 0.13740320895352587 | pass |
| ETCUSDT | 359 | 12.6384 | 0.0352 | 4/6 | 39.1104 | 0.0088 | 3.991 | 0.34651357302617947 | pass |
| **pooled** | 2094 | 139.2906 | 0.0665 | 5/6 | 95.7774 (seq) | - | - | 0.04298423250200223 | - |

Holm survivors (alpha 0.05): []

