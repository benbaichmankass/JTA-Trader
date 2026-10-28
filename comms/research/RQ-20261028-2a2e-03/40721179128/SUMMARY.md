# Stage-0 (synthetic leg) -- pullback 1d -- fail

FAIL: B: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; LONG: net_r/trade 0.2936 beats the baseline's 0.2346 by 0.059 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 27 | 12.2451 | 0.4535 | 5/6 | 5.1957 | 0.0078 | 58.37 | 0.14537108966991125 | pass |
| NEARUSDT | 32 | 10.2574 | 0.3205 | 4/6 | 8.403 | 0.0065 | 49.625 | 0.1919028156190799 | pass |
| ATOMUSDT | 21 | 4.0458 | 0.1927 | 2/6 | 6.6268 | 0.0021 | 91.571 | 0.2847245672846851 | fail |
| FILUSDT | 27 | 7.93 | 0.2937 | 3/6 | 4.1089 | 0.0049 | 60.444 | 0.26656482006915483 | fail |
| TRXUSDT | 34 | 1.3995 | 0.0412 | 3/6 | 11.8445 | 0.0008 | 54.265 | 0.4439924535875938 | fail |
| ETCUSDT | 31 | 4.4698 | 0.1442 | 3/6 | 7.386 | 0.0025 | 58.516 | 0.35036849243592816 | fail |
| **pooled** | 172 | 40.3475 | 0.2346 | 4/6 | 26.0604 (seq) | - | - | 0.06224137993844575 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade 0.2936 beats the baseline's 0.2346 by 0.059 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 22 | 12.4832 | 0.5674 | 4/6 | 3.2556 | 0.0185 | 30.682 | 0.15202238506885662 | pass |
| NEARUSDT | 22 | 8.6267 | 0.3921 | 3/6 | 7.3298 | 0.0104 | 37.636 | 0.20601468460127115 | fail |
| ATOMUSDT | 22 | 0.7776 | 0.0353 | 2/6 | 10.3952 | 0.0007 | 51.136 | 0.45678080078460964 | fail |
| FILUSDT | 20 | 13.5016 | 0.6751 | 5/6 | 5.1359 | 0.022 | 30.75 | 0.15263751099659667 | pass |
| TRXUSDT | 28 | 8.6364 | 0.3084 | 3/6 | 8.7698 | 0.0073 | 42.286 | 0.2072575391658718 | fail |
| ETCUSDT | 25 | -3.2174 | -0.1287 | 2/6 | 12.8068 | -0.0043 | 30.2 | 0.6186845785283499 | fail |
| **pooled** | 139 | 40.8079 | 0.2936 | 3/6 | 20.9687 (seq) | - | - | 0.05804374530542444 | - |

Holm survivors (alpha 0.05): []

