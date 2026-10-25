# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; D40: net_r/trade 0.0411 beats the baseline's 0.0091 by 0.032 < the 0.05 materiality bar; D55: net_r/trade 0.0308 beats the baseline's 0.0091 by 0.0217 < the 0.05 materiality bar; D40A: net_r/trade 0.0025 beats the baseline's 0.0091 by -0.0066 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 402 | 4.0737 | 0.0101 | 3/6 | 27.8344 | 0.0034 | 3.006 | 0.4386536587516722 | fail |
| LINKUSDT | 414 | -2.6144 | -0.0063 | 3/6 | 19.8954 | -0.002 | 3.157 | 0.5425191795874167 | fail |
| DOGEUSDT | 361 | 32.484 | 0.09 | 5/6 | 12.1395 | 0.0297 | 3.027 | 0.10389564213176183 | pass |
| LTCUSDT | 384 | -26.2286 | -0.0683 | 1/6 | 33.0718 | -0.0221 | 3.092 | 0.8803404962773794 | fail |
| BCHUSDT | 370 | 29.1577 | 0.0788 | 4/6 | 18.536 | 0.0244 | 3.231 | 0.13110232259452426 | pass |
| DOTUSDT | 367 | -15.895 | -0.0433 | 2/6 | 26.7893 | -0.0119 | 3.646 | 0.7627974431457611 | fail |
| **pooled** | 2298 | 20.9764 | 0.0091 | 3/6 | 59.9008 (seq) | - | - | 0.36366982369872114 | - |

Holm survivors (alpha 0.05): []

## arm `D40` (candidate) -- fail -- net_r/trade 0.0411 beats the baseline's 0.0091 by 0.032 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 290 | 27.2947 | 0.0941 | 4/6 | 14.9749 | 0.034 | 2.766 | 0.11105833649629082 | pass |
| LINKUSDT | 310 | -0.5099 | -0.0016 | 3/6 | 18.3001 | -0.0006 | 2.819 | 0.5096798609936097 | fail |
| DOGEUSDT | 268 | 39.016 | 0.1456 | 5/6 | 14.3786 | 0.0538 | 2.705 | 0.05417925848802008 | pass |
| LTCUSDT | 282 | -16.843 | -0.0597 | 2/6 | 30.0972 | -0.0209 | 2.864 | 0.8108849624964624 | fail |
| BCHUSDT | 277 | 36.6936 | 0.1325 | 4/6 | 12.0902 | 0.0431 | 3.072 | 0.05707339526540245 | pass |
| DOTUSDT | 285 | -15.2919 | -0.0537 | 0/6 | 17.0934 | -0.0149 | 3.604 | 0.7893562831124723 | fail |
| **pooled** | 1712 | 70.359 | 0.0411 | 4/6 | 40.6208 (seq) | - | - | 0.09147285002642308 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade 0.0308 beats the baseline's 0.0091 by 0.0217 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 172 | 27.721 | 0.1612 | 4/6 | 14.0283 | 0.025 | 6.453 | 0.1592682933903845 | pass |
| LINKUSDT | 184 | -2.5022 | -0.0136 | 3/6 | 26.6069 | -0.0019 | 7.006 | 0.5364645156329386 | fail |
| DOGEUSDT | 179 | 21.1531 | 0.1182 | 4/6 | 25.4787 | 0.0221 | 5.34 | 0.21213521181830725 | pass |
| LTCUSDT | 169 | -20.7683 | -0.1229 | 2/6 | 44.0366 | -0.0163 | 7.53 | 0.8493233237779407 | fail |
| BCHUSDT | 162 | 18.2525 | 0.1127 | 3/6 | 33.9595 | 0.0148 | 7.61 | 0.22500222812500853 | fail |
| DOTUSDT | 170 | -11.9945 | -0.0706 | 2/6 | 24.6767 | -0.0093 | 7.598 | 0.7015641735565066 | fail |
| **pooled** | 1036 | 31.8602 | 0.0308 | 3/6 | 104.6208 (seq) | - | - | 0.30025273128280017 | - |

Holm survivors (alpha 0.05): []

## arm `D40A` (candidate) -- fail -- net_r/trade 0.0025 beats the baseline's 0.0091 by -0.0066 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 237 | 13.7127 | 0.0579 | 3/6 | 11.9092 | 0.0212 | 2.723 | 0.25380687504543153 | fail |
| LINKUSDT | 254 | -12.2221 | -0.0481 | 2/6 | 24.2636 | -0.0156 | 3.087 | 0.7543292487795525 | fail |
| DOGEUSDT | 224 | 15.1194 | 0.0675 | 3/6 | 21.4333 | 0.0238 | 2.83 | 0.2155903318628234 | fail |
| LTCUSDT | 241 | -27.343 | -0.1135 | 2/6 | 31.1067 | -0.0408 | 2.778 | 0.9518006312716931 | fail |
| BCHUSDT | 227 | 24.4303 | 0.1076 | 5/6 | 17.1314 | 0.0351 | 3.07 | 0.1265806193566772 | pass |
| DOTUSDT | 232 | -10.1108 | -0.0436 | 2/6 | 14.4177 | -0.0123 | 3.544 | 0.7304230387733244 | fail |
| **pooled** | 1415 | 3.5877 | 0.0025 | 3/6 | 43.9976 (seq) | - | - | 0.4688310293235867 | - |

Holm survivors (alpha 0.05): []

