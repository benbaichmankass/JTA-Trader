# Stage-0 (synthetic leg) -- squeeze 2h -- fail

FAIL: B: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; BE1: net_r/trade 0.02 beats the baseline's 0.0196 by 0.0004 < the 0.05 materiality bar; WIDE: net_r/trade 0.0117 beats the baseline's 0.0196 by -0.0079 < the 0.05 materiality bar; STOP35: net_r/trade 0.02 beats the baseline's 0.0196 by 0.0004 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 532 | 40.373 | 0.0759 | 4/6 | 22.3606 | 0.04 | 1.895 | 0.12330878574435294 | pass |
| NEARUSDT | 535 | -3.5238 | -0.0066 | 4/6 | 38.5156 | -0.0035 | 1.89 | 0.5472814452411262 | fail |
| ATOMUSDT | 560 | -19.8135 | -0.0354 | 3/6 | 57.9558 | -0.018 | 1.97 | 0.7626784304833794 | fail |
| FILUSDT | 553 | 30.1048 | 0.0544 | 3/6 | 27.6521 | 0.03 | 1.814 | 0.17105993769475314 | fail |
| TRXUSDT | 527 | -3.7878 | -0.0072 | 4/6 | 50.447 | -0.004 | 1.817 | 0.5494942280960962 | fail |
| ETCUSDT | 609 | 21.7103 | 0.0356 | 4/6 | 32.3399 | 0.0202 | 1.767 | 0.2726628503575011 | pass |
| **pooled** | 3316 | 65.062 | 0.0196 | 5/6 | 82.889 (seq) | - | - | 0.2018454965687001 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.02 beats the baseline's 0.0196 by 0.0004 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 542 | 32.7294 | 0.0604 | 4/6 | 24.6642 | 0.0329 | 1.833 | 0.17116560864332936 | pass |
| NEARUSDT | 543 | -5.0 | -0.0092 | 4/6 | 33.7373 | -0.005 | 1.839 | 0.5686431163720067 | fail |
| ATOMUSDT | 567 | -19.6214 | -0.0346 | 3/6 | 54.1549 | -0.018 | 1.919 | 0.7616081928504258 | fail |
| FILUSDT | 558 | 35.4582 | 0.0635 | 3/6 | 27.6018 | 0.0358 | 1.776 | 0.133139602627724 | fail |
| TRXUSDT | 535 | -6.9435 | -0.013 | 4/6 | 51.4553 | -0.0074 | 1.765 | 0.5907939801938381 | fail |
| ETCUSDT | 613 | 30.4901 | 0.0497 | 4/6 | 27.462 | 0.0284 | 1.748 | 0.19707341100940529 | pass |
| **pooled** | 3358 | 67.1128 | 0.02 | 5/6 | 80.9806 (seq) | - | - | 0.19284808287291544 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- fail -- net_r/trade 0.0117 beats the baseline's 0.0196 by -0.0079 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 41 | 7.9378 | 0.1936 | 3/6 | 5.0923 | 0.1273 | 1.52 | 0.16858419415766246 | fail |
| NEARUSDT | 51 | 1.6385 | 0.0321 | 3/6 | 5.2581 | 0.0155 | 2.075 | 0.43203526043486074 | fail |
| ATOMUSDT | 37 | -1.2794 | -0.0346 | 1/6 | 8.1978 | -0.0156 | 2.216 | 0.5800319306495418 | indeterminate |
| FILUSDT | 78 | -2.7282 | -0.035 | 4/6 | 12.1735 | -0.0233 | 1.499 | 0.6009247869578684 | fail |
| TRXUSDT | 38 | 3.2565 | 0.0857 | 2/6 | 7.8293 | 0.0435 | 1.969 | 0.3650456702303937 | indeterminate |
| ETCUSDT | 67 | -5.1683 | -0.0771 | 2/6 | 17.1622 | -0.0477 | 1.617 | 0.7032793039374813 | fail |
| **pooled** | 312 | 3.6565 | 0.0117 | 3/6 | 18.5638 (seq) | - | - | 0.4341156756532397 | - |

Holm survivors (alpha 0.05): []

## arm `STOP35` (candidate) -- fail -- net_r/trade 0.02 beats the baseline's 0.0196 by 0.0004 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 513 | 35.3828 | 0.069 | 4/6 | 16.8801 | 0.0345 | 1.998 | 0.0870618751374555 | pass |
| NEARUSDT | 510 | 1.9224 | 0.0038 | 4/6 | 24.9417 | 0.0018 | 2.064 | 0.4647445236003568 | pass |
| ATOMUSDT | 541 | -23.4336 | -0.0433 | 3/6 | 43.8581 | -0.0208 | 2.083 | 0.8852157450716556 | fail |
| FILUSDT | 521 | 36.3088 | 0.0697 | 4/6 | 19.1114 | 0.0346 | 2.014 | 0.05659385396927591 | pass |
| TRXUSDT | 506 | -0.0261 | -0.0001 | 4/6 | 34.2586 | -0.0 | 1.965 | 0.5004567069636582 | fail |
| ETCUSDT | 573 | 13.071 | 0.0228 | 4/6 | 23.2141 | 0.0117 | 1.954 | 0.30629031556354774 | pass |
| **pooled** | 3164 | 63.2287 | 0.02 | 5/6 | 57.7806 (seq) | - | - | 0.13205785399574826 | - |

Holm survivors (alpha 0.05): []

