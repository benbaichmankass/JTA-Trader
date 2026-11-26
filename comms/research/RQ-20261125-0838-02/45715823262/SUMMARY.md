# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r 71.691 > 0 with 5 folds positive and 2 of 2 powered cells pass (breadth floor 1); W30: net_r/trade 0.1019 beats the baseline's 0.0906 by 0.0113 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 71.691 > 0 with 5 folds positive and 2 of 2 powered cells pass (breadth floor 1)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 399 | 18.31 | 0.0459 | 4/6 | 23.2722 | 0.0104 | 4.424 | 0.32928462723996466 | pass |
| SOLUSDT | 392 | 53.382 | 0.1362 | 5/6 | 15.1738 | 0.0307 | 4.438 | 0.08094451354107884 | pass |
| **pooled** | 791 | 71.691 | 0.0906 | 5/6 | 28.6737 (seq) | - | - | 0.1013855932150245 | - |

Holm survivors (alpha 0.05): []

## arm `W30` (candidate) -- fail -- net_r/trade 0.1019 beats the baseline's 0.0906 by 0.0113 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 359 | 29.7172 | 0.0828 | 4/6 | 16.4507 | 0.0162 | 5.12 | 0.1979311212768305 | pass |
| SOLUSDT | 357 | 43.2405 | 0.1211 | 5/6 | 16.2426 | 0.0242 | 5.006 | 0.09387553001358384 | pass |
| **pooled** | 716 | 72.9593 | 0.1019 | 5/6 | 27.3936 (seq) | - | - | 0.06400991238756581 | - |

Holm survivors (alpha 0.05): []

