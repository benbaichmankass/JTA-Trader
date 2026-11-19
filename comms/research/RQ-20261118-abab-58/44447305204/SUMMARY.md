# Stage-0 (synthetic leg) -- pullback 2h -- indeterminate

INDETERMINATE: B: pooled n 1391 < floor 1500: underpowered, never FAIL on thin n; VW100: pooled n 1285 < floor 1500: underpowered, never FAIL on thin n. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- indeterminate -- pooled n 1391 < floor 1500: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 293 | 66.5163 | 0.227 | 6/6 | 18.1997 | 0.0402 | 5.643 | 0.03508174085375586 | pass |
| ADAUSDT | 276 | 54.0632 | 0.1959 | 4/6 | 31.71 | 0.0355 | 5.523 | 0.06786373388161693 | pass |
| ETHUSDT | 284 | 32.9071 | 0.1159 | 5/6 | 30.7608 | 0.021 | 5.525 | 0.19355723277660547 | pass |
| AVAXUSDT | 276 | 63.7542 | 0.231 | 5/6 | 15.0419 | 0.0449 | 5.142 | 0.036434783533148156 | pass |
| SOLUSDT | 262 | 28.9403 | 0.1105 | 3/6 | 24.3368 | 0.0212 | 5.212 | 0.17565553700629954 | fail |
| **pooled** | 1391 | 246.1793 | 0.177 | 6/6 | 52.4026 (seq) | - | - | 0.0009723288285427704 | - |

Holm survivors (alpha 0.05): []

## arm `VW100` (candidate) -- indeterminate -- pooled n 1285 < floor 1500: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 274 | 57.6027 | 0.2102 | 6/6 | 15.205 | 0.0355 | 5.916 | 0.04845035564445871 | pass |
| ADAUSDT | 258 | 46.0358 | 0.1784 | 5/6 | 25.6096 | 0.0313 | 5.709 | 0.09671922640246894 | pass |
| ETHUSDT | 269 | 30.042 | 0.1117 | 4/6 | 27.532 | 0.0199 | 5.602 | 0.21401123549621853 | pass |
| AVAXUSDT | 241 | 67.6113 | 0.2805 | 5/6 | 15.2671 | 0.0496 | 5.651 | 0.021058938686837246 | pass |
| SOLUSDT | 243 | 27.0087 | 0.1111 | 3/6 | 22.8382 | 0.0208 | 5.35 | 0.18584767756708864 | fail |
| **pooled** | 1285 | 228.2987 | 0.1777 | 5/6 | 50.5056 (seq) | - | - | 0.001465830189222784 | - |

Holm survivors (alpha 0.05): []

