# Stage-0 (synthetic leg) -- trend 1w -- pass

PASS: arm LO passes (pooled net_r 127.7165); 2 of 2 arms pass. Thresholds: n_floor 10, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `LO` (arm) -- pass -- pooled net_r 127.7165 > 0 with 5 folds positive and 11 of 15 powered cells pass (breadth floor 8)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 17 | 12.9275 | 0.7604 | 4/6 | 2.1111 | 0.0029 | 260.232 | 0.05605585040438462 | pass |
| QQQ | 23 | 13.3145 | 0.5789 | 4/6 | 1.9732 | 0.003 | 191.436 | 0.055902495907818595 | pass |
| IWM | 15 | 6.3285 | 0.4219 | 4/6 | 2.7817 | 0.0016 | 258.069 | 0.14210834454799504 | pass |
| GLD | 23 | 13.9088 | 0.6047 | 5/6 | 3.922 | 0.0054 | 111.09 | 0.011695973036099499 | pass |
| SLV | 22 | 9.1336 | 0.4152 | 4/6 | 5.6944 | 0.0053 | 78.274 | 0.1422380277514742 | pass |
| TLT | 17 | 6.8346 | 0.402 | 3/6 | 3.1108 | 0.0036 | 112.413 | 0.13269190784829454 | fail |
| IEF | 17 | 4.8198 | 0.2835 | 3/6 | 3.087 | 0.0023 | 121.471 | 0.20955755542390314 | fail |
| USO | 24 | 0.9404 | 0.0392 | 2/6 | 4.0261 | 0.0004 | 101.206 | 0.43647753078169566 | fail |
| GDX | 25 | -5.7803 | -0.2312 | 2/6 | 6.8714 | -0.0025 | 93.52 | 0.9043222547811467 | fail |
| TQQQ | 25 | 9.8176 | 0.3927 | 5/6 | 3.0764 | 0.0036 | 108.36 | 0.05274528186481692 | pass |
| QLD | 28 | 9.9227 | 0.3544 | 5/6 | 3.1624 | 0.0028 | 128.002 | 0.04882593977237532 | pass |
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '7300', '--output', 'comms/research/RQ-20261018-ef5d-05/39124033697/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| IAUM | 7 | 8.5843 | 1.2263 | 5/6 | 0.2906 | 0.0128 | 95.998 | 0.015438647169011175 | indeterminate |
| SCHA | 14 | 6.6748 | 0.4768 | 4/6 | 1.8934 | 0.0018 | 260.498 | 0.13293811696510166 | pass |
| MES | 16 | 11.6601 | 0.7288 | 4/6 | 2.1279 | 0.0026 | 277.375 | 0.057459469369055625 | pass |
| MGC | 21 | 15.3158 | 0.7293 | 5/6 | 3.9084 | 0.0055 | 132.335 | 0.007042820914231645 | pass |
| MHG | 18 | 3.3129 | 0.184 | 4/6 | 3.4223 | 0.0016 | 113.554 | 0.31929039884387744 | pass |
| **pooled** | 312 | 127.7165 | 0.4093 | 5/6 | 17.771 (seq) | - | - | 2.2661905368980188e-07 | - |

Holm survivors (alpha 0.05): []

## arm `BOTH` (arm) -- pass -- pooled net_r 84.2177 > 0 with 5 folds positive and 10 of 16 powered cells pass (breadth floor 8)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 28 | 8.5399 | 0.305 | 4/6 | 3.941 | 0.0017 | 184.751 | 0.16511791641884416 | pass |
| QQQ | 31 | 9.3371 | 0.3012 | 5/6 | 2.1911 | 0.0018 | 165.291 | 0.14123639973068958 | pass |
| IWM | 25 | 4.3958 | 0.1758 | 4/6 | 3.6973 | 0.0009 | 195.16 | 0.24033509298499695 | pass |
| GLD | 37 | 8.4371 | 0.228 | 4/6 | 7.7998 | 0.0023 | 100.079 | 0.1118297155991167 | pass |
| SLV | 39 | 4.7691 | 0.1223 | 3/6 | 9.5746 | 0.0014 | 85.078 | 0.30115179069020925 | fail |
| TLT | 29 | 3.4075 | 0.1175 | 3/6 | 3.1194 | 0.0008 | 142.898 | 0.2741316229036951 | fail |
| IEF | 35 | 1.2728 | 0.0364 | 3/6 | 5.4562 | 0.0003 | 114.8 | 0.4270999914848276 | fail |
| USO | 29 | 13.8117 | 0.4763 | 4/6 | 4.95 | 0.0032 | 147.0 | 0.07637254242738778 | pass |
| GDX | 36 | -9.9162 | -0.2754 | 0/6 | 10.7165 | -0.0024 | 115.304 | 0.9714859437102611 | fail |
| TQQQ | 31 | 5.0884 | 0.1641 | 3/6 | 3.1223 | 0.0014 | 115.388 | 0.20576865535593297 | fail |
| QLD | 37 | 2.5089 | 0.0678 | 3/6 | 3.7699 | 0.0006 | 118.622 | 0.3380899362743316 | fail |
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '7300', '--output', 'comms/research/RQ-20261018-ef5d-05/39124033697/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| IAUM | 10 | 8.2646 | 0.8265 | 5/6 | 0.4952 | 0.0084 | 98.7 | 0.024774019687927033 | pass |
| SCHA | 21 | 5.9959 | 0.2855 | 4/6 | 2.7783 | 0.0014 | 197.666 | 0.16301503355367497 | pass |
| MES | 28 | 5.743 | 0.2051 | 4/6 | 3.163 | 0.0011 | 184.247 | 0.23932466576736683 | pass |
| MGC | 34 | 9.5227 | 0.2801 | 4/6 | 7.6248 | 0.0025 | 113.029 | 0.09341953350669463 | pass |
| MHG | 31 | 3.0383 | 0.098 | 4/6 | 4.5967 | 0.0008 | 116.515 | 0.35245088484038006 | pass |
| **pooled** | 481 | 84.2177 | 0.1751 | 5/6 | 19.499 (seq) | - | - | 0.0014936234806194697 | - |

Holm survivors (alpha 0.05): []

