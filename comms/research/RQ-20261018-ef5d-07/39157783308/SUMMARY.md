# Stage-0 (synthetic leg) -- trend 30m -- indeterminate

INDETERMINATE: B: pooled net_r <= 0 or folds short; V50: pooled n 33 < floor 88: underpowered, never FAIL on thin n; V75: pooled n 33 < floor 88: underpowered, never FAIL on thin n; V90: pooled n 33 < floor 88: underpowered, never FAIL on thin n. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 2672 | -192.129 | -0.0719 | 0/6 | 225.7772 | -0.1664 | 0.432 | 0.9961552081162719 | fail |
| ETHUSDT | 2694 | -101.949 | -0.0378 | 1/6 | 127.8465 | -0.0901 | 0.42 | 0.9397656933649015 | fail |
| SOLUSDT | 2755 | -78.4299 | -0.0285 | 2/6 | 124.5169 | -0.0633 | 0.45 | 0.893533976833872 | fail |
| XRPUSDT | 2700 | -111.6084 | -0.0413 | 1/6 | 145.2489 | -0.1003 | 0.412 | 0.9455851379326303 | fail |
| ADAUSDT | 2713 | -49.1239 | -0.0181 | 2/6 | 112.7295 | -0.0412 | 0.439 | 0.7784372571795759 | fail |
| AVAXUSDT | 2838 | 25.9664 | 0.0091 | 4/6 | 51.6372 | 0.0214 | 0.427 | 0.34822770726434027 | pass |
| **pooled** | 16372 | -507.2778 | -0.031 | 1/6 | 620.1481 (seq) | - | - | 0.9990201030797324 | - |

Holm survivors (alpha 0.05): []

## arm `V50` (candidate) -- indeterminate -- pooled n 33 < floor 88: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 5 | 5.7622 | 1.1524 | 1/6 | 0.744 | 3.0732 | 0.375 | 0.1313745723442576 | indeterminate |
| ETHUSDT | 7 | 2.3205 | 0.3315 | 1/6 | 1.7141 | 1.3583 | 0.244 | 0.32247537931130044 | indeterminate |
| SOLUSDT | 6 | -0.8334 | -0.1389 | 0/6 | 2.0201 | -0.4445 | 0.312 | 0.634491272010468 | indeterminate |
| XRPUSDT | 3 | 0.3283 | 0.1094 | 1/6 | 0.3504 | 0.927 | 0.118 | 0.37480057691273405 | indeterminate |
| ADAUSDT | 5 | 1.1464 | 0.2293 | 1/6 | 1.1979 | 0.775 | 0.296 | 0.35119281606366426 | indeterminate |
| AVAXUSDT | 7 | -3.0284 | -0.4326 | 0/6 | 3.0284 | -1.3844 | 0.312 | 0.9353514773802458 | indeterminate |
| **pooled** | 33 | 5.6954 | 0.1726 | 1/6 | 5.7257 (seq) | - | - | 0.23176882395215548 | - |

Holm survivors (alpha 0.05): []

## arm `V75` (candidate) -- indeterminate -- pooled n 33 < floor 88: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 5 | 5.7622 | 1.1524 | 1/6 | 0.744 | 3.0732 | 0.375 | 0.1313745723442576 | indeterminate |
| ETHUSDT | 7 | 2.3205 | 0.3315 | 1/6 | 1.7141 | 1.3583 | 0.244 | 0.32247537931130044 | indeterminate |
| SOLUSDT | 6 | -0.8334 | -0.1389 | 0/6 | 2.0201 | -0.4445 | 0.312 | 0.634491272010468 | indeterminate |
| XRPUSDT | 3 | 0.3283 | 0.1094 | 1/6 | 0.3504 | 0.927 | 0.118 | 0.37480057691273405 | indeterminate |
| ADAUSDT | 5 | 1.1464 | 0.2293 | 1/6 | 1.1979 | 0.775 | 0.296 | 0.35119281606366426 | indeterminate |
| AVAXUSDT | 7 | -3.0284 | -0.4326 | 0/6 | 3.0284 | -1.3844 | 0.312 | 0.9353514773802458 | indeterminate |
| **pooled** | 33 | 5.6954 | 0.1726 | 1/6 | 5.7257 (seq) | - | - | 0.23176882395215548 | - |

Holm survivors (alpha 0.05): []

## arm `V90` (candidate) -- indeterminate -- pooled n 33 < floor 88: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 5 | 5.7622 | 1.1524 | 1/6 | 0.744 | 3.0732 | 0.375 | 0.1313745723442576 | indeterminate |
| ETHUSDT | 7 | 2.3205 | 0.3315 | 1/6 | 1.7141 | 1.3583 | 0.244 | 0.32247537931130044 | indeterminate |
| SOLUSDT | 6 | -0.8334 | -0.1389 | 0/6 | 2.0201 | -0.4445 | 0.312 | 0.634491272010468 | indeterminate |
| XRPUSDT | 3 | 0.3283 | 0.1094 | 1/6 | 0.3504 | 0.927 | 0.118 | 0.37480057691273405 | indeterminate |
| ADAUSDT | 5 | 1.1464 | 0.2293 | 1/6 | 1.1979 | 0.775 | 0.296 | 0.35119281606366426 | indeterminate |
| AVAXUSDT | 7 | -3.0284 | -0.4326 | 0/6 | 3.0284 | -1.3844 | 0.312 | 0.9353514773802458 | indeterminate |
| **pooled** | 33 | 5.6954 | 0.1726 | 1/6 | 5.7257 (seq) | - | - | 0.23176882395215548 | - |

Holm survivors (alpha 0.05): []

