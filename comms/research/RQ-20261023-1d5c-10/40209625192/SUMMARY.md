# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r 122.7959 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3); LONG: net_r/trade -0.0027 beats the baseline's 0.0544 by -0.0571 < the 0.05 materiality bar; ADX: net_r/trade 0.0569 beats the baseline's 0.0544 by 0.0025 < the 0.05 materiality bar; D55: net_r/trade 0.1023 beats the baseline's 0.0544 by 0.0479 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 122.7959 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 379 | 23.9539 | 0.0632 | 5/6 | 19.6465 | 0.0194 | 3.251 | 0.18094964546881953 | pass |
| NEARUSDT | 363 | -3.5071 | -0.0097 | 2/6 | 29.2492 | -0.0027 | 3.544 | 0.5622665859118618 | fail |
| ATOMUSDT | 385 | -0.5162 | -0.0013 | 2/6 | 39.4953 | -0.0004 | 3.541 | 0.5086916952832297 | fail |
| FILUSDT | 361 | 32.2585 | 0.0894 | 4/6 | 19.5755 | 0.0296 | 3.021 | 0.10970589232748795 | pass |
| TRXUSDT | 402 | 33.6258 | 0.0836 | 4/6 | 31.1973 | 0.0284 | 2.946 | 0.09159523612594395 | pass |
| ETCUSDT | 369 | 36.9814 | 0.1002 | 4/6 | 16.3012 | 0.0317 | 3.163 | 0.08661311060828181 | pass |
| **pooled** | 2259 | 122.7959 | 0.0544 | 5/6 | 42.6731 (seq) | - | - | 0.023295048285011517 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade -0.0027 beats the baseline's 0.0544 by -0.0571 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 241 | -8.2197 | -0.0341 | 2/6 | 19.0917 | -0.0134 | 2.553 | 0.6715457340455419 | fail |
| NEARUSDT | 235 | 7.1858 | 0.0306 | 2/6 | 18.2856 | 0.0112 | 2.719 | 0.34472564205310463 | fail |
| ATOMUSDT | 243 | -21.3273 | -0.0878 | 2/6 | 32.9143 | -0.031 | 2.827 | 0.8982112344557938 | fail |
| FILUSDT | 222 | -6.9589 | -0.0313 | 1/6 | 33.1226 | -0.0151 | 2.08 | 0.6370640116600628 | fail |
| TRXUSDT | 250 | 29.7254 | 0.1189 | 4/6 | 17.0785 | 0.0428 | 2.777 | 0.06908951878786806 | pass |
| ETCUSDT | 235 | -4.251 | -0.0181 | 2/6 | 28.1658 | -0.0083 | 2.172 | 0.5883307539129015 | fail |
| **pooled** | 1426 | -3.8462 | -0.0027 | 3/6 | 66.8933 (seq) | - | - | 0.5334619396187005 | - |

Holm survivors (alpha 0.05): []

## arm `ADX` (candidate) -- fail -- net_r/trade 0.0569 beats the baseline's 0.0544 by 0.0025 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 308 | 13.1396 | 0.0427 | 4/6 | 9.8916 | 0.0128 | 3.326 | 0.266602466624743 | pass |
| NEARUSDT | 282 | 7.8847 | 0.028 | 5/6 | 16.466 | 0.0073 | 3.824 | 0.33926035323412906 | pass |
| ATOMUSDT | 301 | 0.941 | 0.0031 | 3/6 | 26.7058 | 0.0009 | 3.53 | 0.4803302178517991 | fail |
| FILUSDT | 277 | 42.5459 | 0.1536 | 3/6 | 11.4154 | 0.0496 | 3.094 | 0.034704156534000635 | fail |
| TRXUSDT | 299 | 27.2243 | 0.0911 | 4/6 | 21.1602 | 0.0291 | 3.134 | 0.10055968265188947 | pass |
| ETCUSDT | 304 | 8.9829 | 0.0295 | 3/6 | 21.2457 | 0.011 | 2.678 | 0.35235739210493044 | fail |
| **pooled** | 1771 | 100.7191 | 0.0569 | 6/6 | 27.2931 (seq) | - | - | 0.026851136817822505 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade 0.1023 beats the baseline's 0.0544 by 0.0479 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 179 | 3.8835 | 0.0217 | 3/6 | 17.0682 | 0.0031 | 6.893 | 0.4431007791533821 | fail |
| NEARUSDT | 144 | 40.119 | 0.2786 | 5/6 | 8.8433 | 0.0303 | 9.189 | 0.047116540021890196 | pass |
| ATOMUSDT | 175 | 4.9375 | 0.0282 | 4/6 | 20.2365 | 0.0038 | 7.348 | 0.4259377079117497 | pass |
| FILUSDT | 155 | 43.7438 | 0.2822 | 3/6 | 18.7688 | 0.0436 | 6.479 | 0.07815731740335935 | fail |
| TRXUSDT | 196 | 0.2005 | 0.001 | 3/6 | 32.8182 | 0.0002 | 5.302 | 0.4970237106361362 | fail |
| ETCUSDT | 174 | 11.8007 | 0.0678 | 4/6 | 25.1579 | 0.0107 | 6.315 | 0.32319934901103037 | pass |
| **pooled** | 1023 | 104.6841 | 0.1023 | 5/6 | 44.5708 (seq) | - | - | 0.055531807160267566 | - |

Holm survivors (alpha 0.05): []

