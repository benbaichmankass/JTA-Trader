# Stage-0 (synthetic leg) -- trend 15m -- fail

FAIL: B: pooled net_r <= 0 or folds short; D96: net_r/trade -0.0873 beats the baseline's -0.0903 by 0.003 < the 0.05 materiality bar; D192: net_r/trade -0.0757 beats the baseline's -0.0903 by 0.0146 < the 0.05 materiality bar; D384: net_r/trade -0.0576 beats the baseline's -0.0903 by 0.0327 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.67 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 4511 | -510.5315 | -0.1132 | 0/6 | 546.0277 | -0.5116 | 0.221 | 0.9999999999043571 | fail |
| AVAXUSDT | 4630 | -272.301 | -0.0588 | 0/6 | 310.1828 | -0.2713 | 0.217 | 0.9993207470444823 | fail |
| SOLUSDT | 4544 | -453.3581 | -0.0998 | 0/6 | 455.2246 | -0.4491 | 0.222 | 0.9999999944094397 | fail |
| **pooled** | 13685 | -1236.1903 | -0.0903 | 0/6 | 1291.719 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `D96` (candidate) -- fail -- net_r/trade -0.0873 beats the baseline's -0.0903 by 0.003 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 2088 | -178.8981 | -0.0857 | 0/6 | 205.6618 | -0.3838 | 0.223 | 0.9993558373928152 | fail |
| AVAXUSDT | 2197 | -152.3804 | -0.0694 | 1/6 | 172.9136 | -0.32 | 0.217 | 0.9957300168312226 | fail |
| SOLUSDT | 2133 | -228.7639 | -0.1072 | 0/6 | 241.76 | -0.4736 | 0.226 | 0.9999908667975924 | fail |
| **pooled** | 6418 | -560.0446 | -0.0873 | 0/6 | 606.0066 (seq) | - | - | 0.9999999968674008 | - |

Holm survivors (alpha 0.05): []

## arm `D192` (candidate) -- fail -- net_r/trade -0.0757 beats the baseline's -0.0903 by 0.0146 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1383 | -122.5498 | -0.0886 | 0/6 | 141.8672 | -0.4295 | 0.206 | 0.996458169254735 | fail |
| AVAXUSDT | 1468 | -65.4236 | -0.0446 | 1/6 | 74.5368 | -0.2104 | 0.212 | 0.9245194533859039 | fail |
| SOLUSDT | 1413 | -134.992 | -0.0955 | 1/6 | 146.0285 | -0.4361 | 0.219 | 0.9990157439242394 | fail |
| **pooled** | 4264 | -322.9645 | -0.0757 | 0/6 | 348.8246 (seq) | - | - | 0.9999836438777788 | - |

Holm survivors (alpha 0.05): []

## arm `D384` (candidate) -- fail -- net_r/trade -0.0576 beats the baseline's -0.0903 by 0.0327 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 892 | -41.9523 | -0.047 | 2/6 | 60.977 | -0.2299 | 0.205 | 0.8725165339013521 | fail |
| AVAXUSDT | 971 | -52.0342 | -0.0536 | 2/6 | 61.4639 | -0.2644 | 0.203 | 0.9197191907953879 | fail |
| SOLUSDT | 922 | -66.4981 | -0.0721 | 0/6 | 80.0461 | -0.345 | 0.209 | 0.9748677958108828 | fail |
| **pooled** | 2785 | -160.4828 | -0.0576 | 0/6 | 185.7418 (seq) | - | - | 0.9949941684703127 | - |

Holm survivors (alpha 0.05): []

