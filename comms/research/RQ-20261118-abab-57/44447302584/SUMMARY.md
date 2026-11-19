# Stage-0 (synthetic leg) -- pullback 2h -- indeterminate

INDETERMINATE: B: pooled n 1391 < floor 1500: underpowered, never FAIL on thin n; DI: pooled n 1322 < floor 1500: underpowered, never FAIL on thin n. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

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

## arm `DI` (candidate) -- indeterminate -- pooled n 1322 < floor 1500: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 279 | 60.6935 | 0.2175 | 6/6 | 16.3838 | 0.0394 | 5.519 | 0.046408504390149874 | pass |
| ADAUSDT | 258 | 42.5155 | 0.1648 | 5/6 | 33.2085 | 0.0312 | 5.282 | 0.10108606578816026 | pass |
| ETHUSDT | 274 | 11.5069 | 0.042 | 4/6 | 25.9347 | 0.0079 | 5.32 | 0.3712314261629267 | pass |
| AVAXUSDT | 261 | 44.2183 | 0.1694 | 4/6 | 26.7182 | 0.0339 | 4.999 | 0.07864627609011049 | pass |
| SOLUSDT | 250 | 17.2206 | 0.0689 | 4/6 | 29.2952 | 0.0133 | 5.177 | 0.28376021547927543 | pass |
| **pooled** | 1322 | 176.1534 | 0.1332 | 5/6 | 64.9457 (seq) | - | - | 0.008790529468918567 | - |

Holm survivors (alpha 0.05): []

