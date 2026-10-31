# Stage-0 (synthetic leg) -- pullback 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; BE1: net_r/trade 0.0631 beats the baseline's 0.0557 by 0.0074 < the 0.05 materiality bar; LONG: net_r/trade 0.0981 beats the baseline's 0.0557 by 0.0424 < the 0.05 materiality bar; ADX20: net_r/trade 0.103 beats the baseline's 0.0557 by 0.0473 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 203 | 6.0474 | 0.0298 | 2/6 | 16.9878 | 0.0033 | 8.942 | 0.40510841152687516 | fail |
| ETHUSDT | 198 | 1.1278 | 0.0057 | 4/6 | 27.4859 | 0.0006 | 9.28 | 0.48309596267348937 | pass |
| SOLUSDT | 192 | 28.1743 | 0.1467 | 4/6 | 20.659 | 0.0159 | 9.239 | 0.15000292421719408 | pass |
| XRPUSDT | 204 | -14.241 | -0.0698 | 3/6 | 38.612 | -0.0077 | 9.101 | 0.7197185555410063 | fail |
| ADAUSDT | 187 | 12.1684 | 0.0651 | 3/6 | 19.8865 | 0.0066 | 9.85 | 0.3053573494293259 | fail |
| AVAXUSDT | 197 | 32.4499 | 0.1647 | 5/6 | 12.8598 | 0.0185 | 8.927 | 0.09329115622451667 | pass |
| **pooled** | 1181 | 65.7276 | 0.0557 | 3/6 | 71.0027 (seq) | - | - | 0.14426727411792173 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0631 beats the baseline's 0.0557 by 0.0074 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 242 | -0.4853 | -0.002 | 2/6 | 16.5697 | -0.0003 | 7.078 | 0.5075636917848194 | fail |
| ETHUSDT | 234 | 3.7911 | 0.0162 | 3/6 | 26.0179 | 0.0021 | 7.654 | 0.44327588802801954 | fail |
| SOLUSDT | 216 | 35.6698 | 0.1651 | 4/6 | 12.756 | 0.0207 | 7.995 | 0.09000028316095249 | pass |
| XRPUSDT | 225 | -1.0972 | -0.0049 | 3/6 | 25.196 | -0.0006 | 8.016 | 0.5188589273248505 | fail |
| ADAUSDT | 222 | 19.537 | 0.088 | 3/6 | 12.7351 | 0.011 | 7.995 | 0.21712561493501853 | fail |
| AVAXUSDT | 219 | 28.2178 | 0.1288 | 4/6 | 14.1336 | 0.0167 | 7.728 | 0.116388086776602 | pass |
| **pooled** | 1358 | 85.633 | 0.0631 | 3/6 | 48.6973 (seq) | - | - | 0.08167472579331675 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade 0.0981 beats the baseline's 0.0557 by 0.0424 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 145 | 18.8209 | 0.1298 | 5/6 | 13.3475 | 0.0162 | 8.032 | 0.20703481557066633 | pass |
| ETHUSDT | 139 | 19.6053 | 0.141 | 4/6 | 14.6411 | 0.0169 | 8.332 | 0.2083667886101821 | pass |
| SOLUSDT | 125 | 46.9184 | 0.3753 | 5/6 | 7.7877 | 0.0405 | 9.277 | 0.03044080765298065 | pass |
| XRPUSDT | 164 | -10.8071 | -0.0659 | 3/6 | 29.3766 | -0.0093 | 7.072 | 0.6849553668152212 | fail |
| ADAUSDT | 143 | 12.2781 | 0.0859 | 5/6 | 13.5916 | 0.0115 | 7.449 | 0.30155043413199745 | pass |
| AVAXUSDT | 142 | -2.6572 | -0.0187 | 2/6 | 19.2252 | -0.0027 | 6.859 | 0.5517990980860807 | fail |
| **pooled** | 858 | 84.159 | 0.0981 | 4/6 | 47.3446 (seq) | - | - | 0.06834555560160854 | - |

Holm survivors (alpha 0.05): []

## arm `ADX20` (candidate) -- fail -- net_r/trade 0.103 beats the baseline's 0.0557 by 0.0473 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 175 | 21.266 | 0.1215 | 3/6 | 11.0681 | 0.0125 | 9.696 | 0.1846067153693377 | fail |
| ETHUSDT | 172 | 11.3718 | 0.0661 | 4/6 | 16.395 | 0.0068 | 9.768 | 0.32343506602557276 | pass |
| SOLUSDT | 167 | 42.9127 | 0.257 | 5/6 | 9.043 | 0.0258 | 9.941 | 0.051564288001371084 | pass |
| XRPUSDT | 174 | -12.7256 | -0.0731 | 2/6 | 28.6544 | -0.0075 | 9.804 | 0.7178079634285545 | fail |
| ADAUSDT | 166 | 20.9538 | 0.1262 | 4/6 | 23.4049 | 0.0123 | 10.249 | 0.18761353956121063 | pass |
| AVAXUSDT | 170 | 21.6493 | 0.1273 | 3/6 | 11.0027 | 0.0139 | 9.184 | 0.16105398343664518 | fail |
| **pooled** | 1024 | 105.429 | 0.103 | 5/6 | 54.3587 (seq) | - | - | 0.03476532500936551 | - |

Holm survivors (alpha 0.05): []

