# Stage-0 (synthetic leg) -- pullback 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 203 | 6.652 | 0.0328 | 3/6 | 16.9878 | 0.0037 | 8.966 | 0.39590652534002935 | fail |
| ETHUSDT | 199 | 1.3728 | 0.0069 | 4/6 | 27.4859 | 0.0007 | 9.251 | 0.4794294810804543 | pass |
| SOLUSDT | 192 | 29.0468 | 0.1513 | 4/6 | 20.659 | 0.0163 | 9.265 | 0.14325763754777043 | pass |
| XRPUSDT | 204 | -13.4824 | -0.0661 | 3/6 | 38.612 | -0.0072 | 9.125 | 0.7090871566398137 | fail |
| ADAUSDT | 187 | 12.7352 | 0.0681 | 4/6 | 19.8865 | 0.0069 | 9.877 | 0.2976277959463116 | pass |
| AVAXUSDT | 197 | 32.5703 | 0.1653 | 5/6 | 12.8598 | 0.0185 | 8.953 | 0.09258396012853043 | pass |
| BNBUSDT | 202 | 19.3606 | 0.0958 | 4/6 | 24.5132 | 0.0104 | 9.183 | 0.23515047156671604 | pass |
| DOGEUSDT | 188 | 1.4679 | 0.0078 | 1/6 | 25.194 | 0.0008 | 9.949 | 0.47432180928919654 | fail |
| LINKUSDT | 196 | 12.741 | 0.065 | 4/6 | 24.6356 | 0.007 | 9.321 | 0.305436918723858 | pass |
| LTCUSDT | 205 | 6.3185 | 0.0308 | 3/6 | 39.3731 | 0.0034 | 9.116 | 0.39741091581272947 | fail |
| BCHUSDT | 186 | 14.7477 | 0.0793 | 3/6 | 27.0955 | 0.0078 | 10.158 | 0.26994546863993646 | fail |
| DOTUSDT | 189 | 34.1207 | 0.1805 | 4/6 | 11.1465 | 0.019 | 9.513 | 0.10035546096590942 | pass |
| **pooled** | 2348 | 157.6525 | 0.0671 | 3/6 | 141.3612 (seq) | - | - | 0.03492904877073581 | - |

Holm survivors (alpha 0.05): []

