# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled n 1391 < floor 1500: underpowered, never FAIL on thin n; TV90: net_r/trade 0.1123 beats the baseline's 0.177 by -0.0647 < the 0.13 materiality bar. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

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

## arm `TV90` (candidate) -- fail -- net_r/trade 0.1123 beats the baseline's 0.177 by -0.0647 < the 0.13 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 367 | 64.8028 | 0.1766 | 6/6 | 18.7359 | 0.044 | 4.014 | 0.04050172311301716 | pass |
| ADAUSDT | 368 | 32.4866 | 0.0883 | 5/6 | 21.9491 | 0.0256 | 3.452 | 0.13648735971057552 | pass |
| ETHUSDT | 372 | 16.0892 | 0.0433 | 4/6 | 19.175 | 0.012 | 3.59 | 0.30461306356837037 | pass |
| AVAXUSDT | 362 | 61.2046 | 0.1691 | 5/6 | 17.1267 | 0.0485 | 3.487 | 0.041271609717528836 | pass |
| SOLUSDT | 343 | 28.8842 | 0.0842 | 3/6 | 18.8778 | 0.0246 | 3.418 | 0.15438194559305568 | fail |
| **pooled** | 1812 | 203.4659 | 0.1123 | 6/6 | 48.2736 (seq) | - | - | 0.0025567696171737656 | - |

Holm survivors (alpha 0.05): []

