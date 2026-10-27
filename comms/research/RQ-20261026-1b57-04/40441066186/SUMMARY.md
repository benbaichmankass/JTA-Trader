# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 316.5429); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 316.5429 > 0 with 6 folds positive and 5 of 5 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SUIUSDT | 146 | 50.9394 | 0.3489 | 5/6 | 9.2789 | 0.1509 | 2.313 | 0.03387473106562179 | pass |
| APTUSDT | 151 | 73.7033 | 0.4881 | 5/6 | 11.57 | 0.1783 | 2.737 | 0.0026933870622429445 | pass |
| ARBUSDT | 149 | 52.8276 | 0.3545 | 4/6 | 10.4212 | 0.1423 | 2.491 | 0.028601179515700684 | pass |
| OPUSDT | 175 | 65.0423 | 0.3717 | 6/6 | 8.2086 | 0.1379 | 2.694 | 0.00760655163704325 | pass |
| INJUSDT | 176 | 74.0301 | 0.4206 | 6/6 | 13.2601 | 0.1661 | 2.532 | 0.009132504446179395 | pass |
| **pooled** | 797 | 316.5429 | 0.3972 | 6/6 | 20.9544 (seq) | - | - | 2.170769157156574e-07 | - |

Holm survivors (alpha 0.05): ['APTUSDT', 'OPUSDT', 'INJUSDT']

