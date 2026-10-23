# Stage-0 (synthetic leg) -- pullback 1h -- fail

FAIL: B: pooled net_r 257.0455 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); DI: net_r/trade 0.072 beats the baseline's 0.0519 by 0.0201 < the 0.05 materiality bar; DIA: net_r/trade 0.0667 beats the baseline's 0.0519 by 0.0148 < the 0.05 materiality bar; SL: net_r/trade 0.0187 beats the baseline's 0.0519 by -0.0332 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 257.0455 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 813 | 23.8683 | 0.0294 | 3/6 | 31.7942 | 0.0129 | 2.275 | 0.31857598531179115 | fail |
| ETHUSDT | 822 | 62.4921 | 0.076 | 4/6 | 27.4915 | 0.0341 | 2.233 | 0.1345461225568731 | pass |
| BTCUSDT | 797 | 73.7935 | 0.0926 | 5/6 | 21.9944 | 0.0398 | 2.324 | 0.09758241605529577 | pass |
| BNBUSDT | 861 | -43.4252 | -0.0504 | 3/6 | 79.7591 | -0.0237 | 2.124 | 0.8165461137262789 | fail |
| ADAUSDT | 813 | 132.3122 | 0.1627 | 6/6 | 25.6668 | 0.0707 | 2.301 | 0.017803343884467575 | pass |
| LINKUSDT | 845 | 8.0026 | 0.0095 | 3/6 | 54.9511 | 0.0044 | 2.148 | 0.43554392822115645 | fail |
| **pooled** | 4951 | 257.0455 | 0.0519 | 4/6 | 119.8978 (seq) | - | - | 0.026675830286274446 | - |

Holm survivors (alpha 0.05): []

## arm `DI` (candidate) -- fail -- net_r/trade 0.072 beats the baseline's 0.0519 by 0.0201 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 743 | 49.7737 | 0.067 | 5/6 | 34.3038 | 0.0296 | 2.267 | 0.16307573630140304 | pass |
| ETHUSDT | 754 | 86.8063 | 0.1151 | 6/6 | 28.1225 | 0.0522 | 2.204 | 0.047937112919528124 | pass |
| BTCUSDT | 732 | 92.3061 | 0.1261 | 5/6 | 21.0887 | 0.0542 | 2.328 | 0.051168690442195686 | pass |
| BNBUSDT | 783 | -37.2183 | -0.0475 | 3/6 | 65.6878 | -0.0227 | 2.093 | 0.7910072186208725 | fail |
| ADAUSDT | 746 | 122.7181 | 0.1645 | 5/6 | 20.7966 | 0.0722 | 2.277 | 0.02220895663224971 | pass |
| LINKUSDT | 765 | 11.2407 | 0.0147 | 3/6 | 43.8876 | 0.0069 | 2.143 | 0.40411307224783416 | fail |
| **pooled** | 4523 | 325.6287 | 0.072 | 5/6 | 83.8939 (seq) | - | - | 0.005558171477835704 | - |

Holm survivors (alpha 0.05): []

## arm `DIA` (candidate) -- fail -- net_r/trade 0.0667 beats the baseline's 0.0519 by 0.0148 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 658 | 42.2439 | 0.0642 | 5/6 | 35.3781 | 0.0276 | 2.325 | 0.18808293602081422 | pass |
| ETHUSDT | 682 | 52.2307 | 0.0766 | 3/6 | 26.8692 | 0.0347 | 2.207 | 0.15191911676034753 | fail |
| BTCUSDT | 651 | 76.0936 | 0.1169 | 5/6 | 17.3274 | 0.0493 | 2.369 | 0.07725439962904412 | pass |
| BNBUSDT | 686 | -9.0927 | -0.0133 | 3/6 | 49.865 | -0.0062 | 2.154 | 0.5794205166172446 | fail |
| ADAUSDT | 662 | 87.0392 | 0.1315 | 5/6 | 24.3413 | 0.0567 | 2.319 | 0.048381984722326465 | pass |
| LINKUSDT | 665 | 18.4178 | 0.0277 | 3/6 | 37.6696 | 0.0125 | 2.212 | 0.33240304134246307 | fail |
| **pooled** | 4004 | 266.9333 | 0.0667 | 4/6 | 79.1007 (seq) | - | - | 0.012813649204495684 | - |

Holm survivors (alpha 0.05): []

## arm `SL` (candidate) -- fail -- net_r/trade 0.0187 beats the baseline's 0.0519 by -0.0332 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XRPUSDT | 734 | -28.3184 | -0.0386 | 3/6 | 70.2003 | -0.0197 | 1.959 | 0.7199896821867393 | fail |
| ETHUSDT | 702 | 35.0764 | 0.05 | 4/6 | 32.7244 | 0.0245 | 2.042 | 0.25901308329265954 | pass |
| BTCUSDT | 699 | 38.848 | 0.0556 | 4/6 | 46.8686 | 0.0266 | 2.088 | 0.23350360003163645 | pass |
| BNBUSDT | 743 | -20.8597 | -0.0281 | 3/6 | 44.6708 | -0.0146 | 1.923 | 0.6782711091626866 | fail |
| ADAUSDT | 715 | 44.7782 | 0.0626 | 5/6 | 39.1076 | 0.0303 | 2.07 | 0.211599481403271 | pass |
| LINKUSDT | 723 | 11.2232 | 0.0155 | 4/6 | 47.2322 | 0.0079 | 1.959 | 0.4080590203848714 | pass |
| **pooled** | 4316 | 80.7481 | 0.0187 | 4/6 | 115.6923 (seq) | - | - | 0.2591143334354047 | - |

Holm survivors (alpha 0.05): []

