# Stage-0 (synthetic leg) -- trend 4h -- indeterminate

INDETERMINATE: B: pooled n 67 < floor 88: underpowered, never FAIL on thin n. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- indeterminate -- pooled n 67 < floor 88: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 15 | 6.7498 | 0.45 | 4/6 | 5.6621 | 0.212 | 2.122 | 0.187352432773847 | indeterminate |
| DOGEUSDT | - | - | - | - | - | - | - | - | harness_failed: ValueError: empty window: 2020-07-10 08:00:00+00:00 .. 2020-05-31 00:00:00+00:00 |
| LINKUSDT | 18 | 10.2369 | 0.5687 | 4/6 | 5.1786 | 0.287 | 1.981 | 0.1150118733418754 | indeterminate |
| LTCUSDT | 16 | 3.6695 | 0.2293 | 3/6 | 4.6424 | 0.1029 | 2.229 | 0.32195491797076636 | indeterminate |
| BCHUSDT | 18 | 14.5713 | 0.8095 | 4/6 | 6.193 | 0.3689 | 2.195 | 0.04759181624498646 | indeterminate |
| **pooled** | 67 | 35.2278 | 0.5258 | 4/6 | 21.676 (seq) | - | - | 0.013412410193054882 | - |

Holm survivors (alpha 0.05): []

