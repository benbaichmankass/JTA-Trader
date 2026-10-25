# Stage-0 (synthetic leg) -- squeeze 2h -- fail

FAIL: B: pooled net_r 142.6169 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3); BE1: net_r/trade 0.0392 beats the baseline's 0.0406 by -0.0014 < the 0.05 materiality bar; WIDE: net_r/trade -0.0858 beats the baseline's 0.0406 by -0.1264 < the 0.05 materiality bar; STOP35: net_r/trade 0.0205 beats the baseline's 0.0406 by -0.0201 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 142.6169 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 597 | 47.3631 | 0.0793 | 4/6 | 18.0138 | 0.0442 | 1.797 | 0.11684580947557871 | pass |
| ETHUSDT | 582 | 9.2566 | 0.0159 | 4/6 | 27.6671 | 0.0089 | 1.791 | 0.386744889986095 | pass |
| SOLUSDT | 539 | -34.5971 | -0.0642 | 2/6 | 49.7729 | -0.035 | 1.834 | 0.8841028018923849 | fail |
| XRPUSDT | 616 | 44.8013 | 0.0727 | 5/6 | 25.501 | 0.0417 | 1.745 | 0.13929027792384224 | pass |
| ADAUSDT | 573 | 59.6936 | 0.1042 | 4/6 | 19.5802 | 0.0562 | 1.853 | 0.059783013214864344 | pass |
| BNBUSDT | 602 | 16.0994 | 0.0267 | 3/6 | 28.4863 | 0.015 | 1.781 | 0.3067448852835125 | fail |
| **pooled** | 3509 | 142.6169 | 0.0406 | 4/6 | 61.4867 (seq) | - | - | 0.05135782465340216 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0392 beats the baseline's 0.0406 by -0.0014 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 602 | 48.7785 | 0.081 | 4/6 | 16.9351 | 0.0458 | 1.769 | 0.10997272550063758 | pass |
| ETHUSDT | 590 | 6.5663 | 0.0111 | 5/6 | 30.1188 | 0.0064 | 1.747 | 0.4184504195191826 | pass |
| SOLUSDT | 546 | -33.4604 | -0.0613 | 2/6 | 49.3605 | -0.0342 | 1.792 | 0.8760801903995017 | fail |
| XRPUSDT | 623 | 37.07 | 0.0595 | 4/6 | 28.818 | 0.0347 | 1.714 | 0.17685993536274758 | pass |
| ADAUSDT | 575 | 70.6506 | 0.1229 | 4/6 | 19.2399 | 0.067 | 1.833 | 0.03244470143145067 | pass |
| BNBUSDT | 608 | 9.2972 | 0.0153 | 2/6 | 26.7659 | 0.0088 | 1.735 | 0.38015603037166024 | fail |
| **pooled** | 3544 | 138.9005 | 0.0392 | 4/6 | 59.5679 (seq) | - | - | 0.053403656450371706 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- fail -- net_r/trade -0.0858 beats the baseline's 0.0406 by -0.1264 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 103 | -12.2029 | -0.1185 | 2/6 | 24.3238 | -0.0848 | 1.397 | 0.7953528192893562 | fail |
| ETHUSDT | 93 | -21.8522 | -0.235 | 2/6 | 27.3223 | -0.1811 | 1.298 | 0.9586272437774904 | fail |
| SOLUSDT | 38 | 1.5035 | 0.0396 | 3/6 | 9.981 | 0.029 | 1.366 | 0.43720036976428084 | indeterminate |
| XRPUSDT | 72 | 6.2864 | 0.0873 | 3/6 | 16.5594 | 0.0616 | 1.417 | 0.32466098703374907 | fail |
| ADAUSDT | 63 | 3.2238 | 0.0512 | 4/6 | 6.0263 | 0.029 | 1.765 | 0.3676753362577465 | pass |
| BNBUSDT | 49 | -12.8104 | -0.2614 | 1/6 | 13.8947 | -0.1941 | 1.347 | 0.9331672161359721 | fail |
| **pooled** | 418 | -35.8518 | -0.0858 | 2/6 | 68.408 (seq) | - | - | 0.8958392034350358 | - |

Holm survivors (alpha 0.05): []

## arm `STOP35` (candidate) -- fail -- net_r/trade 0.0205 beats the baseline's 0.0406 by -0.0201 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 575 | 10.4783 | 0.0182 | 5/6 | 13.6008 | 0.0096 | 1.9 | 0.35635432964925284 | pass |
| ETHUSDT | 558 | -0.6667 | -0.0012 | 4/6 | 17.6211 | -0.0006 | 1.911 | 0.5113311407253808 | fail |
| SOLUSDT | 517 | -28.2295 | -0.0546 | 2/6 | 39.544 | -0.0279 | 1.956 | 0.9091550846184958 | fail |
| XRPUSDT | 591 | 38.6564 | 0.0654 | 5/6 | 10.5847 | 0.0347 | 1.886 | 0.0960948842327578 | pass |
| ADAUSDT | 556 | 39.502 | 0.071 | 5/6 | 10.7659 | 0.0361 | 1.967 | 0.07813221190602093 | pass |
| BNBUSDT | 576 | 9.2754 | 0.0161 | 3/6 | 20.9111 | 0.0083 | 1.94 | 0.3437361440971378 | fail |
| **pooled** | 3373 | 69.0163 | 0.0205 | 4/6 | 51.2844 (seq) | - | - | 0.13724545604751354 | - |

Holm survivors (alpha 0.05): []

