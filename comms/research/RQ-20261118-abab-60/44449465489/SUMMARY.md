# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; DI: net_r/trade -0.0219 beats the baseline's -0.0028 by -0.0191 < the 0.13 materiality bar. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 279 | 39.57 | 0.1418 | 4/6 | 22.6404 | 0.0246 | 5.77 | 0.12373938273633434 | pass |
| DOGEUSDT | 271 | 1.4556 | 0.0054 | 3/6 | 43.0946 | 0.0009 | 5.832 | 0.4808106458958623 | fail |
| LINKUSDT | 289 | 3.7012 | 0.0128 | 4/6 | 38.7127 | 0.0024 | 5.25 | 0.4537428491589169 | pass |
| LTCUSDT | 287 | -35.6075 | -0.1241 | 2/6 | 61.0912 | -0.0238 | 5.208 | 0.8838028906471114 | fail |
| BCHUSDT | 282 | -2.2998 | -0.0082 | 4/6 | 36.7923 | -0.0014 | 5.643 | 0.5287525541339184 | fail |
| DOTUSDT | 276 | -11.6172 | -0.0421 | 2/6 | 34.1518 | -0.0077 | 5.436 | 0.6414439069055359 | fail |
| **pooled** | 1684 | -4.7969 | -0.0028 | 3/6 | 158.4322 (seq) | - | - | 0.5246642887763427 | - |

Holm survivors (alpha 0.05): []

## arm `DI` (candidate) -- fail -- net_r/trade -0.0219 beats the baseline's -0.0028 by -0.0191 < the 0.13 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 263 | 29.6481 | 0.1127 | 3/6 | 23.8488 | 0.02 | 5.648 | 0.18560204203252134 | fail |
| DOGEUSDT | 259 | -8.65 | -0.0334 | 2/6 | 37.3984 | -0.0059 | 5.629 | 0.6205943534782468 | fail |
| LINKUSDT | 271 | -5.0632 | -0.0187 | 3/6 | 31.7573 | -0.0037 | 5.028 | 0.5667418101526458 | fail |
| LTCUSDT | 264 | -31.0613 | -0.1177 | 2/6 | 51.7257 | -0.022 | 5.35 | 0.860497833633202 | fail |
| BCHUSDT | 267 | -19.1942 | -0.0719 | 3/6 | 48.4323 | -0.0132 | 5.432 | 0.7375878555145017 | fail |
| DOTUSDT | 256 | -0.3244 | -0.0013 | 3/6 | 26.7308 | -0.0002 | 5.653 | 0.5040640093811618 | fail |
| **pooled** | 1580 | -34.6439 | -0.0219 | 2/6 | 146.5183 (seq) | - | - | 0.6794334357220204 | - |

Holm survivors (alpha 0.05): []

