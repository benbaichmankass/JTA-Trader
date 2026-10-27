# Stage-0 (synthetic leg) -- trend 15m -- fail

FAIL: B: pooled net_r <= 0 or folds short; M: net_r/trade -0.01 beats the baseline's -0.0502 by 0.0402 < the 0.05 materiality bar; G90M: pooled passes but only 2 of 3 powered cells pass (< 3): one symbol's edge. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.67 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 4539 | -340.5867 | -0.075 | 0/6 | 377.2894 | -0.3391 | 0.221 | 0.9999824757241658 | fail |
| AVAXUSDT | 4663 | -82.0847 | -0.0176 | 1/6 | 133.6233 | -0.0812 | 0.217 | 0.8230906317774104 | fail |
| SOLUSDT | 4580 | -269.4264 | -0.0588 | 0/6 | 275.1965 | -0.2651 | 0.222 | 0.9994351284287972 | fail |
| **pooled** | 13782 | -692.1026 | -0.0502 | 0/6 | 752.7379 (seq) | - | - | 0.9999988470468608 | - |

Holm survivors (alpha 0.05): []

## arm `M` (candidate) -- fail -- net_r/trade -0.01 beats the baseline's -0.0502 by 0.0402 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 4539 | -152.8633 | -0.0337 | 1/6 | 192.8333 | -0.1522 | 0.221 | 0.9685039264859405 | fail |
| AVAXUSDT | 4663 | 104.257 | 0.0224 | 6/6 | 40.4705 | 0.1031 | 0.217 | 0.11955321852069883 | pass |
| SOLUSDT | 4580 | -88.9845 | -0.0194 | 1/6 | 105.6815 | -0.0876 | 0.222 | 0.8590650966981918 | fail |
| **pooled** | 13782 | -137.5931 | -0.01 | 1/6 | 209.7487 (seq) | - | - | 0.8263115743055753 | - |

Holm survivors (alpha 0.05): []

## arm `G90M` (candidate) -- fail -- pooled passes but only 2 of 3 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1060 | 20.5629 | 0.0194 | 3/6 | 24.0282 | 0.0597 | 0.325 | 0.3088570042330072 | fail |
| AVAXUSDT | 1071 | 89.8141 | 0.0839 | 5/6 | 21.5825 | 0.2543 | 0.33 | 0.014986156099257077 | pass |
| SOLUSDT | 1071 | 42.4141 | 0.0396 | 4/6 | 31.1807 | 0.119 | 0.333 | 0.14956621637954814 | pass |
| **pooled** | 3202 | 152.7893 | 0.0477 | 5/6 | 62.3713 (seq) | - | - | 0.0159842797656153 | - |

Holm survivors (alpha 0.05): ['AVAXUSDT']

