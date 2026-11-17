# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm LONG passes (pooled net_r 99.2079); 1 of 2 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| TRXUSDT | 41 | 26.6527 | 0.6501 | 5/6 | 4.2627 | 0.0174 | 37.463 | 0.0686072934801451 | pass |
| ETCUSDT | 39 | 10.2287 | 0.2623 | 2/6 | 6.8157 | 0.0069 | 38.026 | 0.22763767281838865 | fail |
| XLMUSDT | 38 | -0.8717 | -0.0229 | 3/6 | 12.644 | -0.0005 | 43.474 | 0.5421935574955237 | fail |
| ATOMUSDT | 41 | -7.5549 | -0.1843 | 2/6 | 12.9199 | -0.0045 | 41.049 | 0.8405042954801372 | fail |
| VETUSDT | 31 | 22.5707 | 0.7281 | 6/6 | 3.8008 | 0.0136 | 53.355 | 0.04385222520539637 | pass |
| FILUSDT | 27 | 9.0395 | 0.3348 | 3/6 | 5.0536 | 0.0056 | 60.074 | 0.11426498868109375 | fail |
| **pooled** | 217 | 60.065 | 0.2768 | 4/6 | 14.7423 (seq) | - | - | 0.019597659935025418 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- pass -- pooled net_r 99.2079 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); beats the baseline by 0.2268 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| TRXUSDT | 29 | 44.5072 | 1.5347 | 6/6 | 2.1028 | 0.0539 | 28.448 | 0.006158484531272782 | pass |
| ETCUSDT | 32 | 19.0782 | 0.5962 | 4/6 | 4.7478 | 0.04 | 14.906 | 0.09662264827468625 | pass |
| XLMUSDT | 36 | 8.1765 | 0.2271 | 2/6 | 11.286 | 0.0146 | 15.556 | 0.2833542561477581 | fail |
| ATOMUSDT | 36 | -1.1165 | -0.031 | 3/6 | 6.8132 | -0.0016 | 19.222 | 0.5481742566007806 | fail |
| VETUSDT | 33 | 18.5521 | 0.5622 | 5/6 | 3.9054 | 0.03 | 18.727 | 0.08675920703333495 | pass |
| FILUSDT | 31 | 10.0101 | 0.3229 | 2/6 | 7.1462 | 0.0232 | 13.903 | 0.1926724213076872 | fail |
| **pooled** | 197 | 99.2079 | 0.5036 | 4/6 | 18.2643 (seq) | - | - | 0.0015035213970218493 | - |

Holm survivors (alpha 0.05): ['TRXUSDT']

