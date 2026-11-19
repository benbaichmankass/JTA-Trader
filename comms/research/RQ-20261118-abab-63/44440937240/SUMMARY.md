# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; D55: net_r/trade -0.0138 beats the baseline's -0.015 by 0.0012 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| QTUMUSDT | 204 | 37.9963 | 0.1863 | 4/6 | 14.9659 | 0.0218 | 8.556 | 0.09173851216204537 | pass |
| ZRXUSDT | 228 | -17.7663 | -0.0779 | 2/6 | 27.1517 | -0.0107 | 7.295 | 0.7520172762429396 | fail |
| BATUSDT | 231 | -22.4092 | -0.097 | 3/6 | 48.3017 | -0.013 | 7.439 | 0.8147094928173082 | fail |
| RLCUSDT | 193 | 11.1155 | 0.0576 | 3/6 | 17.5635 | 0.0063 | 9.15 | 0.32177721535422266 | fail |
| KNCUSDT | 215 | -18.414 | -0.0856 | 2/6 | 26.5138 | -0.0104 | 8.242 | 0.7740620981018045 | fail |
| CRVUSDT | 193 | -9.4918 | -0.0492 | 2/6 | 21.6183 | -0.0052 | 9.447 | 0.6525875142276961 | fail |
| **pooled** | 1264 | -18.9676 | -0.015 | 2/6 | 95.5224 (seq) | - | - | 0.6198066002112798 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade -0.0138 beats the baseline's -0.015 by 0.0012 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| QTUMUSDT | 179 | 11.5491 | 0.0645 | 2/6 | 14.9476 | 0.0093 | 6.917 | 0.32119355938454386 | fail |
| ZRXUSDT | 177 | -2.3067 | -0.013 | 3/6 | 18.28 | -0.002 | 6.593 | 0.5361398492627452 | fail |
| BATUSDT | 174 | -13.9797 | -0.0803 | 3/6 | 37.9369 | -0.0109 | 7.378 | 0.7454842099587858 | fail |
| RLCUSDT | 155 | -2.8816 | -0.0186 | 2/6 | 23.8304 | -0.0022 | 8.542 | 0.5518907705289764 | fail |
| KNCUSDT | 177 | -12.0793 | -0.0682 | 2/6 | 22.4927 | -0.0101 | 6.752 | 0.6562511878929371 | fail |
| CRVUSDT | 167 | 5.4847 | 0.0328 | 2/6 | 17.6334 | 0.0039 | 8.318 | 0.41632856933869 | fail |
| **pooled** | 1029 | -14.2141 | -0.0138 | 3/6 | 62.6007 (seq) | - | - | 0.5917624656277742 | - |

Holm survivors (alpha 0.05): []

