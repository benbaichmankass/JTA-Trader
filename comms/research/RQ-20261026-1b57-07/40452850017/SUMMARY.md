# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm B passes (pooled net_r 243.4278); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 243.4278 > 0 with 5 folds positive and 5 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 252 | 78.1528 | 0.3101 | 5/6 | 20.3673 | 0.1091 | 2.844 | 0.03321581834369029 | pass |
| DOGEUSDT | 230 | 45.2557 | 0.1968 | 4/6 | 28.5173 | 0.066 | 2.983 | 0.10048995062366689 | pass |
| LINKUSDT | 220 | 30.1418 | 0.137 | 4/6 | 19.1934 | 0.0345 | 3.966 | 0.1810404657035697 | pass |
| LTCUSDT | 225 | 7.6732 | 0.0341 | 2/6 | 29.1329 | 0.0096 | 3.544 | 0.4070898451102579 | fail |
| BCHUSDT | 229 | 56.5818 | 0.2471 | 4/6 | 24.5718 | 0.0644 | 3.838 | 0.07358071045625275 | pass |
| DOTUSDT | 199 | 25.622 | 0.1288 | 5/6 | 21.2693 | 0.0283 | 4.554 | 0.21810160978570614 | pass |
| **pooled** | 1355 | 243.4278 | 0.1797 | 5/6 | 56.5961 (seq) | - | - | 0.00291338672671838 | - |

Holm survivors (alpha 0.05): []

