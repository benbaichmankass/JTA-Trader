# Stage-0 (synthetic leg) -- trend 1w -- indeterminate

INDETERMINATE: W5: only 0 powered cell(s) (< 2): breadth cannot be read; W10: only 0 powered cell(s) (< 2): breadth cannot be read; W20: only 0 powered cell(s) (< 2): breadth cannot be read. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline W5 with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `W5` (baseline) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 8 | 8.0362 | 1.0045 | 3/6 | 1.8028 | 0.005 | 200.375 | 0.18251614901803448 | indeterminate |
| ETHUSDT | 7 | 5.5754 | 0.7965 | 3/6 | 1.2867 | 0.0033 | 238.0 | 0.11602665189883099 | indeterminate |
| SOLUSDT | 10 | 7.9037 | 0.7904 | 3/6 | 2.0753 | 0.0058 | 137.2 | 0.11342872413293092 | indeterminate |
| XRPUSDT | 5 | 1.7533 | 0.3507 | 2/6 | 1.7773 | 0.001 | 359.8 | 0.35280347900938896 | indeterminate |
| ADAUSDT | 12 | 1.2543 | 0.1045 | 3/6 | 3.8814 | 0.0011 | 96.25 | 0.4116352285101076 | indeterminate |
| AVAXUSDT | 6 | 2.5303 | 0.4217 | 1/6 | 2.7202 | 0.0018 | 239.169 | 0.35890406700749905 | indeterminate |
| BNBUSDT | 6 | 8.5945 | 1.4324 | 3/6 | 1.0202 | 0.0048 | 296.331 | 0.14473666312877792 | indeterminate |
| DOGEUSDT | 13 | 13.9888 | 1.0761 | 3/6 | 3.3568 | 0.0139 | 77.539 | 0.1004462041665719 | indeterminate |
| LINKUSDT | 5 | 0.6859 | 0.1372 | 1/6 | 2.4546 | 0.0004 | 357.0 | 0.4185099567888214 | indeterminate |
| LTCUSDT | 9 | 1.2895 | 0.1433 | 2/6 | 2.5318 | 0.001 | 143.892 | 0.3807022708859622 | indeterminate |
| BCHUSDT | 8 | 0.6818 | 0.0852 | 2/6 | 1.7262 | 0.0004 | 200.375 | 0.40762440155003055 | indeterminate |
| DOTUSDT | 6 | -1.0167 | -0.1694 | 1/6 | 3.8908 | -0.0006 | 273.0 | 0.6047970196320173 | indeterminate |
| **pooled** | 95 | 51.2769 | 0.5398 | 4/6 | 15.8534 (seq) | - | - | 0.005753429959239527 | - |

Holm survivors (alpha 0.05): []

## arm `W10` (candidate) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 8 | 1.7373 | 0.2172 | 3/6 | 2.1749 | 0.0012 | 183.75 | 0.3416949179645917 | indeterminate |
| ETHUSDT | 7 | 3.705 | 0.5293 | 2/6 | 1.4592 | 0.0034 | 156.002 | 0.2026098708373686 | indeterminate |
| SOLUSDT | 7 | 9.3434 | 1.3348 | 4/6 | 1.07 | 0.011 | 121.002 | 0.12224017259115327 | indeterminate |
| XRPUSDT | 10 | 4.4265 | 0.4426 | 2/6 | 4.0435 | 0.0047 | 94.5 | 0.35441411328683337 | indeterminate |
| ADAUSDT | 8 | 11.8044 | 1.4755 | 3/6 | 1.8149 | 0.0176 | 84.0 | 0.16788577805109117 | indeterminate |
| AVAXUSDT | 7 | 7.9673 | 1.1382 | 3/6 | 2.2204 | 0.0165 | 68.999 | 0.18955973603245396 | indeterminate |
| BNBUSDT | 10 | 8.8218 | 0.8822 | 3/6 | 4.3388 | 0.0075 | 118.3 | 0.2108872411303379 | indeterminate |
| DOGEUSDT | 11 | 22.9545 | 2.0868 | 3/6 | 4.026 | 0.0455 | 45.815 | 0.17322612436483842 | indeterminate |
| LINKUSDT | 9 | -0.4716 | -0.0524 | 3/6 | 2.162 | -0.0005 | 100.331 | 0.5517771285349401 | indeterminate |
| LTCUSDT | 10 | -2.1811 | -0.2181 | 2/6 | 3.9175 | -0.0026 | 82.6 | 0.7499831818934235 | indeterminate |
| BCHUSDT | 9 | -3.9667 | -0.4407 | 0/6 | 4.1608 | -0.0048 | 91.777 | 0.9641059700121484 | indeterminate |
| DOTUSDT | 6 | -0.1657 | -0.0276 | 1/6 | 1.8393 | -0.0003 | 81.669 | 0.5244975082168399 | indeterminate |
| **pooled** | 102 | 63.9752 | 0.6272 | 4/6 | 17.3669 (seq) | - | - | 0.025908652598880977 | - |

Holm survivors (alpha 0.05): []

## arm `W20` (candidate) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 6 | -0.2418 | -0.0403 | 1/6 | 2.1586 | -0.0002 | 191.331 | 0.5281089762197181 | indeterminate |
| ETHUSDT | 6 | 2.1259 | 0.3543 | 2/6 | 1.8036 | 0.0027 | 130.669 | 0.31604630395823297 | indeterminate |
| SOLUSDT | 6 | 6.822 | 1.137 | 3/6 | 1.4741 | 0.0089 | 127.169 | 0.19589960931462175 | indeterminate |
| XRPUSDT | 5 | 2.2583 | 0.4517 | 2/6 | 2.1411 | 0.0062 | 72.8 | 0.34592154367836186 | indeterminate |
| ADAUSDT | 7 | 1.5483 | 0.2212 | 3/6 | 1.7579 | 0.0032 | 68.999 | 0.35325260825178745 | indeterminate |
| AVAXUSDT | 6 | 2.6666 | 0.4444 | 2/6 | 3.3554 | 0.0089 | 50.169 | 0.31991938051460045 | indeterminate |
| BNBUSDT | 9 | 10.1615 | 1.1291 | 3/6 | 4.2049 | 0.0134 | 84.0 | 0.22095316547860272 | indeterminate |
| DOGEUSDT | 7 | -1.4668 | -0.2095 | 1/6 | 4.302 | -0.0068 | 31.003 | 0.6139211742879023 | indeterminate |
| LINKUSDT | 5 | 0.8904 | 0.1781 | 1/6 | 0.8966 | 0.002 | 89.6 | 0.3758799394676462 | indeterminate |
| LTCUSDT | 7 | -3.7403 | -0.5343 | 1/6 | 3.7547 | -0.0057 | 93.002 | 0.9636129616157575 | indeterminate |
| BCHUSDT | 5 | -1.1337 | -0.2267 | 2/6 | 2.5779 | -0.0019 | 120.4 | 0.691659252022916 | indeterminate |
| DOTUSDT | 5 | -4.8395 | -0.9679 | 0/6 | 4.8395 | -0.021 | 46.2 | 0.9999755414093208 | indeterminate |
| **pooled** | 74 | 15.0511 | 0.2034 | 3/6 | 14.7619 (seq) | - | - | 0.20518031803069586 | - |

Holm survivors (alpha 0.05): []

