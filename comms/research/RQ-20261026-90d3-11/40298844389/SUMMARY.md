# Stage-0 (synthetic leg) -- pullback 4h -- fail

FAIL: B: pooled net_r 113.7355 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3); BE1: net_r/trade 0.0641 beats the baseline's 0.0982 by -0.0341 < the 0.05 materiality bar; LONG: net_r/trade 0.0338 beats the baseline's 0.0982 by -0.0644 < the 0.05 materiality bar; ADX20: net_r/trade 0.1228 beats the baseline's 0.0982 by 0.0246 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 113.7355 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 197 | 32.5853 | 0.1654 | 5/6 | 12.7342 | 0.0186 | 8.902 | 0.09179106479773502 | pass |
| NEARUSDT | 193 | 22.8252 | 0.1183 | 4/6 | 18.8659 | 0.0136 | 8.716 | 0.17565383691280606 | pass |
| ATOMUSDT | 200 | -0.9899 | -0.0049 | 2/6 | 19.5075 | -0.0005 | 9.101 | 0.5160023566693639 | fail |
| FILUSDT | 177 | 4.5763 | 0.0259 | 2/6 | 29.9673 | 0.0027 | 9.644 | 0.41966964365118714 | fail |
| TRXUSDT | 200 | 24.3918 | 0.122 | 4/6 | 18.1157 | 0.0131 | 9.276 | 0.19286291768494657 | pass |
| ETCUSDT | 191 | 30.3481 | 0.1589 | 4/6 | 17.1614 | 0.0161 | 9.897 | 0.13229154301932705 | pass |
| **pooled** | 1158 | 113.7355 | 0.0982 | 5/6 | 51.6836 (seq) | - | - | 0.032979742521526426 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0641 beats the baseline's 0.0982 by -0.0341 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 218 | 28.9791 | 0.1329 | 5/6 | 13.6426 | 0.0171 | 7.758 | 0.11022328161872064 | pass |
| NEARUSDT | 220 | 27.2268 | 0.1238 | 5/6 | 15.8609 | 0.0168 | 7.365 | 0.1297797930770524 | pass |
| ATOMUSDT | 226 | 0.4714 | 0.0021 | 2/6 | 19.165 | 0.0003 | 7.75 | 0.49212853839031234 | fail |
| FILUSDT | 214 | 2.16 | 0.0101 | 1/6 | 35.304 | 0.0013 | 7.596 | 0.46389657111401644 | fail |
| TRXUSDT | 244 | 12.9633 | 0.0531 | 2/6 | 17.5145 | 0.0075 | 7.123 | 0.31887180988918673 | fail |
| ETCUSDT | 213 | 13.7092 | 0.0644 | 2/6 | 25.5165 | 0.0075 | 8.557 | 0.29222651521808063 | fail |
| **pooled** | 1335 | 85.508 | 0.0641 | 4/6 | 51.0715 (seq) | - | - | 0.07849158410183138 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade 0.0338 beats the baseline's 0.0982 by -0.0644 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 142 | -1.9557 | -0.0138 | 2/6 | 18.5681 | -0.002 | 6.859 | 0.5381798979240361 | fail |
| NEARUSDT | 136 | 2.2676 | 0.0167 | 2/6 | 27.2527 | 0.0024 | 6.986 | 0.456150979632678 | fail |
| ATOMUSDT | 154 | -21.9727 | -0.1427 | 2/6 | 43.4744 | -0.0226 | 6.314 | 0.8513760785344391 | fail |
| FILUSDT | 125 | -7.0747 | -0.0566 | 1/6 | 33.9808 | -0.0079 | 7.172 | 0.6424850584039756 | fail |
| TRXUSDT | 127 | 53.8467 | 0.424 | 6/6 | 6.6025 | 0.0412 | 10.285 | 0.01526412672077749 | pass |
| ETCUSDT | 154 | 3.228 | 0.021 | 2/6 | 27.8231 | 0.0031 | 6.708 | 0.4477624817946997 | fail |
| **pooled** | 838 | 28.3388 | 0.0338 | 2/6 | 81.4644 (seq) | - | - | 0.29844473771008684 | - |

Holm survivors (alpha 0.05): []

## arm `ADX20` (candidate) -- fail -- net_r/trade 0.1228 beats the baseline's 0.0982 by 0.0246 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 170 | 21.6082 | 0.1271 | 3/6 | 10.8408 | 0.0139 | 9.155 | 0.1606839908584704 | fail |
| NEARUSDT | 165 | 30.2516 | 0.1833 | 5/6 | 16.8837 | 0.0195 | 9.419 | 0.09497647067488346 | pass |
| ATOMUSDT | 174 | 8.6942 | 0.05 | 4/6 | 21.5582 | 0.0054 | 9.222 | 0.36332843691311223 | pass |
| FILUSDT | 156 | 8.7018 | 0.0558 | 2/6 | 24.6662 | 0.0055 | 10.229 | 0.34330904797146666 | fail |
| TRXUSDT | 170 | 18.8282 | 0.1108 | 1/6 | 16.9091 | 0.0118 | 9.398 | 0.23693511105907733 | fail |
| ETCUSDT | 172 | 35.6076 | 0.207 | 4/6 | 13.9772 | 0.02 | 10.336 | 0.08908129173282914 | pass |
| **pooled** | 1007 | 123.6914 | 0.1228 | 5/6 | 39.4971 (seq) | - | - | 0.017710232783395435 | - |

Holm survivors (alpha 0.05): []

