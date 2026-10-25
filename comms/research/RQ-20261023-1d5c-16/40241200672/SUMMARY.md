# Stage-0 (synthetic leg) -- squeeze 2h -- fail

FAIL: B: pooled net_r 111.9428 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); BE1: net_r/trade 0.0325 beats the baseline's 0.0319 by 0.0006 < the 0.05 materiality bar; ST12: net_r/trade 0.0231 beats the baseline's 0.0319 by -0.0088 < the 0.05 materiality bar; WIDE: net_r/trade -0.0721 beats the baseline's 0.0319 by -0.104 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 111.9428 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 602 | 16.0994 | 0.0267 | 3/6 | 28.4863 | 0.015 | 1.781 | 0.3067448852835125 | fail |
| LINKUSDT | 564 | -11.8746 | -0.0211 | 3/6 | 43.0973 | -0.0111 | 1.889 | 0.6609293900546043 | fail |
| DOGEUSDT | 605 | 38.529 | 0.0637 | 6/6 | 25.3886 | 0.0352 | 1.811 | 0.143320068199696 | pass |
| LTCUSDT | 607 | -3.1503 | -0.0052 | 3/6 | 27.3284 | -0.0028 | 1.831 | 0.5407050660572673 | fail |
| BCHUSDT | 584 | 41.2339 | 0.0706 | 4/6 | 29.6604 | 0.0387 | 1.826 | 0.11947966959109513 | pass |
| DOTUSDT | 552 | 31.1088 | 0.0564 | 4/6 | 38.8236 | 0.0292 | 1.93 | 0.17876772310724032 | pass |
| **pooled** | 3514 | 111.9428 | 0.0319 | 4/6 | 77.414 (seq) | - | - | 0.08167184891155116 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0325 beats the baseline's 0.0319 by 0.0006 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 608 | 9.2972 | 0.0153 | 2/6 | 26.7659 | 0.0088 | 1.735 | 0.38015603037166024 | fail |
| LINKUSDT | 575 | -19.2479 | -0.0335 | 3/6 | 50.3242 | -0.0183 | 1.83 | 0.757072580575973 | fail |
| DOGEUSDT | 614 | 39.2556 | 0.0639 | 6/6 | 24.6362 | 0.0363 | 1.759 | 0.1380848855800188 | pass |
| LTCUSDT | 616 | -2.457 | -0.004 | 3/6 | 29.2716 | -0.0022 | 1.774 | 0.5320811830561087 | fail |
| BCHUSDT | 591 | 52.4778 | 0.0888 | 5/6 | 36.2381 | 0.0499 | 1.781 | 0.07301504965396166 | pass |
| DOTUSDT | 558 | 36.2988 | 0.0651 | 4/6 | 38.3446 | 0.0345 | 1.885 | 0.14124672409264677 | pass |
| **pooled** | 3562 | 115.6209 | 0.0325 | 5/6 | 89.4933 (seq) | - | - | 0.07349507942124667 | - |

Holm survivors (alpha 0.05): []

## arm `ST12` (candidate) -- fail -- net_r/trade 0.0231 beats the baseline's 0.0319 by -0.0088 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 781 | 10.1152 | 0.013 | 3/6 | 24.9176 | 0.0116 | 1.113 | 0.3789576594959987 | fail |
| LINKUSDT | 732 | 5.3935 | 0.0074 | 2/6 | 36.3687 | 0.0062 | 1.186 | 0.42481082554865646 | fail |
| DOGEUSDT | 783 | 54.698 | 0.0699 | 5/6 | 14.8372 | 0.067 | 1.043 | 0.0627365389980497 | pass |
| LTCUSDT | 807 | -9.5653 | -0.0119 | 3/6 | 25.6628 | -0.011 | 1.082 | 0.6227600706135887 | fail |
| BCHUSDT | 764 | 21.8116 | 0.0285 | 4/6 | 27.8637 | 0.0266 | 1.075 | 0.26225170548309296 | pass |
| DOTUSDT | 739 | 24.0627 | 0.0326 | 3/6 | 32.1861 | 0.0279 | 1.168 | 0.22550556193499577 | fail |
| **pooled** | 4606 | 106.511 | 0.0231 | 4/6 | 62.9175 (seq) | - | - | 0.08947985578219769 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- fail -- net_r/trade -0.0721 beats the baseline's 0.0319 by -0.104 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 49 | -12.8104 | -0.2614 | 1/6 | 13.8947 | -0.1941 | 1.347 | 0.9331672161359721 | fail |
| LINKUSDT | 37 | 4.9148 | 0.1328 | 4/6 | 7.0965 | 0.074 | 1.795 | 0.3073099538586652 | indeterminate |
| DOGEUSDT | 86 | 1.4129 | 0.0164 | 2/6 | 14.6327 | 0.011 | 1.487 | 0.460437494944082 | fail |
| LTCUSDT | 71 | -9.7581 | -0.1374 | 2/6 | 21.9979 | -0.0738 | 1.862 | 0.827916248375784 | fail |
| BCHUSDT | 76 | -12.7626 | -0.1679 | 1/6 | 17.6943 | -0.1087 | 1.545 | 0.8794621137796759 | fail |
| DOTUSDT | 53 | 2.1934 | 0.0414 | 3/6 | 12.1729 | 0.0238 | 1.736 | 0.4165636827429019 | fail |
| **pooled** | 372 | -26.8101 | -0.0721 | 2/6 | 39.2675 (seq) | - | - | 0.8458944040657195 | - |

Holm survivors (alpha 0.05): []

