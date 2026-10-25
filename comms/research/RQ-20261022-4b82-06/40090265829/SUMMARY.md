# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; LONG: net_r/trade -0.0134 beats the baseline's 0.0091 by -0.0225 < the 0.05 materiality bar; LONGA: net_r/trade 0.0044 beats the baseline's 0.0091 by -0.0047 < the 0.05 materiality bar; ADX: net_r/trade -0.0089 beats the baseline's 0.0091 by -0.018 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 402 | 4.0737 | 0.0101 | 3/6 | 27.8344 | 0.0034 | 3.006 | 0.4386536587516722 | fail |
| LINKUSDT | 414 | -2.6144 | -0.0063 | 3/6 | 19.8954 | -0.002 | 3.157 | 0.5425191795874167 | fail |
| DOGEUSDT | 361 | 32.484 | 0.09 | 5/6 | 12.1395 | 0.0297 | 3.027 | 0.10389564213176183 | pass |
| LTCUSDT | 384 | -26.2286 | -0.0683 | 1/6 | 33.0718 | -0.0221 | 3.092 | 0.8803404962773794 | fail |
| BCHUSDT | 370 | 29.1577 | 0.0788 | 4/6 | 18.536 | 0.0244 | 3.231 | 0.13110232259452426 | pass |
| DOTUSDT | 367 | -15.895 | -0.0433 | 2/6 | 26.7893 | -0.0119 | 3.646 | 0.7627974431457611 | fail |
| **pooled** | 2298 | 20.9764 | 0.0091 | 3/6 | 59.9008 (seq) | - | - | 0.36366982369872114 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade -0.0134 beats the baseline's 0.0091 by -0.0225 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 244 | 15.9383 | 0.0653 | 3/6 | 21.0597 | 0.0224 | 2.913 | 0.22369018072109909 | fail |
| LINKUSDT | 260 | -12.0443 | -0.0463 | 3/6 | 30.0448 | -0.0166 | 2.795 | 0.7450297212777108 | fail |
| DOGEUSDT | 232 | 6.7448 | 0.0291 | 2/6 | 18.735 | 0.0154 | 1.887 | 0.37662015494539947 | fail |
| LTCUSDT | 243 | -23.2378 | -0.0956 | 1/6 | 33.0967 | -0.0358 | 2.674 | 0.9154537808945861 | fail |
| BCHUSDT | 235 | 0.8976 | 0.0038 | 2/6 | 18.6246 | 0.0014 | 2.645 | 0.4813430244042256 | fail |
| DOTUSDT | 230 | -7.7108 | -0.0335 | 3/6 | 29.823 | -0.0122 | 2.741 | 0.6627685649151713 | fail |
| **pooled** | 1444 | -19.4129 | -0.0134 | 3/6 | 109.1899 (seq) | - | - | 0.6599989239037856 | - |

Holm survivors (alpha 0.05): []

## arm `LONGA` (candidate) -- fail -- net_r/trade 0.0044 beats the baseline's 0.0091 by -0.0047 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 185 | 23.0533 | 0.1246 | 5/6 | 13.3542 | 0.0414 | 3.009 | 0.11623252677303486 | pass |
| LINKUSDT | 203 | -16.7628 | -0.0826 | 1/6 | 28.9517 | -0.029 | 2.851 | 0.8475798264267771 | fail |
| DOGEUSDT | 175 | 12.5367 | 0.0716 | 3/6 | 16.439 | 0.0399 | 1.793 | 0.24436783280206353 | fail |
| LTCUSDT | 189 | -22.3329 | -0.1182 | 1/6 | 29.6144 | -0.0442 | 2.675 | 0.9605784569739022 | fail |
| BCHUSDT | 178 | 11.9978 | 0.0674 | 5/6 | 21.4703 | 0.0241 | 2.8 | 0.2552349007649648 | pass |
| DOTUSDT | 182 | -3.6266 | -0.0199 | 3/6 | 22.4953 | -0.0074 | 2.705 | 0.583713445674183 | fail |
| **pooled** | 1112 | 4.866 | 0.0044 | 2/6 | 69.6735 (seq) | - | - | 0.4536743982375019 | - |

Holm survivors (alpha 0.05): []

## arm `ADX` (candidate) -- fail -- net_r/trade -0.0089 beats the baseline's 0.0091 by -0.018 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 318 | 17.0575 | 0.0536 | 5/6 | 16.3021 | 0.0178 | 3.007 | 0.24955700338219533 | pass |
| LINKUSDT | 317 | -24.8277 | -0.0783 | 2/6 | 37.2467 | -0.0226 | 3.463 | 0.8995583412310486 | fail |
| DOGEUSDT | 290 | 25.8831 | 0.0893 | 6/6 | 10.9918 | 0.0288 | 3.103 | 0.12003749915164025 | pass |
| LTCUSDT | 302 | -37.0911 | -0.1228 | 1/6 | 38.1001 | -0.0397 | 3.093 | 0.9761940988359651 | fail |
| BCHUSDT | 297 | 10.1576 | 0.0342 | 3/6 | 27.3731 | 0.0104 | 3.287 | 0.3283304791010889 | fail |
| DOTUSDT | 295 | -7.2788 | -0.0247 | 2/6 | 24.1608 | -0.0072 | 3.429 | 0.6398807042426967 | fail |
| **pooled** | 1819 | -16.099 | -0.0089 | 2/6 | 53.3259 (seq) | - | - | 0.6199752315793745 | - |

Holm survivors (alpha 0.05): []

