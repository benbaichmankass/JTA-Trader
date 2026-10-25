# Stage-0 (synthetic leg) -- pullback 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 861 | -45.6392 | -0.053 | 3/6 | 79.7591 | -0.025 | 2.122 | 0.828853451784284 | fail |
| LTCUSDT | 781 | -25.78 | -0.033 | 2/6 | 48.1148 | -0.0142 | 2.328 | 0.7105230313445876 | fail |
| BCHUSDT | 836 | -19.5548 | -0.0234 | 3/6 | 78.4425 | -0.0109 | 2.153 | 0.647649576213847 | fail |
| DOTUSDT | 815 | -21.4309 | -0.0263 | 3/6 | 53.5982 | -0.0125 | 2.108 | 0.6656234490684532 | fail |
| BTCUSDT | 797 | 71.6479 | 0.0899 | 5/6 | 21.9944 | 0.0387 | 2.321 | 0.10406306709354174 | pass |
| **pooled** | 4090 | -40.7601 | -0.01 | 2/6 | 126.7247 (seq) | - | - | 0.6403333271696565 | - |

Holm survivors (alpha 0.05): []

