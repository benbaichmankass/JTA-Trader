# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm TR8 passes (pooled net_r 86.581); 1 of 3 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline D20 with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `D20` (baseline) -- pass -- pooled net_r 68.4395 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

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

## arm `TR8` (candidate) -- pass -- pooled net_r 86.581 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); beats the baseline by 0.1722 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 30 | 16.8206 | 0.5607 | 2/6 | 6.3414 | 0.0084 | 66.467 | 0.18952062195229674 | fail |
| ETHUSDT | 36 | 10.0466 | 0.2791 | 3/6 | 6.804 | 0.0053 | 52.472 | 0.23300139329690772 | fail |
| SOLUSDT | 30 | 20.7199 | 0.6907 | 4/6 | 6.2545 | 0.0126 | 54.967 | 0.10193815786072746 | pass |
| XRPUSDT | 36 | 2.1453 | 0.0596 | 3/6 | 10.641 | 0.0013 | 46.639 | 0.44877023464112814 | fail |
| ADAUSDT | 38 | 19.2045 | 0.5054 | 5/6 | 9.8833 | 0.0109 | 46.447 | 0.17878413298342027 | pass |
| AVAXUSDT | 27 | 17.6438 | 0.6535 | 4/6 | 5.0723 | 0.0098 | 66.926 | 0.07678684767415839 | pass |
| **pooled** | 197 | 86.581 | 0.4395 | 4/6 | 21.3428 (seq) | - | - | 0.0159611831142056 | - |

Holm survivors (alpha 0.05): []

## arm `TS60` (candidate) -- fail -- net_r/trade 0.2591 beats the baseline's 0.2673 by -0.0082 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 58 | 16.6552 | 0.2872 | 4/6 | 7.3646 | 0.0108 | 26.707 | 0.13668841126749176 | pass |
| ETHUSDT | 56 | 18.0811 | 0.3229 | 4/6 | 8.7258 | 0.0113 | 28.643 | 0.07057523289774348 | pass |
| SOLUSDT | 48 | 14.8119 | 0.3086 | 4/6 | 4.1215 | 0.0102 | 30.312 | 0.08865021983235705 | pass |
| XRPUSDT | 60 | 0.6989 | 0.0116 | 3/6 | 14.7799 | 0.0005 | 21.517 | 0.4811178902413046 | fail |
| ADAUSDT | 57 | 3.6621 | 0.0642 | 4/6 | 11.0609 | 0.0024 | 26.702 | 0.3502268749374263 | pass |
| AVAXUSDT | 48 | 30.8323 | 0.6423 | 3/6 | 6.7029 | 0.0211 | 30.458 | 0.0727855990745952 | fail |
| **pooled** | 327 | 84.7408 | 0.2591 | 5/6 | 27.3922 (seq) | - | - | 0.007989164231948556 | - |

Holm survivors (alpha 0.05): []

