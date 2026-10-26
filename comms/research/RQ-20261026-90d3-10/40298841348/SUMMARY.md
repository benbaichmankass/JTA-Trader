# Stage-0 (synthetic leg) -- fade 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; M15: net_r/trade -0.1827 beats the baseline's -0.1161 by -0.0666 < the 0.05 materiality bar; M25: net_r/trade -0.137 beats the baseline's -0.1161 by -0.0209 < the 0.05 materiality bar; TRL: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 1088 | -173.0707 | -0.1591 | 0/6 | 93.1075 | None | None | 0.9989117245453762 | fail |
| LINKUSDT | 1208 | -109.5938 | -0.0907 | 2/6 | 95.4433 | None | None | 0.9592855092416961 | fail |
| LTCUSDT | 1150 | -132.1295 | -0.1149 | 2/6 | 74.058 | None | None | 0.9856385143644237 | fail |
| BCHUSDT | 1064 | -75.6607 | -0.0711 | 1/6 | 73.4395 | None | None | 0.9064339688662979 | fail |
| DOTUSDT | 1163 | -168.2205 | -0.1446 | 1/6 | 102.2973 | None | None | 0.9977071007426521 | fail |
| DOGEUSDT | 994 | -115.5051 | -0.1162 | 1/6 | 73.9379 | None | None | 0.9844519134526052 | fail |
| **pooled** | 6667 | -774.1777 | -0.1161 | 0/6 | 794.2823 (seq) | - | - | 0.999999969012567 | - |

Holm survivors (alpha 0.05): []

## arm `M15` (candidate) -- fail -- net_r/trade -0.1827 beats the baseline's -0.1161 by -0.0666 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 244 | -40.2591 | -0.165 | 0/6 | 21.931 | None | None | 0.9874300013127216 | fail |
| LINKUSDT | 203 | -62.1507 | -0.3062 | 0/6 | 49.0513 | None | None | 0.9999772039926973 | fail |
| LTCUSDT | 239 | -23.6221 | -0.0988 | 1/6 | 28.9506 | None | None | 0.9089330740890085 | fail |
| BCHUSDT | 216 | -17.281 | -0.08 | 2/6 | 14.4248 | None | None | 0.8683271346283198 | fail |
| DOTUSDT | 185 | -52.4835 | -0.2837 | 1/6 | 40.8581 | None | None | 0.9998723137696837 | fail |
| DOGEUSDT | 238 | -46.222 | -0.1942 | 1/6 | 46.1057 | None | None | 0.9952138134828467 | fail |
| **pooled** | 1325 | -242.0185 | -0.1827 | 0/6 | 247.5504 (seq) | - | - | 0.9999999990071706 | - |

Holm survivors (alpha 0.05): []

## arm `M25` (candidate) -- fail -- net_r/trade -0.137 beats the baseline's -0.1161 by -0.0209 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 900 | -163.6276 | -0.1818 | 0/6 | 76.4599 | None | None | 0.9999965753573534 | fail |
| LINKUSDT | 938 | -115.6476 | -0.1233 | 0/6 | 72.0618 | None | None | 0.998743344312089 | fail |
| LTCUSDT | 979 | -125.637 | -0.1283 | 0/6 | 54.9689 | None | None | 0.9995014511137377 | fail |
| BCHUSDT | 873 | -42.6177 | -0.0488 | 2/6 | 57.9553 | None | None | 0.882177026753875 | fail |
| DOTUSDT | 911 | -151.16 | -0.1659 | 0/6 | 93.6978 | None | None | 0.999987172706655 | fail |
| DOGEUSDT | 841 | -146.7039 | -0.1744 | 0/6 | 102.4772 | None | None | 0.9999932590846723 | fail |
| **pooled** | 5442 | -745.3966 | -0.137 | 0/6 | 753.5346 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 428 | -37.8785 | -0.0885 | 2/6 | 37.2644 | None | None | 0.81660259494964 | fail |
| LINKUSDT | 464 | 112.1701 | 0.2417 | 6/6 | 26.7903 | None | None | 0.03941455127243529 | pass |
| LTCUSDT | 475 | -16.4188 | -0.0346 | 1/6 | 51.0103 | None | None | 0.6374291059877787 | fail |
| BCHUSDT | 428 | 48.1228 | 0.1124 | 2/6 | 26.2402 | None | None | 0.15036232143045902 | fail |
| DOTUSDT | 432 | 4.6654 | 0.0108 | 3/6 | 35.8642 | None | None | 0.4629105795850115 | fail |
| DOGEUSDT | 446 | -119.4392 | -0.2678 | 0/6 | 102.3345 | None | None | 0.9991410943832107 | fail |
| **pooled** | 2673 | -8.7805 | -0.0033 | 2/6 | 171.2241 (seq) | - | - | 0.5294369813823866 | - |

Holm survivors (alpha 0.05): []

