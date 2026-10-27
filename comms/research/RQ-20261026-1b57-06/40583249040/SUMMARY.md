# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled passes but only 2 of 5 powered cells pass (< 3): one symbol's edge. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled passes but only 2 of 5 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SUIUSDT | 46 | 2.0024 | 0.0435 | 3/6 | 5.9151 | 0.0213 | 2.04 | 0.4046871921982549 | fail |
| APTUSDT | 48 | 17.7453 | 0.3697 | 6/6 | 3.2759 | 0.1001 | 3.695 | 0.03893891235646932 | pass |
| ARBUSDT | 49 | 20.866 | 0.4258 | 4/6 | 4.5208 | 0.2252 | 1.891 | 0.029864743710311236 | pass |
| OPUSDT | 62 | 4.3278 | 0.0698 | 3/6 | 5.9965 | 0.0323 | 2.164 | 0.3253306782605877 | fail |
| INJUSDT | 47 | 14.1411 | 0.3009 | 3/6 | 9.572 | 0.147 | 2.046 | 0.1425187883899161 | fail |
| **pooled** | 252 | 59.0831 | 0.2345 | 5/6 | 11.3785 (seq) | - | - | 0.005835617794473798 | - |

Holm survivors (alpha 0.05): []

