# Stage-0 (synthetic leg) -- pullback 1d -- fail

FAIL: B: pooled net_r <= 0 or folds short; A15: net_r/trade 0.0199 beats the baseline's 0.0099 by 0.01 < the 0.05 materiality bar; L100: pooled net_r <= 0 or folds short; L100A: pooled passes but only 1 of 6 powered cells pass (< 3): one symbol's edge. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 33 | 4.3673 | 0.1323 | 3/6 | 11.1321 | 0.0023 | 58.667 | 0.3492727726954246 | fail |
| ETHUSDT | 37 | -7.8321 | -0.2117 | 2/6 | 17.6876 | -0.0046 | 46.216 | 0.7687228496262157 | fail |
| SOLUSDT | 33 | 6.9095 | 0.2094 | 3/6 | 10.0594 | 0.0042 | 50.152 | 0.27326103501724097 | fail |
| XRPUSDT | 29 | -11.7778 | -0.4061 | 1/6 | 11.7778 | -0.0062 | 65.828 | 0.9448106812694184 | fail |
| ADAUSDT | 37 | -2.0718 | -0.056 | 3/6 | 11.7208 | -0.0011 | 49.0 | 0.5873548439823253 | fail |
| AVAXUSDT | 27 | 12.3458 | 0.4573 | 5/6 | 5.1957 | 0.0079 | 58.185 | 0.14326733648285955 | pass |
| **pooled** | 196 | 1.9408 | 0.0099 | 3/6 | 48.365 (seq) | - | - | 0.4692005844554895 | - |

Holm survivors (alpha 0.05): []

## arm `A15` (candidate) -- fail -- net_r/trade 0.0199 beats the baseline's 0.0099 by 0.01 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 33 | 4.3673 | 0.1323 | 3/6 | 11.1321 | 0.0023 | 58.667 | 0.3492727726954246 | fail |
| ETHUSDT | 37 | -7.8321 | -0.2117 | 2/6 | 17.6876 | -0.0046 | 46.216 | 0.7687228496262157 | fail |
| SOLUSDT | 32 | 7.9489 | 0.2484 | 3/6 | 9.02 | 0.0049 | 50.719 | 0.24292379325483981 | fail |
| XRPUSDT | 28 | -10.7462 | -0.3838 | 1/6 | 10.7462 | -0.0057 | 67.25 | 0.928618267636993 | fail |
| ADAUSDT | 37 | -2.0718 | -0.056 | 3/6 | 11.7208 | -0.0011 | 49.0 | 0.5873548439823253 | fail |
| AVAXUSDT | 27 | 12.194 | 0.4516 | 5/6 | 5.1957 | 0.0079 | 56.963 | 0.14659122464104013 | pass |
| **pooled** | 194 | 3.8601 | 0.0199 | 3/6 | 46.294 (seq) | - | - | 0.4388330077846923 | - |

Holm survivors (alpha 0.05): []

## arm `L100` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 26 | 11.9205 | 0.4585 | 5/6 | 5.3314 | 0.0058 | 78.462 | 0.12926957193627242 | pass |
| ETHUSDT | 38 | 1.7676 | 0.0465 | 2/6 | 12.5996 | 0.001 | 48.132 | 0.44426857197615605 | fail |
| SOLUSDT | 29 | 11.3476 | 0.3913 | 3/6 | 5.9303 | 0.0062 | 63.207 | 0.1611433420891607 | fail |
| XRPUSDT | 32 | -1.3609 | -0.0425 | 2/6 | 10.2632 | -0.0007 | 59.844 | 0.5464857944271244 | fail |
| ADAUSDT | 31 | -2.7916 | -0.0901 | 2/6 | 6.0888 | -0.0015 | 60.323 | 0.6392579308738979 | fail |
| AVAXUSDT | 31 | 0.6015 | 0.0194 | 2/6 | 8.6602 | 0.0004 | 54.742 | 0.47901613181037184 | fail |
| **pooled** | 187 | 21.485 | 0.1149 | 3/6 | 29.9141 (seq) | - | - | 0.20905972303700066 | - |

Holm survivors (alpha 0.05): []

## arm `L100A` (candidate) -- fail -- pooled passes but only 1 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 26 | 11.9205 | 0.4585 | 5/6 | 5.3314 | 0.0058 | 78.462 | 0.12926957193627242 | pass |
| ETHUSDT | 37 | 3.765 | 0.1018 | 2/6 | 10.6022 | 0.0021 | 48.676 | 0.38171783091702954 | fail |
| SOLUSDT | 28 | 12.3811 | 0.4422 | 3/6 | 5.9246 | 0.0068 | 65.357 | 0.13877628461970976 | fail |
| XRPUSDT | 31 | -0.3292 | -0.0106 | 2/6 | 9.2315 | -0.0002 | 60.903 | 0.5113002149482935 | fail |
| ADAUSDT | 30 | 2.4307 | 0.081 | 3/6 | 4.5378 | 0.0013 | 63.467 | 0.38612431474480813 | fail |
| AVAXUSDT | 29 | 2.6739 | 0.0922 | 2/6 | 8.1033 | 0.0016 | 58.0 | 0.4068411470672218 | fail |
| **pooled** | 181 | 32.8422 | 0.1814 | 4/6 | 27.0493 (seq) | - | - | 0.10796272447185484 | - |

Holm survivors (alpha 0.05): []

