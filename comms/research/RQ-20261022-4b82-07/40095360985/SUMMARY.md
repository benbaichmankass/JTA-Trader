# Stage-0 (synthetic leg) -- trend 1h -- fail

FAIL: B: pooled net_r 180.7345 > 0 with 6 folds positive and 3 of 6 powered cells pass (breadth floor 3); FLAT: net_r/trade -0.0089 beats the baseline's 0.0203 by -0.0292 < the 0.05 materiality bar; FLATE: net_r/trade -0.0097 beats the baseline's 0.0203 by -0.03 < the 0.05 materiality bar; CONF: net_r/trade 0.0386 beats the baseline's 0.0203 by 0.0183 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 180.7345 > 0 with 6 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 1504 | -35.4263 | -0.0236 | 2/6 | 66.253 | -0.0283 | 0.833 | 0.7694508983910783 | fail |
| SOLUSDT | 1499 | -8.996 | -0.006 | 2/6 | 53.1841 | -0.0069 | 0.875 | 0.5748552120224457 | fail |
| XRPUSDT | 1426 | 140.3968 | 0.0985 | 5/6 | 22.5867 | 0.117 | 0.841 | 0.012208260908593192 | pass |
| LINKUSDT | 1537 | 0.0368 | 0.0 | 3/6 | 33.4525 | 0.0 | 0.879 | 0.49970777069775685 | fail |
| ADAUSDT | 1484 | 29.2657 | 0.0197 | 4/6 | 33.356 | 0.0228 | 0.866 | 0.28616891766448427 | pass |
| DOGEUSDT | 1446 | 55.4602 | 0.0384 | 6/6 | 36.2905 | 0.0467 | 0.821 | 0.1332232973903389 | pass |
| **pooled** | 8896 | 180.7345 | 0.0203 | 6/6 | 116.253 (seq) | - | - | 0.07682721612968846 | - |

Holm survivors (alpha 0.05): []

## arm `FLAT` (candidate) -- fail -- net_r/trade -0.0089 beats the baseline's 0.0203 by -0.0292 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 1974 | -23.2168 | -0.0118 | 4/6 | 79.4797 | -0.0295 | 0.399 | 0.7020917791756329 | fail |
| SOLUSDT | 2052 | -70.1498 | -0.0342 | 1/6 | 80.7443 | -0.0816 | 0.419 | 0.9553438355337949 | fail |
| XRPUSDT | 1927 | 35.2277 | 0.0183 | 5/6 | 30.5731 | 0.0461 | 0.397 | 0.27699071600515557 | pass |
| LINKUSDT | 2108 | -6.4271 | -0.003 | 3/6 | 42.88 | -0.0072 | 0.423 | 0.5566674916397587 | fail |
| ADAUSDT | 2049 | -48.8927 | -0.0239 | 2/6 | 65.531 | -0.0583 | 0.409 | 0.8529839155484489 | fail |
| DOGEUSDT | 1938 | 5.8922 | 0.003 | 3/6 | 38.9318 | 0.0078 | 0.392 | 0.45128138605456236 | fail |
| **pooled** | 12048 | -107.561 | -0.0089 | 1/6 | 223.8494 (seq) | - | - | 0.8211292149726612 | - |

Holm survivors (alpha 0.05): []

## arm `FLATE` (candidate) -- fail -- net_r/trade -0.0097 beats the baseline's 0.0203 by -0.03 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 1678 | 10.5784 | 0.0063 | 4/6 | 62.9583 | 0.0142 | 0.444 | 0.40130021321033515 | pass |
| SOLUSDT | 1769 | -63.8947 | -0.0361 | 1/6 | 81.5248 | -0.0786 | 0.459 | 0.9451845742137213 | fail |
| XRPUSDT | 1651 | 29.151 | 0.0177 | 4/6 | 37.9414 | 0.0405 | 0.435 | 0.30768861514757984 | pass |
| LINKUSDT | 1820 | -8.063 | -0.0044 | 3/6 | 37.4799 | -0.0095 | 0.465 | 0.5761991248171558 | fail |
| ADAUSDT | 1780 | -63.1107 | -0.0355 | 0/6 | 71.573 | -0.0794 | 0.447 | 0.9177016799876765 | fail |
| DOGEUSDT | 1654 | -5.3925 | -0.0033 | 3/6 | 38.822 | -0.0076 | 0.432 | 0.5485007691635755 | fail |
| **pooled** | 10352 | -100.7279 | -0.0097 | 2/6 | 204.6256 (seq) | - | - | 0.8159475383541447 | - |

Holm survivors (alpha 0.05): []

## arm `CONF` (candidate) -- fail -- net_r/trade 0.0386 beats the baseline's 0.0203 by 0.0183 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ETHUSDT | 1042 | 6.0829 | 0.0058 | 4/6 | 26.0983 | 0.0062 | 0.946 | 0.4412975041224024 | pass |
| SOLUSDT | 1036 | 45.1713 | 0.0436 | 4/6 | 26.0007 | 0.044 | 0.991 | 0.12011752717203272 | pass |
| XRPUSDT | 986 | 70.9818 | 0.072 | 5/6 | 31.4918 | 0.0748 | 0.963 | 0.04214699469879085 | pass |
| LINKUSDT | 1101 | 5.3505 | 0.0049 | 4/6 | 54.8426 | 0.0051 | 0.955 | 0.44727242009157087 | pass |
| ADAUSDT | 1039 | 51.4681 | 0.0495 | 4/6 | 27.8858 | 0.0497 | 0.998 | 0.12551970788414352 | pass |
| DOGEUSDT | 977 | 59.66 | 0.0611 | 4/6 | 32.4133 | 0.0638 | 0.957 | 0.07508302655133758 | pass |
| **pooled** | 6181 | 238.7136 | 0.0386 | 4/6 | 75.9726 (seq) | - | - | 0.009092957131621898 | - |

Holm survivors (alpha 0.05): []

