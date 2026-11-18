# Stage-0 (synthetic leg) -- trend 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; D55: net_r/trade -0.0447 beats the baseline's -0.0367 by -0.008 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DASHUSDT | 444 | -57.287 | -0.129 | 2/6 | 77.4886 | -0.033 | 3.906 | 0.9395164904877454 | fail |
| ONTUSDT | 451 | -3.2212 | -0.0071 | 2/6 | 30.2272 | -0.0019 | 3.844 | 0.5337279928272547 | fail |
| NEOUSDT | 471 | -46.7379 | -0.0992 | 1/6 | 66.6137 | -0.0274 | 3.619 | 0.8932032901385405 | fail |
| SNXUSDT | 409 | -25.4959 | -0.0623 | 1/6 | 55.2351 | -0.0145 | 4.309 | 0.7780895165759811 | fail |
| MANAUSDT | 371 | 0.153 | 0.0004 | 2/6 | 29.7592 | 0.0001 | 4.168 | 0.49816063413316963 | fail |
| SANDUSDT | 388 | 39.6126 | 0.1021 | 5/6 | 26.1638 | 0.0249 | 4.107 | 0.15565868662779836 | pass |
| **pooled** | 2534 | -92.9753 | -0.0367 | 2/6 | 179.2454 (seq) | - | - | 0.851619343771214 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade -0.0447 beats the baseline's -0.0367 by -0.008 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DASHUSDT | 328 | -19.8381 | -0.0605 | 3/6 | 48.0777 | -0.0145 | 4.183 | 0.7280409012835283 | fail |
| ONTUSDT | 353 | -18.4249 | -0.0522 | 3/6 | 37.9894 | -0.0144 | 3.63 | 0.7248626002250835 | fail |
| NEOUSDT | 378 | -53.9114 | -0.1426 | 1/6 | 71.3235 | -0.043 | 3.32 | 0.9483582756965145 | fail |
| SNXUSDT | 333 | -43.8441 | -0.1317 | 2/6 | 54.5057 | -0.0328 | 4.018 | 0.9446125583800413 | fail |
| MANAUSDT | 294 | 8.8865 | 0.0302 | 3/6 | 18.3623 | 0.0075 | 4.007 | 0.3803990933507922 | fail |
| SANDUSDT | 309 | 37.9687 | 0.1229 | 5/6 | 23.4176 | 0.0328 | 3.749 | 0.1326168845795338 | pass |
| **pooled** | 1995 | -89.1651 | -0.0447 | 3/6 | 155.7297 (seq) | - | - | 0.8777404318926016 | - |

Holm survivors (alpha 0.05): []

