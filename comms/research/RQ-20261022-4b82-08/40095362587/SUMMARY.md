# Stage-0 (synthetic leg) -- pullback 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short; BE1: net_r/trade -0.0016 beats the baseline's -0.0012 by -0.0004 < the 0.05 materiality bar; ST: net_r/trade -0.0364 beats the baseline's -0.0012 by -0.0352 < the 0.05 materiality bar; DIA: net_r/trade -0.0132 beats the baseline's -0.0012 by -0.012 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 861 | -43.4252 | -0.0504 | 3/6 | 79.7591 | -0.0237 | 2.124 | 0.8165461137262789 | fail |
| DOGEUSDT | 776 | 96.1406 | 0.1239 | 4/6 | 35.6635 | 0.0519 | 2.387 | 0.04245890446109479 | pass |
| LINKUSDT | 845 | 8.0026 | 0.0095 | 3/6 | 54.9511 | 0.0044 | 2.148 | 0.43554392822115645 | fail |
| LTCUSDT | 782 | -26.6583 | -0.0341 | 2/6 | 48.1148 | -0.0147 | 2.327 | 0.7169068164668024 | fail |
| BCHUSDT | 836 | -18.5434 | -0.0222 | 3/6 | 78.4425 | -0.0103 | 2.156 | 0.6403095843426998 | fail |
| DOTUSDT | 815 | -21.3178 | -0.0262 | 3/6 | 53.5982 | -0.0124 | 2.111 | 0.6647991851245214 | fail |
| **pooled** | 4915 | -5.8023 | -0.0012 | 4/6 | 149.3775 (seq) | - | - | 0.5187810031177065 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade -0.0016 beats the baseline's -0.0012 by -0.0004 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 979 | -55.131 | -0.0563 | 3/6 | 89.0878 | -0.0313 | 1.8 | 0.8835426004641814 | fail |
| DOGEUSDT | 921 | 64.732 | 0.0703 | 4/6 | 27.2469 | 0.0367 | 1.914 | 0.11710315075747268 | pass |
| LINKUSDT | 944 | 36.2466 | 0.0384 | 4/6 | 43.089 | 0.0208 | 1.844 | 0.23534326291588675 | pass |
| LTCUSDT | 908 | -23.0966 | -0.0254 | 2/6 | 45.9171 | -0.0134 | 1.899 | 0.6902991205722027 | fail |
| BCHUSDT | 960 | -29.4339 | -0.0307 | 4/6 | 50.8198 | -0.0172 | 1.785 | 0.7228105148876957 | fail |
| DOTUSDT | 915 | -2.2536 | -0.0025 | 3/6 | 54.7541 | -0.0014 | 1.811 | 0.5179242389843807 | fail |
| **pooled** | 5627 | -8.939 | -0.0016 | 3/6 | 124.2033 (seq) | - | - | 0.5293219140684196 | - |

Holm survivors (alpha 0.05): []

## arm `ST` (candidate) -- fail -- net_r/trade -0.0364 beats the baseline's -0.0012 by -0.0352 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 1876 | -105.0184 | -0.056 | 0/6 | 105.1812 | -0.083 | 0.675 | 0.977658204110105 | fail |
| DOGEUSDT | 1950 | -26.7008 | -0.0137 | 2/6 | 64.5252 | -0.0221 | 0.62 | 0.6885277250306221 | fail |
| LINKUSDT | 1771 | -31.6136 | -0.0179 | 3/6 | 47.2484 | -0.0248 | 0.719 | 0.7489317096904944 | fail |
| LTCUSDT | 1837 | -87.9489 | -0.0479 | 0/6 | 97.1388 | -0.072 | 0.665 | 0.9707803251052632 | fail |
| BCHUSDT | 1885 | -118.3334 | -0.0628 | 2/6 | 139.5774 | -0.0978 | 0.642 | 0.9909499577232915 | fail |
| DOTUSDT | 1705 | -31.1981 | -0.0183 | 3/6 | 99.3739 | -0.0258 | 0.709 | 0.743538044480432 | fail |
| **pooled** | 11024 | -400.8085 | -0.0364 | 1/6 | 431.0929 (seq) | - | - | 0.999500180899766 | - |

Holm survivors (alpha 0.05): []

## arm `DIA` (candidate) -- fail -- net_r/trade -0.0132 beats the baseline's -0.0012 by -0.012 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 752 | -0.5334 | -0.0007 | 3/6 | 44.8368 | -0.0004 | 1.813 | 0.5048750968114927 | fail |
| DOGEUSDT | 743 | 20.035 | 0.027 | 4/6 | 33.8018 | 0.014 | 1.932 | 0.3320685475242414 | pass |
| LINKUSDT | 731 | 2.6245 | 0.0036 | 4/6 | 38.5155 | 0.002 | 1.817 | 0.4738201768142053 | pass |
| LTCUSDT | 711 | -53.2329 | -0.0749 | 2/6 | 68.3745 | -0.0401 | 1.868 | 0.9105441129785639 | fail |
| BCHUSDT | 758 | -30.0509 | -0.0396 | 2/6 | 49.7085 | -0.0225 | 1.76 | 0.7466021836073689 | fail |
| DOTUSDT | 694 | 3.089 | 0.0045 | 3/6 | 38.7698 | 0.0023 | 1.927 | 0.47034047639306 | fail |
| **pooled** | 4389 | -58.069 | -0.0132 | 2/6 | 117.0086 (seq) | - | - | 0.710491521387591 | - |

Holm survivors (alpha 0.05): []

