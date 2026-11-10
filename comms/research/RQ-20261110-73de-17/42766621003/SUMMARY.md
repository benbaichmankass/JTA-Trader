# Stage-0 (synthetic leg) -- squeeze 4h -- fail

FAIL: B: pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 294 | 0.4581 | 0.0016 | 3/6 | 20.6257 | 0.0004 | 3.578 | 0.49282024258622914 | fail |
| ETHUSDT | 301 | 16.2455 | 0.054 | 5/6 | 13.5501 | 0.0154 | 3.507 | 0.2715639087554703 | pass |
| SOLUSDT | 267 | 64.0045 | 0.2397 | 6/6 | 8.0343 | 0.0614 | 3.901 | 0.004849184877389035 | pass |
| XRPUSDT | 295 | -13.3782 | -0.0453 | 3/6 | 37.8837 | -0.0133 | 3.406 | 0.7011688728469053 | fail |
| ADAUSDT | 294 | 30.9198 | 0.1052 | 5/6 | 19.8268 | 0.0294 | 3.582 | 0.09053028457873202 | pass |
| AVAXUSDT | 273 | -17.0964 | -0.0626 | 1/6 | 28.7902 | -0.0174 | 3.601 | 0.8090235463181233 | fail |
| BNBUSDT | 287 | 10.0601 | 0.0351 | 3/6 | 19.4153 | 0.0096 | 3.639 | 0.32561127774658544 | fail |
| DOGEUSDT | 297 | 27.9816 | 0.0942 | 4/6 | 20.8743 | 0.0267 | 3.528 | 0.12131150700737864 | pass |
| LINKUSDT | 295 | 20.1261 | 0.0682 | 5/6 | 16.8062 | 0.0188 | 3.636 | 0.18339500225124722 | pass |
| LTCUSDT | 311 | -37.4345 | -0.1204 | 0/6 | 42.7921 | -0.0344 | 3.495 | 0.9558469594445409 | fail |
| BCHUSDT | 297 | -21.6194 | -0.0728 | 3/6 | 49.0134 | -0.0214 | 3.398 | 0.8109511094009476 | fail |
| DOTUSDT | 280 | -2.9547 | -0.0106 | 3/6 | 13.2483 | -0.0026 | 3.989 | 0.5578792041902312 | fail |
| **pooled** | 3491 | 77.3125 | 0.0221 | 4/6 | 98.2086 (seq) | - | - | 0.17024519657157927 | - |

Holm survivors (alpha 0.05): []

