# Stage-0 (synthetic leg) -- squeeze 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 285 | 14.2545 | 0.05 | 3/6 | 17.945 | 0.0137 | 3.65 | 0.2606683787102181 | fail |
| DOGEUSDT | 296 | 28.1106 | 0.095 | 4/6 | 20.8743 | 0.0269 | 3.533 | 0.12022419790806044 | pass |
| LINKUSDT | 293 | 21.3275 | 0.0728 | 5/6 | 16.8062 | 0.0199 | 3.652 | 0.16918520363577294 | pass |
| LTCUSDT | 310 | -36.3498 | -0.1173 | 0/6 | 42.7921 | -0.0335 | 3.499 | 0.9512085007629623 | fail |
| BCHUSDT | 295 | -20.4551 | -0.0693 | 3/6 | 49.0134 | -0.0204 | 3.406 | 0.7980465150020741 | fail |
| DOTUSDT | 278 | -1.2708 | -0.0046 | 3/6 | 13.2483 | -0.0011 | 4.003 | 0.5250107414307661 | fail |
| **pooled** | 1757 | 5.6163 | 0.0032 | 3/6 | 64.5622 (seq) | - | - | 0.4594879714894419 | - |

Holm survivors (alpha 0.05): []

