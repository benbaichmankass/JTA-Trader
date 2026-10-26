# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm LONG passes (pooled net_r 116.4993); 1 of 2 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 68.0025 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 38 | 18.1684 | 0.4781 | 4/6 | 5.5615 | 0.0114 | 41.895 | 0.09531153349949661 | pass |
| NEARUSDT | 36 | 6.4486 | 0.1791 | 4/6 | 5.7167 | 0.0042 | 42.444 | 0.29314332159398415 | pass |
| ATOMUSDT | 41 | -6.4909 | -0.1583 | 2/6 | 12.9199 | -0.0039 | 41.049 | 0.7906376453931796 | fail |
| FILUSDT | 27 | 9.0395 | 0.3348 | 3/6 | 5.0536 | 0.0056 | 60.074 | 0.11426498868109375 | fail |
| TRXUSDT | 41 | 26.7058 | 0.6514 | 5/6 | 4.2627 | 0.0174 | 37.463 | 0.06846242963148397 | pass |
| ETCUSDT | 39 | 14.1315 | 0.3623 | 2/6 | 6.8157 | 0.0095 | 38.026 | 0.18093326581847075 | fail |
| **pooled** | 222 | 68.0025 | 0.3063 | 4/6 | 14.4532 (seq) | - | - | 0.015389022304533661 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- pass -- pooled net_r 116.4993 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3); beats the baseline by 0.2911 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 34 | 22.4716 | 0.6609 | 4/6 | 7.7065 | 0.0322 | 20.5 | 0.12415504414376244 | pass |
| NEARUSDT | 33 | 18.5664 | 0.5626 | 4/6 | 7.8234 | 0.0287 | 19.636 | 0.09317567270746802 | pass |
| ATOMUSDT | 36 | -1.1165 | -0.031 | 3/6 | 6.8132 | -0.0016 | 19.222 | 0.5481742566007806 | fail |
| FILUSDT | 31 | 10.406 | 0.3357 | 2/6 | 7.1462 | 0.0241 | 13.903 | 0.1867207909845754 | fail |
| TRXUSDT | 29 | 44.5603 | 1.5366 | 6/6 | 2.1028 | 0.054 | 28.448 | 0.006159253594623417 | pass |
| ETCUSDT | 32 | 21.6116 | 0.6754 | 4/6 | 4.7478 | 0.0453 | 14.906 | 0.08912006467255862 | pass |
| **pooled** | 195 | 116.4993 | 0.5974 | 5/6 | 15.8388 (seq) | - | - | 0.0007339740645150736 | - |

Holm survivors (alpha 0.05): ['TRXUSDT']

