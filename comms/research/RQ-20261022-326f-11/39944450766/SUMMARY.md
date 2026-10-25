# Stage-0 (synthetic leg) -- pullback 4h -- pass

PASS: arm B passes (pooled net_r 89.0908); 1 of 1 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- pass -- pooled net_r 89.0908 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 201 | 21.7876 | 0.1084 | 4/6 | 24.1044 | 0.0118 | 9.197 | 0.20827244256433725 | pass |
| DOGEUSDT | 188 | 0.5946 | 0.0032 | 1/6 | 25.194 | 0.0003 | 9.895 | 0.48956758188488275 | fail |
| LINKUSDT | 195 | 12.1118 | 0.0621 | 4/6 | 24.6356 | 0.0067 | 9.327 | 0.31407761180549126 | pass |
| LTCUSDT | 203 | 6.6723 | 0.0329 | 3/6 | 39.3731 | 0.0036 | 9.179 | 0.39166644360120123 | fail |
| BCHUSDT | 184 | 15.5053 | 0.0843 | 3/6 | 27.0955 | 0.0082 | 10.237 | 0.2595436530999773 | fail |
| DOTUSDT | 189 | 32.4186 | 0.1715 | 4/6 | 11.1465 | 0.0181 | 9.46 | 0.11153415619220186 | pass |
| **pooled** | 1160 | 89.0908 | 0.0768 | 4/6 | 78.1798 (seq) | - | - | 0.07187375263669316 | - |

Holm survivors (alpha 0.05): []

