# Stage-0 (synthetic leg) -- squeeze 4h -- fail

FAIL: B: pooled net_r 82.561 > 0 with 5 folds positive and 3 of 6 powered cells pass (breadth floor 3); BE1: net_r/trade 0.0408 beats the baseline's 0.048 by -0.0072 < the 0.05 materiality bar; WIDE: net_r/trade -0.0893 beats the baseline's 0.048 by -0.1373 < the 0.05 materiality bar; STOP35: net_r/trade 0.0394 beats the baseline's 0.048 by -0.0086 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 82.561 > 0 with 5 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 293 | 0.6809 | 0.0023 | 3/6 | 20.4029 | 0.0006 | 3.581 | 0.489327932636183 | fail |
| ETHUSDT | 300 | 16.9471 | 0.0565 | 4/6 | 13.5501 | 0.0161 | 3.509 | 0.26284958321891216 | pass |
| SOLUSDT | 267 | 63.4932 | 0.2378 | 6/6 | 8.0343 | 0.0611 | 3.893 | 0.005118344311237946 | pass |
| XRPUSDT | 294 | -12.9423 | -0.044 | 3/6 | 37.8837 | -0.0129 | 3.407 | 0.695195610089745 | fail |
| ADAUSDT | 293 | 31.0445 | 0.106 | 5/6 | 19.8268 | 0.0296 | 3.584 | 0.08964854483576923 | pass |
| AVAXUSDT | 272 | -16.6636 | -0.0613 | 1/6 | 28.7902 | -0.017 | 3.605 | 0.8029882053203252 | fail |
| **pooled** | 1719 | 82.561 | 0.048 | 5/6 | 54.9385 (seq) | - | - | 0.08215321525352198 | - |

Holm survivors (alpha 0.05): ['SOLUSDT']

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0408 beats the baseline's 0.048 by -0.0072 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 299 | -1.5443 | -0.0052 | 3/6 | 22.4226 | -0.0015 | 3.41 | 0.5243788193853379 | fail |
| ETHUSDT | 302 | 19.2337 | 0.0637 | 5/6 | 13.1147 | 0.0184 | 3.452 | 0.23485988230334937 | pass |
| SOLUSDT | 270 | 59.1476 | 0.2191 | 5/6 | 7.6853 | 0.0575 | 3.81 | 0.0065144331216263505 | pass |
| XRPUSDT | 300 | -20.2589 | -0.0675 | 3/6 | 42.5252 | -0.0208 | 3.253 | 0.7907650645225057 | fail |
| ADAUSDT | 298 | 32.6067 | 0.1094 | 5/6 | 15.7939 | 0.0313 | 3.501 | 0.08012570877503095 | pass |
| AVAXUSDT | 277 | -17.9161 | -0.0647 | 1/6 | 27.1846 | -0.0184 | 3.514 | 0.8249007978588874 | fail |
| **pooled** | 1746 | 71.2696 | 0.0408 | 5/6 | 54.9827 (seq) | - | - | 0.11218177247228606 | - |

Holm survivors (alpha 0.05): ['SOLUSDT']

## arm `WIDE` (candidate) -- fail -- net_r/trade -0.0893 beats the baseline's 0.048 by -0.1373 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 41 | -2.25 | -0.0549 | 2/6 | 11.3132 | -0.02 | 2.744 | 0.576879971076908 | fail |
| ETHUSDT | 42 | -10.8915 | -0.2593 | 0/6 | 10.8915 | -0.1018 | 2.548 | 0.9386735196653664 | fail |
| SOLUSDT | 20 | -11.515 | -0.5757 | 0/6 | 11.7553 | -0.2179 | 2.642 | 0.9995079093442454 | indeterminate |
| XRPUSDT | 40 | 2.0049 | 0.0501 | 3/6 | 4.7356 | 0.0145 | 3.446 | 0.38465673221356483 | fail |
| ADAUSDT | 21 | 4.8701 | 0.2319 | 3/6 | 3.2754 | 0.0611 | 3.794 | 0.27547318188010783 | indeterminate |
| AVAXUSDT | 21 | 1.2571 | 0.0599 | 1/6 | 8.0761 | 0.0216 | 2.778 | 0.4381663509297986 | indeterminate |
| **pooled** | 185 | -16.5244 | -0.0893 | 2/6 | 20.7973 (seq) | - | - | 0.8066043976037347 | - |

Holm survivors (alpha 0.05): []

## arm `STOP35` (candidate) -- fail -- net_r/trade 0.0394 beats the baseline's 0.048 by -0.0086 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 273 | 4.1033 | 0.015 | 3/6 | 13.8452 | 0.0039 | 3.839 | 0.4143769131270946 | fail |
| ETHUSDT | 282 | 13.8258 | 0.049 | 5/6 | 13.2409 | 0.0127 | 3.875 | 0.23389647318900075 | pass |
| SOLUSDT | 257 | 42.5968 | 0.1657 | 6/6 | 5.8653 | 0.0394 | 4.207 | 0.007515971709613575 | pass |
| XRPUSDT | 283 | -3.5347 | -0.0125 | 4/6 | 17.1722 | -0.0035 | 3.607 | 0.5674781131011242 | fail |
| ADAUSDT | 283 | 22.6171 | 0.0799 | 4/6 | 15.4847 | 0.021 | 3.814 | 0.10862170316573688 | pass |
| AVAXUSDT | 256 | -15.165 | -0.0592 | 1/6 | 24.732 | -0.015 | 3.944 | 0.8551910301831451 | fail |
| **pooled** | 1634 | 64.4449 | 0.0394 | 5/6 | 46.6227 (seq) | - | - | 0.07469222968341133 | - |

Holm survivors (alpha 0.05): ['SOLUSDT']

