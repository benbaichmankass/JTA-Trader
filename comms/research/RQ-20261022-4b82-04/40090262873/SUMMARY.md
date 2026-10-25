# Stage-0 (synthetic leg) -- fade 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short; MID: net_r/trade -0.1741 beats the baseline's -0.163 by -0.0111 < the 0.05 materiality bar; TRL: pooled net_r <= 0 or folds short; TP1: net_r/trade -0.1624 beats the baseline's -0.163 by 0.0006 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 2168 | -305.3572 | -0.1408 | 0/6 | 162.6835 | None | None | 0.9999078331468453 | fail |
| XRPUSDT | 2053 | -289.8412 | -0.1412 | 0/6 | 86.6925 | None | None | 0.9999027380559832 | fail |
| LINKUSDT | 2382 | -398.0396 | -0.1671 | 0/6 | 257.3066 | None | None | 0.9999985856257692 | fail |
| DOGEUSDT | 2035 | -368.6102 | -0.1811 | 0/6 | 219.5944 | None | None | 0.9999995149898532 | fail |
| BNBUSDT | 2204 | -403.268 | -0.183 | 0/6 | 131.1225 | None | None | 0.9999996130292697 | fail |
| AVAXUSDT | 2169 | -355.9367 | -0.1641 | 0/6 | 282.4532 | None | None | 0.999991718057705 | fail |
| **pooled** | 13011 | -2121.0506 | -0.163 | 0/6 | 2144.5757 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `MID` (candidate) -- fail -- net_r/trade -0.1741 beats the baseline's -0.163 by -0.0111 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1146 | -153.9054 | -0.1343 | 0/6 | 63.2881 | None | None | 0.9999639900418373 | fail |
| XRPUSDT | 1108 | -200.7569 | -0.1812 | 0/6 | 86.6934 | None | None | 0.9999999195250705 | fail |
| LINKUSDT | 1199 | -198.0499 | -0.1652 | 0/6 | 121.6547 | None | None | 0.9999994710786148 | fail |
| DOGEUSDT | 1073 | -222.2235 | -0.2071 | 1/6 | 154.0476 | None | None | 0.9999999970640677 | fail |
| BNBUSDT | 1179 | -242.8358 | -0.206 | 0/6 | 80.542 | None | None | 0.9999999987013077 | fail |
| AVAXUSDT | 1055 | -158.8195 | -0.1505 | 0/6 | 94.4694 | None | None | 0.9999802473536096 | fail |
| **pooled** | 6760 | -1176.5886 | -0.1741 | 0/6 | 1186.2181 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 878 | -4.7387 | -0.0054 | 3/6 | 89.0696 | None | None | 0.529871055560909 | fail |
| XRPUSDT | 825 | -92.9125 | -0.1126 | 1/6 | 37.8287 | None | None | 0.9449434843034861 | fail |
| LINKUSDT | 901 | -32.2964 | -0.0358 | 4/6 | 37.5672 | None | None | 0.6920579509757501 | fail |
| DOGEUSDT | 834 | -120.2321 | -0.1442 | 2/6 | 77.2412 | None | None | 0.9546714548786025 | fail |
| BNBUSDT | 890 | -144.1346 | -0.1619 | 0/6 | 45.8863 | None | None | 0.9917967568576522 | fail |
| AVAXUSDT | 802 | 11.2091 | 0.014 | 3/6 | 47.4098 | None | None | 0.42792473943584614 | fail |
| **pooled** | 5130 | -383.1029 | -0.0747 | 1/6 | 498.6204 (seq) | - | - | 0.9933352712101382 | - |

Holm survivors (alpha 0.05): []

## arm `TP1` (candidate) -- fail -- net_r/trade -0.1624 beats the baseline's -0.163 by 0.0006 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1142 | -156.8108 | -0.1373 | 0/6 | 77.4914 | None | None | 0.9999980700513137 | fail |
| XRPUSDT | 1102 | -179.7 | -0.1631 | 1/6 | 59.0329 | None | None | 0.9999999641060081 | fail |
| LINKUSDT | 1211 | -148.7191 | -0.1228 | 0/6 | 58.4303 | None | None | 0.9999897285327722 | fail |
| DOGEUSDT | 1083 | -227.75 | -0.2103 | 0/6 | 130.2633 | None | None | 0.9999999999974591 | fail |
| BNBUSDT | 1186 | -219.1024 | -0.1847 | 0/6 | 50.0324 | None | None | 0.9999999998270525 | fail |
| AVAXUSDT | 1058 | -169.3578 | -0.1601 | 0/6 | 84.1723 | None | None | 0.9999998969429488 | fail |
| **pooled** | 6782 | -1101.4394 | -0.1624 | 0/6 | 1112.3914 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

