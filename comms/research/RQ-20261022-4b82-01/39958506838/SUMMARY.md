# Stage-0 (synthetic leg) -- trend 1h -- fail

FAIL: B: pooled net_r 239.0345 > 0 with 6 folds positive and 4 of 6 powered cells pass (breadth floor 3); D40: net_r/trade 0.0314 beats the baseline's 0.0269 by 0.0045 < the 0.05 materiality bar; D55: net_r/trade 0.0294 beats the baseline's 0.0269 by 0.0025 < the 0.05 materiality bar; D40A: net_r/trade 0.0181 beats the baseline's 0.0269 by -0.0088 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 239.0345 > 0 with 6 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| LINKUSDT | 1537 | 0.0368 | 0.0 | 3/6 | 33.4525 | 0.0 | 0.879 | 0.49970777069775685 | fail |
| AAVEUSDT | 1433 | 48.1423 | 0.0336 | 4/6 | 26.6785 | 0.0375 | 0.896 | 0.17707125867491258 | pass |
| BNBUSDT | 1566 | -34.2631 | -0.0219 | 2/6 | 71.2625 | -0.0276 | 0.794 | 0.7612572049114024 | fail |
| DOGEUSDT | 1446 | 55.4602 | 0.0384 | 6/6 | 36.2905 | 0.0467 | 0.821 | 0.1332232973903389 | pass |
| ADAUSDT | 1484 | 29.2657 | 0.0197 | 4/6 | 33.356 | 0.0228 | 0.866 | 0.28616891766448427 | pass |
| XRPUSDT | 1426 | 140.3968 | 0.0985 | 5/6 | 22.5867 | 0.117 | 0.841 | 0.012208260908593192 | pass |
| **pooled** | 8892 | 239.0345 | 0.0269 | 6/6 | 101.159 (seq) | - | - | 0.031337323977747904 | - |

Holm survivors (alpha 0.05): []

## arm `D40` (candidate) -- fail -- net_r/trade 0.0314 beats the baseline's 0.0269 by 0.0045 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| LINKUSDT | 1185 | -10.77 | -0.0091 | 3/6 | 48.0782 | -0.0105 | 0.862 | 0.5997892383488136 | fail |
| AAVEUSDT | 1078 | 60.2045 | 0.0558 | 4/6 | 24.3182 | 0.063 | 0.887 | 0.09650841263297655 | pass |
| BNBUSDT | 1172 | 14.7367 | 0.0126 | 3/6 | 47.0124 | 0.0171 | 0.735 | 0.3647779100820114 | fail |
| DOGEUSDT | 1095 | 71.9059 | 0.0657 | 6/6 | 22.1845 | 0.0932 | 0.704 | 0.062186733221955115 | pass |
| ADAUSDT | 1111 | 42.2281 | 0.038 | 3/6 | 31.443 | 0.0456 | 0.833 | 0.17754061405782817 | fail |
| XRPUSDT | 1116 | 34.1944 | 0.0306 | 5/6 | 23.5733 | 0.0425 | 0.721 | 0.21862305232349616 | pass |
| **pooled** | 6757 | 212.5006 | 0.0314 | 5/6 | 83.3921 (seq) | - | - | 0.026063776469213096 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade 0.0294 beats the baseline's 0.0269 by 0.0025 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| LINKUSDT | 1000 | -10.9034 | -0.0109 | 2/6 | 47.7961 | -0.013 | 0.839 | 0.609505782705072 | fail |
| AAVEUSDT | 912 | 84.1333 | 0.0923 | 4/6 | 18.534 | 0.1025 | 0.9 | 0.028063460073517652 | pass |
| BNBUSDT | 1003 | -11.6677 | -0.0116 | 3/6 | 45.4149 | -0.0161 | 0.723 | 0.6191379742194054 | fail |
| DOGEUSDT | 916 | 32.8424 | 0.0359 | 4/6 | 37.2833 | 0.0544 | 0.659 | 0.21844830945657545 | pass |
| ADAUSDT | 945 | 48.2955 | 0.0511 | 5/6 | 28.5731 | 0.0618 | 0.827 | 0.13074872239013707 | pass |
| XRPUSDT | 918 | 24.9488 | 0.0272 | 4/6 | 30.328 | 0.0382 | 0.712 | 0.26378408511932716 | pass |
| **pooled** | 5694 | 167.649 | 0.0294 | 4/6 | 120.9695 (seq) | - | - | 0.047999976227840746 | - |

Holm survivors (alpha 0.05): []

## arm `D40A` (candidate) -- fail -- net_r/trade 0.0181 beats the baseline's 0.0269 by -0.0088 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| LINKUSDT | 971 | -4.2911 | -0.0044 | 3/6 | 43.1188 | -0.0051 | 0.875 | 0.5444504503412373 | fail |
| AAVEUSDT | 875 | 65.3304 | 0.0747 | 4/6 | 15.2271 | 0.0859 | 0.869 | 0.06325620546148764 | pass |
| BNBUSDT | 953 | -46.2142 | -0.0485 | 2/6 | 84.1721 | -0.0644 | 0.753 | 0.8890904652731562 | fail |
| DOGEUSDT | 905 | 43.4169 | 0.048 | 5/6 | 26.0183 | 0.067 | 0.716 | 0.14412995158067765 | pass |
| ADAUSDT | 914 | 40.368 | 0.0442 | 3/6 | 26.4036 | 0.053 | 0.833 | 0.16998205621933565 | fail |
| XRPUSDT | 911 | 1.6915 | 0.0019 | 5/6 | 44.1928 | 0.0025 | 0.738 | 0.4831126431071004 | pass |
| **pooled** | 5529 | 100.3012 | 0.0181 | 4/6 | 118.7886 (seq) | - | - | 0.15530853511312914 | - |

Holm survivors (alpha 0.05): []

