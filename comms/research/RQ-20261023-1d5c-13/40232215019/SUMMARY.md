# Stage-0 (synthetic leg) -- fade 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; M15: net_r/trade -0.2086 beats the baseline's -0.1165 by -0.0921 < the 0.05 materiality bar; M25: net_r/trade -0.1648 beats the baseline's -0.1165 by -0.0483 < the 0.05 materiality bar; TRL: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 1094 | -150.8415 | -0.1379 | 1/6 | 121.9531 | None | None | 0.9962670980673591 | fail |
| SOLUSDT | 1099 | -239.618 | -0.218 | 0/6 | 186.462 | None | None | 0.9999875976386359 | fail |
| XRPUSDT | 1017 | -143.389 | -0.141 | 0/6 | 101.4348 | None | None | 0.9957315383955196 | fail |
| ADAUSDT | 1085 | -47.0482 | -0.0434 | 4/6 | 70.3869 | None | None | 0.7917993321764059 | fail |
| AVAXUSDT | 1084 | -76.9547 | -0.071 | 3/6 | 78.0722 | None | None | 0.8946951819524215 | fail |
| LINKUSDT | 1208 | -109.5938 | -0.0907 | 2/6 | 95.4433 | None | None | 0.9592855092416961 | fail |
| **pooled** | 6587 | -767.446 | -0.1165 | 0/6 | 792.5113 (seq) | - | - | 0.9999999597579432 | - |

Holm survivors (alpha 0.05): []

## arm `M15` (candidate) -- fail -- net_r/trade -0.2086 beats the baseline's -0.1165 by -0.0921 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 179 | -16.281 | -0.091 | 2/6 | 23.1659 | None | None | 0.8791481842809088 | fail |
| SOLUSDT | 197 | -41.2021 | -0.2091 | 0/6 | 38.319 | None | None | 0.995079152265188 | fail |
| XRPUSDT | 200 | -42.9688 | -0.2148 | 1/6 | 32.5232 | None | None | 0.9981477837348707 | fail |
| ADAUSDT | 217 | -25.8979 | -0.1193 | 2/6 | 22.2458 | None | None | 0.9421412703690216 | fail |
| AVAXUSDT | 181 | -56.971 | -0.3148 | 0/6 | 45.0169 | None | None | 0.9999692159564639 | fail |
| LINKUSDT | 203 | -62.1507 | -0.3062 | 0/6 | 49.0513 | None | None | 0.9999772039926973 | fail |
| **pooled** | 1177 | -245.4696 | -0.2086 | 0/6 | 249.502 (seq) | - | - | 0.9999999999838359 | - |

Holm survivors (alpha 0.05): []

## arm `M25` (candidate) -- fail -- net_r/trade -0.1648 beats the baseline's -0.1165 by -0.0483 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 816 | -60.7787 | -0.0745 | 2/6 | 33.6059 | None | None | 0.9629240929000109 | fail |
| SOLUSDT | 864 | -164.5017 | -0.1904 | 0/6 | 120.4907 | None | None | 0.9999987190026104 | fail |
| XRPUSDT | 796 | -180.8218 | -0.2272 | 0/6 | 117.801 | None | None | 0.999999994556064 | fail |
| ADAUSDT | 857 | -129.4232 | -0.151 | 0/6 | 82.3827 | None | None | 0.9999000106094733 | fail |
| AVAXUSDT | 816 | -186.9521 | -0.2291 | 0/6 | 146.2503 | None | None | 0.9999999870758398 | fail |
| LINKUSDT | 938 | -115.6476 | -0.1233 | 0/6 | 72.0618 | None | None | 0.998743344312089 | fail |
| **pooled** | 5087 | -838.1227 | -0.1648 | 0/6 | 842.9732 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 399 | -5.7052 | -0.0143 | 3/6 | 18.8073 | None | None | 0.5580236950632659 | fail |
| SOLUSDT | 410 | -58.8153 | -0.1435 | 1/6 | 70.8795 | None | None | 0.9438025060079 | fail |
| XRPUSDT | 408 | -53.2054 | -0.1304 | 2/6 | 55.8692 | None | None | 0.8890427968732999 | fail |
| ADAUSDT | 428 | -13.1026 | -0.0306 | 3/6 | 56.3038 | None | None | 0.6123085250191733 | fail |
| AVAXUSDT | 370 | -58.7389 | -0.1588 | 2/6 | 49.7057 | None | None | 0.934833350691857 | fail |
| LINKUSDT | 464 | 112.1701 | 0.2417 | 6/6 | 26.7903 | None | None | 0.03941455127243529 | pass |
| **pooled** | 2479 | -77.3957 | -0.0312 | 2/6 | 125.4818 (seq) | - | - | 0.7558233818778348 | - |

Holm survivors (alpha 0.05): []

