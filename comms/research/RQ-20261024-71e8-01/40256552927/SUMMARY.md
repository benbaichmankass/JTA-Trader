# Stage-0 (synthetic leg) -- squeeze 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short; WIDE: net_r/trade 0.014 beats the baseline's 0.0222 by -0.0082 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 1068 | 38.2136 | 0.0358 | 3/6 | 30.8512 | 0.038 | 0.942 | 0.1845544280343217 | fail |
| NEARUSDT | 1074 | 14.9683 | 0.0139 | 5/6 | 43.28 | 0.0141 | 0.985 | 0.3698935185351562 | pass |
| ATOMUSDT | 1134 | -24.8268 | -0.0219 | 2/6 | 63.0873 | -0.0222 | 0.985 | 0.7088288560961282 | fail |
| FILUSDT | 1105 | 82.7106 | 0.0749 | 4/6 | 32.7811 | 0.0762 | 0.982 | 0.04126448136034881 | pass |
| TRXUSDT | 1094 | -30.9369 | -0.0283 | 3/6 | 75.1742 | -0.0317 | 0.892 | 0.7490959985859489 | fail |
| ETCUSDT | 1172 | 67.2061 | 0.0573 | 4/6 | 39.4727 | 0.0619 | 0.926 | 0.0804019553407549 | pass |
| **pooled** | 6647 | 147.3375 | 0.0222 | 3/6 | 86.6159 (seq) | - | - | 0.09428585159698039 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- fail -- net_r/trade 0.014 beats the baseline's 0.0222 by -0.0082 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 109 | 3.2208 | 0.0295 | 3/6 | 10.5266 | 0.0345 | 0.856 | 0.40203412074237144 | fail |
| NEARUSDT | 90 | -0.2668 | -0.003 | 3/6 | 9.403 | -0.003 | 1.002 | 0.509270256473373 | fail |
| ATOMUSDT | 87 | 11.6814 | 0.1343 | 4/6 | 6.4181 | 0.1374 | 0.978 | 0.1478291024261037 | pass |
| FILUSDT | 138 | 5.5557 | 0.0403 | 5/6 | 16.6024 | 0.0484 | 0.832 | 0.37015551189442175 | pass |
| TRXUSDT | 79 | -1.6352 | -0.0207 | 3/6 | 11.7161 | -0.0212 | 0.976 | 0.5664228718663017 | fail |
| ETCUSDT | 149 | -9.4491 | -0.0634 | 2/6 | 16.3736 | -0.0722 | 0.878 | 0.7335907485077409 | fail |
| **pooled** | 652 | 9.1069 | 0.014 | 4/6 | 29.4033 (seq) | - | - | 0.387799875072145 | - |

Holm survivors (alpha 0.05): []

