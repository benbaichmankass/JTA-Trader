# Stage-0 (synthetic leg) -- trend 15m -- fail

FAIL: B: pooled net_r <= 0 or folds short; G50: net_r/trade -0.0214 beats the baseline's -0.0504 by 0.029 < the 0.05 materiality bar; G75: pooled passes but only 1 of 3 powered cells pass (< 3): one symbol's edge; G90: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.67 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 4526 | -340.2838 | -0.0752 | 0/6 | 377.2894 | -0.3396 | 0.221 | 0.9999825020541324 | fail |
| AVAXUSDT | 4649 | -84.4813 | -0.0182 | 1/6 | 133.6233 | -0.0838 | 0.217 | 0.8304188307808387 | fail |
| SOLUSDT | 4564 | -267.6623 | -0.0586 | 0/6 | 273.7537 | -0.2641 | 0.222 | 0.999401446807521 | fail |
| **pooled** | 13739 | -692.4324 | -0.0504 | 0/6 | 752.7379 (seq) | - | - | 0.9999988957327048 | - |

Holm survivors (alpha 0.05): []

## arm `G50` (candidate) -- fail -- net_r/trade -0.0214 beats the baseline's -0.0504 by 0.029 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 2888 | -144.274 | -0.05 | 0/6 | 171.3244 | -0.1962 | 0.255 | 0.9849594328509659 | fail |
| AVAXUSDT | 2988 | 9.2433 | 0.0031 | 3/6 | 54.8433 | 0.0125 | 0.247 | 0.4474725526091904 | fail |
| SOLUSDT | 2919 | -52.7829 | -0.0181 | 1/6 | 85.5498 | -0.0699 | 0.259 | 0.7821705652050195 | fail |
| **pooled** | 8795 | -187.8166 | -0.0214 | 0/6 | 261.8666 (seq) | - | - | 0.9444279020067139 | - |

Holm survivors (alpha 0.05): []

## arm `G75` (candidate) -- fail -- pooled passes but only 1 of 3 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1826 | -19.9289 | -0.0109 | 1/6 | 65.1899 | -0.0378 | 0.288 | 0.6415155515770561 | fail |
| AVAXUSDT | 1870 | 71.9191 | 0.0385 | 5/6 | 48.7235 | 0.1351 | 0.285 | 0.08824084877939037 | pass |
| SOLUSDT | 1892 | 4.3045 | 0.0023 | 3/6 | 33.4262 | 0.0077 | 0.296 | 0.46846438836439613 | fail |
| **pooled** | 5588 | 56.2968 | 0.0101 | 4/6 | 87.1823 (seq) | - | - | 0.2743518163063843 | - |

Holm survivors (alpha 0.05): []

## arm `G90` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1057 | -5.8524 | -0.0055 | 2/6 | 36.929 | -0.017 | 0.325 | 0.5565330667528625 | fail |
| AVAXUSDT | 1069 | 63.456 | 0.0594 | 5/6 | 23.69 | 0.1798 | 0.33 | 0.06232830498773151 | pass |
| SOLUSDT | 1070 | 15.4297 | 0.0144 | 4/6 | 34.4809 | 0.0433 | 0.333 | 0.3526535806655581 | pass |
| **pooled** | 3196 | 73.0322 | 0.0229 | 3/6 | 70.6394 (seq) | - | - | 0.15236132905369332 | - |

Holm survivors (alpha 0.05): []

