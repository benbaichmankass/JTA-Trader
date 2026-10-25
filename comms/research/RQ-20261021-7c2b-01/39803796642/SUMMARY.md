# Stage-0 (synthetic leg) -- trend 30m -- fail

FAIL: B: pooled net_r <= 0 or folds short; G50: net_r/trade -0.0054 beats the baseline's -0.031 by 0.0256 < the 0.05 materiality bar; G75: net_r/trade 0.0094 beats the baseline's -0.031 by 0.0404 < the 0.05 materiality bar; G90: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

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

## arm `G50` (candidate) -- fail -- net_r/trade -0.0054 beats the baseline's -0.031 by 0.0256 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 1778 | -55.275 | -0.0311 | 2/6 | 78.6603 | -0.0608 | 0.512 | 0.828902461211315 | fail |
| ETHUSDT | 1739 | -24.6431 | -0.0142 | 3/6 | 65.6755 | -0.0277 | 0.511 | 0.673970758526183 | fail |
| SOLUSDT | 1785 | 17.0322 | 0.0095 | 4/6 | 54.6844 | 0.0183 | 0.523 | 0.37285654864502643 | pass |
| XRPUSDT | 1683 | 0.7028 | 0.0004 | 3/6 | 63.9525 | 0.0009 | 0.473 | 0.49462068958283734 | fail |
| ADAUSDT | 1738 | -23.6836 | -0.0136 | 2/6 | 67.8277 | -0.0276 | 0.493 | 0.675108331685121 | fail |
| AVAXUSDT | 1805 | 28.5756 | 0.0158 | 4/6 | 34.5519 | 0.032 | 0.494 | 0.29348397850067504 | pass |
| **pooled** | 10528 | -57.2956 | -0.0054 | 3/6 | 182.3648 (seq) | - | - | 0.6683268661631795 | - |

Holm survivors (alpha 0.05): []

## arm `G75` (candidate) -- fail -- net_r/trade 0.0094 beats the baseline's -0.031 by 0.0404 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 1095 | 6.1195 | 0.0056 | 3/6 | 47.4984 | 0.009 | 0.621 | 0.44649029742948754 | fail |
| ETHUSDT | 1080 | 43.4395 | 0.0402 | 5/6 | 41.679 | 0.0684 | 0.588 | 0.15468146350247475 | pass |
| SOLUSDT | 1144 | -25.3309 | -0.0221 | 2/6 | 65.3149 | -0.0387 | 0.573 | 0.7347272235291875 | fail |
| XRPUSDT | 1069 | 23.1407 | 0.0216 | 3/6 | 39.3395 | 0.0418 | 0.518 | 0.29064729051925087 | fail |
| ADAUSDT | 1104 | -9.7338 | -0.0088 | 3/6 | 31.427 | -0.0164 | 0.537 | 0.5930711742071382 | fail |
| AVAXUSDT | 1141 | 25.0202 | 0.0219 | 4/6 | 27.8645 | 0.0405 | 0.542 | 0.27021999685261355 | pass |
| **pooled** | 6633 | 62.6538 | 0.0094 | 4/6 | 102.4054 (seq) | - | - | 0.2719373159277674 | - |

Holm survivors (alpha 0.05): []

## arm `G90` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 609 | 35.4622 | 0.0582 | 2/6 | 29.7798 | 0.0795 | 0.733 | 0.14726050676859492 | fail |
| ETHUSDT | 584 | 29.3864 | 0.0503 | 4/6 | 18.5885 | 0.0787 | 0.639 | 0.16424923540468606 | pass |
| SOLUSDT | 637 | 9.925 | 0.0156 | 3/6 | 39.3271 | 0.0245 | 0.637 | 0.37968875127761265 | fail |
| XRPUSDT | 579 | 41.4564 | 0.0716 | 4/6 | 34.9703 | 0.12 | 0.597 | 0.09870979812294461 | pass |
| ADAUSDT | 615 | -16.9653 | -0.0276 | 2/6 | 29.2857 | -0.0476 | 0.579 | 0.6991631013942478 | fail |
| AVAXUSDT | 633 | 6.5779 | 0.0104 | 4/6 | 16.9574 | 0.0183 | 0.569 | 0.41810461954578265 | pass |
| **pooled** | 3657 | 105.8439 | 0.0289 | 3/6 | 77.0819 (seq) | - | - | 0.08928740863813639 | - |

Holm survivors (alpha 0.05): []

