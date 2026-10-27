# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r 145.4049 > 0 with 5 folds positive and 7 of 12 powered cells pass (breadth floor 6); BOTH: net_r/trade 0.1276 beats the baseline's 0.1685 by -0.0409 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 145.4049 > 0 with 5 folds positive and 7 of 12 powered cells pass (breadth floor 6)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 72 | 5.8504 | 0.0813 | 2/6 | 7.1319 | 0.0575 | 1.414 | 0.2997529049979478 | fail |
| DOGEUSDT | 75 | 5.0781 | 0.0677 | 3/6 | 8.1623 | 0.0478 | 1.418 | 0.32370639982546995 | fail |
| LINKUSDT | 65 | 8.4205 | 0.1295 | 3/6 | 6.0868 | 0.0676 | 1.915 | 0.22117737287339695 | fail |
| LTCUSDT | 72 | 18.6887 | 0.2596 | 4/6 | 5.1501 | 0.1168 | 2.222 | 0.07994280992804337 | pass |
| BCHUSDT | 80 | 21.1796 | 0.2647 | 6/6 | 6.9877 | 0.1368 | 1.935 | 0.08787330581340752 | pass |
| DOTUSDT | 71 | 13.5787 | 0.1912 | 5/6 | 3.4584 | 0.0867 | 2.207 | 0.1084863167474166 | pass |
| AVAXUSDT | 78 | 13.2441 | 0.1698 | 2/6 | 6.5747 | 0.0964 | 1.761 | 0.20483743297763524 | fail |
| NEARUSDT | 56 | 22.1967 | 0.3964 | 4/6 | 2.5486 | 0.2006 | 1.976 | 0.01799574676502016 | pass |
| ATOMUSDT | 70 | -6.7491 | -0.0964 | 2/6 | 12.5451 | -0.0506 | 1.907 | 0.7473159156172767 | fail |
| FILUSDT | 69 | 24.0314 | 0.3483 | 5/6 | 4.6479 | 0.1657 | 2.102 | 0.053053024896361656 | pass |
| TRXUSDT | 80 | 2.8007 | 0.035 | 5/6 | 7.6898 | 0.025 | 1.4 | 0.4085798969478384 | pass |
| ETCUSDT | 75 | 17.0838 | 0.2278 | 5/6 | 6.5069 | 0.149 | 1.529 | 0.1268039998789227 | pass |
| **pooled** | 863 | 145.4049 | 0.1685 | 5/6 | 31.4856 (seq) | - | - | 0.00048814088217346066 | - |

Holm survivors (alpha 0.05): []

## arm `BOTH` (candidate) -- fail -- net_r/trade 0.1276 beats the baseline's 0.1685 by -0.0409 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 169 | 35.6819 | 0.2111 | 5/6 | 8.692 | 0.1349 | 1.565 | 0.03851318596659831 | pass |
| DOGEUSDT | 157 | 17.9836 | 0.1145 | 3/6 | 15.2809 | 0.0951 | 1.205 | 0.19224116155404763 | fail |
| LINKUSDT | 157 | 0.9332 | 0.0059 | 3/6 | 11.9126 | 0.0035 | 1.719 | 0.4767614315540939 | fail |
| LTCUSDT | 156 | 38.2942 | 0.2455 | 6/6 | 7.2104 | 0.1327 | 1.849 | 0.019334746505695204 | pass |
| BCHUSDT | 171 | 20.6328 | 0.1207 | 4/6 | 13.3747 | 0.0697 | 1.732 | 0.1649172625782831 | pass |
| DOTUSDT | 154 | 9.4827 | 0.0616 | 3/6 | 13.6346 | 0.0325 | 1.895 | 0.2718696831322444 | fail |
| AVAXUSDT | 161 | 16.5246 | 0.1026 | 4/6 | 9.5759 | 0.0566 | 1.813 | 0.20121770924914034 | pass |
| NEARUSDT | 128 | 33.7933 | 0.264 | 5/6 | 5.4426 | 0.146 | 1.809 | 0.025560970938867146 | pass |
| ATOMUSDT | 143 | -3.2971 | -0.0231 | 3/6 | 16.6712 | -0.0133 | 1.731 | 0.5917188315040693 | fail |
| FILUSDT | 160 | 8.4134 | 0.0526 | 4/6 | 18.4458 | 0.033 | 1.596 | 0.3281742052242236 | pass |
| TRXUSDT | 175 | 26.0087 | 0.1486 | 5/6 | 11.966 | 0.0983 | 1.512 | 0.11711681125483703 | pass |
| ETCUSDT | 152 | 35.8078 | 0.2356 | 5/6 | 10.7445 | 0.1654 | 1.424 | 0.05242449083673417 | pass |
| **pooled** | 1883 | 240.2612 | 0.1276 | 5/6 | 63.618 (seq) | - | - | 0.00012643971503226923 | - |

Holm survivors (alpha 0.05): []

