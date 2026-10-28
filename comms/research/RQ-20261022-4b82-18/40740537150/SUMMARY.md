# Stage-0 (synthetic leg) -- fade 4h -- fail

FAIL: FAR: pooled net_r <= 0 or folds short; SWEEP: net_r/trade -0.1235 beats the baseline's -0.088 by -0.0355 < the 0.05 materiality bar; SWEEPTR: net_r/trade -0.0701 beats the baseline's -0.088 by 0.0179 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline FAR with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `FAR` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 554 | -54.6729 | -0.0987 | 1/6 | 45.2291 | None | None | 0.9007926949961833 | fail |
| ETHUSDT | 552 | 25.8091 | 0.0468 | 4/6 | 20.5066 | None | None | 0.2853531895403556 | pass |
| SOLUSDT | 546 | -82.2923 | -0.1507 | 2/6 | 101.4933 | None | None | 0.9773360173759175 | fail |
| XRPUSDT | 490 | -38.5601 | -0.0787 | 2/6 | 37.8274 | None | None | 0.8374373651943776 | fail |
| ADAUSDT | 546 | -100.3413 | -0.1838 | 1/6 | 85.2285 | None | None | 0.9956529365851453 | fail |
| AVAXUSDT | 553 | -35.0324 | -0.0633 | 2/6 | 94.4426 | None | None | 0.7926413030917361 | fail |
| **pooled** | 3241 | -285.0905 | -0.088 | 1/6 | 344.7144 (seq) | - | - | 0.9974124847856662 | - |

Holm survivors (alpha 0.05): []

## arm `SWEEP` (candidate) -- fail -- net_r/trade -0.1235 beats the baseline's -0.088 by -0.0355 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 412 | -73.6351 | -0.1787 | 2/6 | 48.9973 | None | None | 0.989001309466683 | fail |
| ETHUSDT | 399 | -28.9705 | -0.0726 | 2/6 | 25.9097 | None | None | 0.7970981019820174 | fail |
| SOLUSDT | 366 | -45.4481 | -0.1242 | 1/6 | 40.3349 | None | None | 0.9218084793535202 | fail |
| XRPUSDT | 352 | -60.7509 | -0.1726 | 1/6 | 43.8737 | None | None | 0.9845110205304837 | fail |
| ADAUSDT | 365 | -27.0463 | -0.0741 | 3/6 | 32.178 | None | None | 0.8210460896211631 | fail |
| AVAXUSDT | 382 | -45.1874 | -0.1183 | 2/6 | 67.1431 | None | None | 0.9233743823542965 | fail |
| **pooled** | 2276 | -281.0385 | -0.1235 | 1/6 | 308.2575 (seq) | - | - | 0.9998704607226465 | - |

Holm survivors (alpha 0.05): []

## arm `SWEEPTR` (candidate) -- fail -- net_r/trade -0.0701 beats the baseline's -0.088 by 0.0179 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 394 | -38.0634 | -0.0966 | 2/6 | 36.3777 | None | None | 0.8097733309066316 | fail |
| ETHUSDT | 387 | -60.8568 | -0.1573 | 0/6 | 48.8035 | None | None | 0.970563370309881 | fail |
| SOLUSDT | 349 | -16.8465 | -0.0483 | 2/6 | 39.5585 | None | None | 0.6860379063108667 | fail |
| XRPUSDT | 347 | -29.4337 | -0.0848 | 3/6 | 24.7949 | None | None | 0.8099528597641614 | fail |
| ADAUSDT | 355 | -13.9842 | -0.0394 | 2/6 | 34.1872 | None | None | 0.6679226058118486 | fail |
| AVAXUSDT | 369 | 4.8417 | 0.0131 | 2/6 | 34.0461 | None | None | 0.4457347179120194 | fail |
| **pooled** | 2201 | -154.3447 | -0.0701 | 1/6 | 193.6904 (seq) | - | - | 0.9623696006931081 | - |

Holm survivors (alpha 0.05): []

