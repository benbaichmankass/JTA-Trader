# Stage-0 (synthetic leg) -- trend 4h -- pass

PASS: arm D55 passes (pooled net_r 143.4303); 1 of 2 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 377 | -1.3805 | -0.0037 | 4/6 | 18.5226 | -0.0011 | 3.4 | 0.5247965741897975 | fail |
| BNBUSDT | 403 | 2.4834 | 0.0062 | 3/6 | 27.8344 | 0.0021 | 3.001 | 0.4625588587614451 | fail |
| ETHUSDT | 382 | 33.1096 | 0.0867 | 4/6 | 14.8588 | 0.0257 | 3.373 | 0.10899453735159642 | pass |
| XRPUSDT | 373 | 36.6086 | 0.0981 | 4/6 | 17.5148 | 0.032 | 3.065 | 0.09193069011110966 | pass |
| LINKUSDT | 415 | -2.9706 | -0.0072 | 3/6 | 19.8954 | -0.0023 | 3.151 | 0.5482816372199864 | fail |
| AAVEUSDT | 381 | 5.5453 | 0.0146 | 4/6 | 19.0868 | 0.0044 | 3.329 | 0.41370522160738354 | pass |
| **pooled** | 2331 | 73.3972 | 0.0315 | 3/6 | 86.591 (seq) | - | - | 0.12018763553621231 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- pass -- pooled net_r 143.4303 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3); beats the baseline by 0.1065 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 165 | 54.5021 | 0.3303 | 5/6 | 13.281 | 0.042 | 7.857 | 0.03588252772101176 | pass |
| BNBUSDT | 172 | 27.721 | 0.1612 | 4/6 | 14.0283 | 0.025 | 6.453 | 0.1592682933903845 | pass |
| ETHUSDT | 173 | 44.9846 | 0.26 | 5/6 | 11.3045 | 0.0344 | 7.55 | 0.07186247199229534 | pass |
| XRPUSDT | 181 | 15.8905 | 0.0878 | 5/6 | 18.0018 | 0.0158 | 5.565 | 0.2886393577160044 | pass |
| LINKUSDT | 184 | -1.5001 | -0.0082 | 3/6 | 26.6069 | -0.0012 | 7.023 | 0.5218334697573241 | fail |
| AAVEUSDT | 164 | 1.8326 | 0.0112 | 2/6 | 24.529 | 0.0015 | 7.479 | 0.46954064217640995 | fail |
| **pooled** | 1039 | 143.4303 | 0.138 | 5/6 | 48.9215 (seq) | - | - | 0.018686933208568787 | - |

Holm survivors (alpha 0.05): []

