# Stage-0 (synthetic leg) -- pullback 1d -- fail

FAIL: PB: pooled net_r <= 0 or folds short; PBL: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; PBX: net_r/trade -0.0083 beats the baseline's -0.0622 by 0.0539 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline PB with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `PB` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 32 | -4.7096 | -0.1472 | 3/6 | 11.1321 | -0.0027 | 54.656 | 0.6844197336804407 | fail |
| ETHUSDT | 34 | -10.4413 | -0.3071 | 3/6 | 17.6876 | -0.0065 | 46.912 | 0.8668105276857736 | fail |
| SOLUSDT | 33 | 6.7772 | 0.2054 | 3/6 | 10.0594 | 0.0041 | 50.242 | 0.27713499571874833 | fail |
| XRPUSDT | 27 | -10.404 | -0.3853 | 0/6 | 10.5286 | -0.0057 | 67.519 | 0.9219542232894734 | fail |
| ADAUSDT | 33 | -5.0153 | -0.152 | 3/6 | 11.7208 | -0.0029 | 52.364 | 0.7193887099857894 | fail |
| AVAXUSDT | 27 | 12.2296 | 0.4529 | 5/6 | 5.1957 | 0.0078 | 58.296 | 0.14569578222138774 | pass |
| **pooled** | 186 | -11.5636 | -0.0622 | 2/6 | 48.365 (seq) | - | - | 0.6870853625007077 | - |

Holm survivors (alpha 0.05): []

## arm `PBL` (candidate) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 23 | 11.5475 | 0.5021 | 4/6 | 5.1045 | 0.0103 | 48.652 | 0.14343303550308967 | pass |
| ETHUSDT | 23 | 9.21 | 0.4004 | 3/6 | 7.7574 | 0.0108 | 37.043 | 0.1812371228179614 | fail |
| SOLUSDT | 22 | 15.3067 | 0.6958 | 3/6 | 5.5529 | 0.0181 | 38.5 | 0.0940990572717535 | fail |
| XRPUSDT | 23 | 6.5287 | 0.2839 | 2/6 | 8.2637 | 0.0063 | 45.087 | 0.337228707675528 | fail |
| ADAUSDT | 20 | -4.9868 | -0.2493 | 2/6 | 10.0895 | -0.0064 | 39.0 | 0.7796260974909581 | fail |
| AVAXUSDT | 22 | 12.4727 | 0.5669 | 4/6 | 3.2556 | 0.0185 | 30.591 | 0.1522465551173161 | pass |
| **pooled** | 133 | 50.0786 | 0.3765 | 4/6 | 27.4772 (seq) | - | - | 0.03355672125682051 | - |

Holm survivors (alpha 0.05): []

## arm `PBX` (candidate) -- fail -- net_r/trade -0.0083 beats the baseline's -0.0622 by 0.0539 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 24 | -6.643 | -0.2768 | 2/6 | 10.7317 | -0.0047 | 58.333 | 0.8253221615980028 | fail |
| ETHUSDT | 27 | -4.591 | -0.17 | 3/6 | 14.3097 | -0.0034 | 50.296 | 0.703525739993256 | fail |
| SOLUSDT | 27 | 3.2467 | 0.1202 | 2/6 | 9.3337 | 0.0024 | 50.222 | 0.38629388883616167 | fail |
| XRPUSDT | 23 | 2.7409 | 0.1192 | 1/6 | 11.2175 | 0.0018 | 66.913 | 0.4278449581957536 | fail |
| ADAUSDT | 27 | -7.5159 | -0.2784 | 3/6 | 11.6734 | -0.005 | 55.704 | 0.8453412853070564 | fail |
| AVAXUSDT | 19 | 11.5478 | 0.6078 | 5/6 | 2.08 | 0.0084 | 72.158 | 0.14423541024868197 | indeterminate |
| **pooled** | 147 | -1.2144 | -0.0083 | 2/6 | 51.6941 (seq) | - | - | 0.5194208927335459 | - |

Holm survivors (alpha 0.05): []

