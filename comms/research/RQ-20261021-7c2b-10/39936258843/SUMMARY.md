# Stage-0 (synthetic leg) -- trend 1h -- pass

PASS: arm B passes (pooled net_r 335.9706); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 335.9706 > 0 with 6 folds positive and 6 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 1105 | 39.7065 | 0.0359 | 4/6 | 27.5697 | 0.0627 | 0.573 | 0.16331764612795086 | pass |
| DOGEUSDT | 1017 | 73.6316 | 0.0724 | 6/6 | 16.3996 | 0.1346 | 0.538 | 0.04862201822807072 | pass |
| LINKUSDT | 1027 | 91.114 | 0.0887 | 6/6 | 12.1231 | 0.1338 | 0.663 | 0.011338421556487885 | pass |
| LTCUSDT | 1028 | 23.3051 | 0.0227 | 4/6 | 17.8575 | 0.0365 | 0.621 | 0.277276466246864 | pass |
| BCHUSDT | 1034 | 48.2368 | 0.0467 | 5/6 | 18.8529 | 0.0789 | 0.591 | 0.11871361096562016 | pass |
| DOTUSDT | 1009 | 59.9748 | 0.0594 | 4/6 | 36.1412 | 0.0894 | 0.665 | 0.05648374784982485 | pass |
| **pooled** | 6220 | 335.9706 | 0.054 | 6/6 | 54.7955 (seq) | - | - | 0.0003561756895520229 | - |

Holm survivors (alpha 0.05): []

