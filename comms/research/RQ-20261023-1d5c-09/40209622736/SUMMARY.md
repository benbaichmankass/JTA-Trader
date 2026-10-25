# Stage-0 (synthetic leg) -- pullback 4h -- fail

FAIL: B: pooled net_r 89.0908 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); DI: net_r/trade 0.045 beats the baseline's 0.0768 by -0.0318 < the 0.05 materiality bar; ST: net_r/trade 0.0154 beats the baseline's 0.0768 by -0.0614 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 89.0908 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 201 | 21.7876 | 0.1084 | 4/6 | 24.1044 | 0.0118 | 9.197 | 0.20827244256433725 | pass |
| LINKUSDT | 195 | 12.1118 | 0.0621 | 4/6 | 24.6356 | 0.0067 | 9.327 | 0.31407761180549126 | pass |
| DOGEUSDT | 188 | 0.5946 | 0.0032 | 1/6 | 25.194 | 0.0003 | 9.895 | 0.48956758188488275 | fail |
| LTCUSDT | 203 | 6.6723 | 0.0329 | 3/6 | 39.3731 | 0.0036 | 9.179 | 0.39166644360120123 | fail |
| BCHUSDT | 184 | 15.5053 | 0.0843 | 3/6 | 27.0955 | 0.0082 | 10.237 | 0.2595436530999773 | fail |
| DOTUSDT | 189 | 32.4186 | 0.1715 | 4/6 | 11.1465 | 0.0181 | 9.46 | 0.11153415619220186 | pass |
| **pooled** | 1160 | 89.0908 | 0.0768 | 4/6 | 78.1798 (seq) | - | - | 0.07187375263669316 | - |

Holm survivors (alpha 0.05): []

## arm `DI` (candidate) -- fail -- net_r/trade 0.045 beats the baseline's 0.0768 by -0.0318 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 203 | 10.1351 | 0.0499 | 5/6 | 22.209 | 0.0063 | 7.934 | 0.3495674955651536 | pass |
| LINKUSDT | 185 | -3.5519 | -0.0192 | 4/6 | 27.5662 | -0.0021 | 8.96 | 0.5629985114694276 | fail |
| DOGEUSDT | 178 | 8.8347 | 0.0496 | 3/6 | 17.9961 | 0.0051 | 9.734 | 0.34201590937956855 | fail |
| LTCUSDT | 181 | -1.9534 | -0.0108 | 4/6 | 37.7586 | -0.0012 | 9.261 | 0.5335939223543658 | fail |
| BCHUSDT | 163 | 9.45 | 0.058 | 3/6 | 22.0658 | 0.0052 | 11.15 | 0.329137964149802 | fail |
| DOTUSDT | 167 | 25.5485 | 0.153 | 4/6 | 14.3707 | 0.0159 | 9.621 | 0.1631863801505401 | pass |
| **pooled** | 1077 | 48.463 | 0.045 | 3/6 | 83.2744 (seq) | - | - | 0.19978880811167554 | - |

Holm survivors (alpha 0.05): []

## arm `ST` (candidate) -- fail -- net_r/trade 0.0154 beats the baseline's 0.0768 by -0.0614 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 481 | 5.6552 | 0.0118 | 3/6 | 24.6777 | 0.0045 | 2.621 | 0.4137551441934846 | fail |
| LINKUSDT | 440 | 14.4217 | 0.0328 | 4/6 | 16.5505 | 0.0117 | 2.804 | 0.28245347310649116 | pass |
| DOGEUSDT | 520 | 31.6962 | 0.061 | 4/6 | 26.0561 | 0.0264 | 2.31 | 0.1402119284791558 | pass |
| LTCUSDT | 475 | -13.3803 | -0.0282 | 3/6 | 43.8893 | -0.0109 | 2.594 | 0.7014227935421781 | fail |
| BCHUSDT | 480 | 11.4653 | 0.0239 | 3/6 | 35.7833 | 0.0092 | 2.608 | 0.33513110452122097 | fail |
| DOTUSDT | 431 | -6.2848 | -0.0146 | 3/6 | 19.7345 | -0.0052 | 2.798 | 0.6097921766066225 | fail |
| **pooled** | 2827 | 43.5731 | 0.0154 | 2/6 | 104.2283 (seq) | - | - | 0.24620306629009314 | - |

Holm survivors (alpha 0.05): []

