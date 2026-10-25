# Stage-0 (synthetic leg) -- trend 30m -- fail

FAIL: B: pooled net_r <= 0 or folds short; G50: net_r/trade 0.0104 beats the baseline's -0.0173 by 0.0277 < the 0.05 materiality bar; G75: net_r/trade 0.0048 beats the baseline's -0.0173 by 0.0221 < the 0.05 materiality bar; G90: net_r/trade 0.0103 beats the baseline's -0.0173 by 0.0276 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.67 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 2217 | -55.7188 | -0.0251 | 1/6 | 112.7295 | -0.0554 | 0.454 | 0.8313115206088002 | fail |
| AVAXUSDT | 2340 | 36.558 | 0.0156 | 3/6 | 51.6372 | 0.0365 | 0.428 | 0.27646116137730153 | fail |
| SOLUSDT | 2257 | -98.4227 | -0.0436 | 2/6 | 110.667 | -0.0965 | 0.452 | 0.9569728062085878 | fail |
| **pooled** | 6814 | -117.5871 | -0.0173 | 1/6 | 183.9805 (seq) | - | - | 0.8749424961845261 | - |

Holm survivors (alpha 0.05): []

## arm `G50` (candidate) -- fail -- net_r/trade 0.0104 beats the baseline's -0.0173 by 0.0277 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1441 | -1.5165 | -0.0011 | 3/6 | 54.8563 | -0.002 | 0.514 | 0.5124579884146785 | fail |
| AVAXUSDT | 1496 | 54.535 | 0.0365 | 5/6 | 34.5519 | 0.0723 | 0.504 | 0.13358949448438434 | pass |
| SOLUSDT | 1490 | -7.0897 | -0.0048 | 3/6 | 44.8812 | -0.009 | 0.529 | 0.5580043313727653 | fail |
| **pooled** | 4427 | 45.9275 | 0.0104 | 4/6 | 62.3043 (seq) | - | - | 0.2932406929912481 | - |

Holm survivors (alpha 0.05): []

## arm `G75` (candidate) -- fail -- net_r/trade 0.0048 beats the baseline's -0.0173 by 0.0221 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 927 | -5.1359 | -0.0055 | 3/6 | 31.427 | -0.0099 | 0.559 | 0.5533429169314379 | fail |
| AVAXUSDT | 940 | 41.263 | 0.0439 | 5/6 | 27.8645 | 0.0786 | 0.558 | 0.14034634069170776 | pass |
| SOLUSDT | 951 | -22.6336 | -0.0238 | 2/6 | 49.0052 | -0.0407 | 0.585 | 0.7258926316972842 | fail |
| **pooled** | 2818 | 13.4944 | 0.0048 | 3/6 | 52.8246 (seq) | - | - | 0.4189087669652324 | - |

Holm survivors (alpha 0.05): []

## arm `G90` (candidate) -- fail -- net_r/trade 0.0103 beats the baseline's -0.0173 by 0.0276 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 515 | -10.2446 | -0.0199 | 3/6 | 18.6767 | -0.0334 | 0.595 | 0.6355401334375295 | fail |
| AVAXUSDT | 520 | 16.2428 | 0.0312 | 4/6 | 16.9574 | 0.053 | 0.589 | 0.2942725898729875 | pass |
| SOLUSDT | 518 | 10.0305 | 0.0194 | 5/6 | 30.3293 | 0.0297 | 0.651 | 0.3691433300423614 | pass |
| **pooled** | 1553 | 16.0306 | 0.0103 | 3/6 | 49.9405 (seq) | - | - | 0.3782314737701322 | - |

Holm survivors (alpha 0.05): []

