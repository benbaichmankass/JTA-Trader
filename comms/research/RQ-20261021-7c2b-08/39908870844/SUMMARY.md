# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 277 | 38.9908 | 0.1408 | 5/6 | 21.9129 | 0.0245 | 5.752 | 0.12384804177137959 | pass |
| DOGEUSDT | 270 | -3.8613 | -0.0143 | 3/6 | 43.0946 | -0.0025 | 5.778 | 0.5513489398245166 | fail |
| LINKUSDT | 288 | 0.679 | 0.0024 | 4/6 | 38.7127 | 0.0005 | 5.21 | 0.49145724428584864 | pass |
| LTCUSDT | 284 | -37.3397 | -0.1315 | 2/6 | 61.0912 | -0.0254 | 5.181 | 0.895522467513346 | fail |
| BCHUSDT | 279 | -3.7371 | -0.0134 | 4/6 | 36.7923 | -0.0024 | 5.663 | 0.546994915275149 | fail |
| DOTUSDT | 272 | -15.6783 | -0.0576 | 2/6 | 33.1227 | -0.0105 | 5.47 | 0.6888072534959542 | fail |
| **pooled** | 1670 | -20.9457 | -0.0125 | 3/6 | 156.9815 (seq) | - | - | 0.6073084048564427 | - |

Holm survivors (alpha 0.05): []

