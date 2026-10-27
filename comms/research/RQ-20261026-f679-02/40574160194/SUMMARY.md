# Stage-0 (synthetic leg) -- trend 1h -- fail

FAIL: B: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; D55: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 1500 | -7.5946 | -0.0051 | 2/6 | 53.1841 | -0.0058 | 0.877 | 0.5632762213186266 | fail |
| BNBUSDT | 1569 | -34.5474 | -0.022 | 2/6 | 71.2625 | -0.0277 | 0.794 | 0.7631996109435855 | fail |
| ETHUSDT | 1506 | -34.8593 | -0.0231 | 2/6 | 66.253 | -0.0278 | 0.833 | 0.7658245323336212 | fail |
| XRPUSDT | 1429 | 140.6084 | 0.0984 | 5/6 | 22.5867 | 0.117 | 0.841 | 0.012101305714440503 | pass |
| LINKUSDT | 1539 | 0.4113 | 0.0003 | 3/6 | 33.4525 | 0.0003 | 0.879 | 0.4966585825612622 | fail |
| AAVEUSDT | 1434 | 51.1003 | 0.0356 | 4/6 | 26.6785 | 0.0397 | 0.898 | 0.16306358945166138 | pass |
| **pooled** | 8977 | 115.1151 | 0.0128 | 4/6 | 95.4201 (seq) | - | - | 0.18068575351674493 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 633 | 92.0669 | 0.1454 | 5/6 | 32.3596 | 0.0698 | 2.083 | 0.041898948100191305 | pass |
| BNBUSDT | 682 | 21.669 | 0.0318 | 3/6 | 40.6975 | 0.0171 | 1.856 | 0.33957718786276525 | fail |
| ETHUSDT | 633 | 83.1563 | 0.1314 | 5/6 | 23.3012 | 0.063 | 2.085 | 0.07373076884453267 | pass |
| XRPUSDT | 654 | 37.355 | 0.0571 | 3/6 | 34.6712 | 0.0333 | 1.716 | 0.2342776566938034 | fail |
| LINKUSDT | 669 | -15.0866 | -0.0226 | 2/6 | 55.3127 | -0.0111 | 2.027 | 0.6298415200419337 | fail |
| AAVEUSDT | 620 | 44.7732 | 0.0722 | 3/6 | 27.9545 | 0.0334 | 2.159 | 0.20606505742923725 | fail |
| **pooled** | 3891 | 263.9347 | 0.0678 | 4/6 | 111.4729 (seq) | - | - | 0.020127167059338695 | - |

Holm survivors (alpha 0.05): []

