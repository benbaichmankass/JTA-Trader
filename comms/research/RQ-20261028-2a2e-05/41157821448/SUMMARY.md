# Stage-0 (synthetic leg) -- fade 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short; M20: net_r/trade -0.176 beats the baseline's -0.1729 by -0.0031 < the 0.05 materiality bar; TRL: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 2174 | -405.2959 | -0.1864 | 0/6 | 282.4532 | None | None | 0.999999493451556 | fail |
| NEARUSDT | 2253 | -387.2466 | -0.1719 | 0/6 | 244.1825 | None | None | 0.9999984464024257 | fail |
| ATOMUSDT | 2430 | -434.743 | -0.1789 | 0/6 | 258.4676 | None | None | 0.9999996977755692 | fail |
| FILUSDT | 1948 | -202.9476 | -0.1042 | 0/6 | 92.1142 | None | None | 0.99571200842919 | fail |
| TRXUSDT | 2350 | -580.542 | -0.247 | 0/6 | 176.6229 | None | None | 0.9999999999762442 | fail |
| ETCUSDT | 2175 | -294.0769 | -0.1352 | 1/6 | 132.986 | None | None | 0.9998903504567779 | fail |
| **pooled** | 13330 | -2304.8509 | -0.1729 | 0/6 | 2339.0829 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `M20` (candidate) -- fail -- net_r/trade -0.176 beats the baseline's -0.1729 by -0.0031 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 1055 | -187.1839 | -0.1774 | 0/6 | 94.4694 | None | None | 0.9999993427553275 | fail |
| NEARUSDT | 1200 | -135.3865 | -0.1128 | 0/6 | 60.2541 | None | None | 0.9994600215962433 | fail |
| ATOMUSDT | 1259 | -236.9461 | -0.1882 | 0/6 | 143.7492 | None | None | 0.9999999910604189 | fail |
| FILUSDT | 1023 | -140.968 | -0.1378 | 0/6 | 72.1268 | None | None | 0.9999306064195513 | fail |
| TRXUSDT | 1263 | -334.3909 | -0.2648 | 0/6 | 75.3254 | None | None | 0.9999999999999819 | fail |
| ETCUSDT | 1168 | -191.2256 | -0.1637 | 0/6 | 91.9335 | None | None | 0.9999994446792546 | fail |
| **pooled** | 6968 | -1226.099 | -0.176 | 0/6 | 1239.9352 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 802 | -10.6548 | -0.0133 | 3/6 | 47.4098 | None | None | 0.5685306373818754 | fail |
| NEARUSDT | 879 | -110.905 | -0.1262 | 1/6 | 67.1036 | None | None | 0.9672275487998143 | fail |
| ATOMUSDT | 973 | -169.3664 | -0.1741 | 0/6 | 108.9908 | None | None | 0.9965512221937363 | fail |
| FILUSDT | 775 | -86.65 | -0.1118 | 1/6 | 46.239 | None | None | 0.9446169750797848 | fail |
| TRXUSDT | 981 | -128.5746 | -0.1311 | 1/6 | 46.951 | None | None | 0.9521766223558527 | fail |
| ETCUSDT | 889 | -95.3982 | -0.1073 | 1/6 | 108.7154 | None | None | 0.91138590351034 | fail |
| **pooled** | 5299 | -601.5457 | -0.1135 | 1/6 | 624.1233 (seq) | - | - | 0.9999235528063664 | - |

Holm survivors (alpha 0.05): []

