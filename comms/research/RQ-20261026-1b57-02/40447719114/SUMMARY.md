# Stage-0 (synthetic leg) -- trend 1h -- pass

PASS: arm B passes (pooled net_r 244.4572); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 244.4572 > 0 with 6 folds positive and 4 of 5 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SUIUSDT | 592 | 52.5106 | 0.0887 | 3/6 | 16.8743 | 0.143 | 0.62 | 0.08836997553300524 | fail |
| APTUSDT | 624 | 59.8225 | 0.0959 | 5/6 | 25.9102 | 0.1482 | 0.647 | 0.04221908437873939 | pass |
| ARBUSDT | 597 | 53.3065 | 0.0893 | 5/6 | 15.7428 | 0.1476 | 0.605 | 0.03999595155571172 | pass |
| OPUSDT | 701 | 33.7778 | 0.0482 | 4/6 | 21.1244 | 0.0731 | 0.659 | 0.15244163180976056 | pass |
| INJUSDT | 665 | 45.0392 | 0.0677 | 5/6 | 18.4842 | 0.1022 | 0.662 | 0.06602631829449207 | pass |
| **pooled** | 3179 | 244.4572 | 0.0769 | 6/6 | 51.4503 (seq) | - | - | 0.000548567442918032 | - |

Holm survivors (alpha 0.05): []

