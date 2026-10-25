# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: B: pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3); VOL50: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; VOL75: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 45 | 18.4636 | 0.4103 | 4/6 | 7.3646 | 0.0102 | 40.267 | 0.10554328916297728 | pass |
| ETHUSDT | 46 | 12.7891 | 0.278 | 3/6 | 10.7864 | 0.0072 | 38.717 | 0.16298372694754648 | fail |
| SOLUSDT | 41 | 3.575 | 0.0872 | 3/6 | 8.9755 | 0.0023 | 38.683 | 0.3549037570285778 | fail |
| XRPUSDT | 43 | 7.9747 | 0.1855 | 4/6 | 12.199 | 0.0054 | 34.488 | 0.3055604398788302 | pass |
| ADAUSDT | 44 | 7.5845 | 0.1724 | 4/6 | 7.7063 | 0.0045 | 38.318 | 0.21257525556795098 | pass |
| AVAXUSDT | 37 | 18.0532 | 0.4879 | 4/6 | 5.5615 | 0.0114 | 42.946 | 0.09680278476694565 | pass |
| **pooled** | 256 | 68.4395 | 0.2673 | 4/6 | 25.2343 (seq) | - | - | 0.014467231449741672 | - |

Holm survivors (alpha 0.05): []

## arm `VOL50` (candidate) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 28 | 8.6982 | 0.3106 | 3/6 | 5.2932 | 0.0065 | 47.75 | 0.19286859521401395 | fail |
| ETHUSDT | 28 | 15.5072 | 0.5538 | 3/6 | 7.3215 | 0.0114 | 48.607 | 0.0895257406144051 | fail |
| SOLUSDT | 25 | 16.4436 | 0.6577 | 5/6 | 1.8778 | 0.0134 | 49.12 | 0.025109723651251314 | pass |
| XRPUSDT | 31 | 5.278 | 0.1703 | 3/6 | 8.8664 | 0.0045 | 37.452 | 0.3401761856076225 | fail |
| ADAUSDT | 26 | 15.1809 | 0.5839 | 4/6 | 3.6302 | 0.0126 | 46.346 | 0.0655286113485648 | pass |
| AVAXUSDT | 25 | 9.6559 | 0.3862 | 3/6 | 5.0723 | 0.0098 | 39.32 | 0.2262008794192999 | fail |
| **pooled** | 163 | 70.7635 | 0.4341 | 5/6 | 13.7779 (seq) | - | - | 0.0038146325585620426 | - |

Holm survivors (alpha 0.05): []

## arm `VOL75` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 20 | 15.5179 | 0.7759 | 3/6 | 3.3011 | 0.0138 | 56.15 | 0.08939800614969551 | fail |
| ETHUSDT | 22 | 9.4353 | 0.4289 | 3/6 | 5.9889 | 0.0093 | 46.136 | 0.18202906999471852 | fail |
| SOLUSDT | 22 | 12.9494 | 0.5886 | 4/6 | 4.2502 | 0.0119 | 49.409 | 0.06366969254338484 | pass |
| XRPUSDT | 24 | 2.3965 | 0.0999 | 3/6 | 8.2764 | 0.0027 | 36.875 | 0.4115809251341916 | fail |
| ADAUSDT | 20 | 10.1693 | 0.5085 | 4/6 | 2.5173 | 0.0151 | 33.6 | 0.08218153671506467 | pass |
| AVAXUSDT | 16 | 13.1923 | 0.8245 | 2/6 | 3.0758 | 0.0304 | 27.125 | 0.1457684075944523 | indeterminate |
| **pooled** | 124 | 63.6605 | 0.5134 | 3/6 | 12.0862 (seq) | - | - | 0.004722230037877367 | - |

Holm survivors (alpha 0.05): []

