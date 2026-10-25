# Stage-0 (synthetic leg) -- trend 2h -- fail

FAIL: B: pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge; D40: net_r/trade 0.0415 beats the baseline's 0.0269 by 0.0146 < the 0.05 materiality bar; D55: net_r/trade 0.0698 beats the baseline's 0.0269 by 0.0429 < the 0.05 materiality bar; D40A: net_r/trade 0.0255 beats the baseline's 0.0269 by -0.0014 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 2 of 6 powered cells pass (< 3): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 759 | 10.5578 | 0.0139 | 3/6 | 21.9821 | 0.0083 | 1.673 | 0.37473861593331176 | fail |
| BNBUSDT | 793 | -22.8321 | -0.0288 | 1/6 | 47.0946 | -0.0185 | 1.558 | 0.7541714227285778 | fail |
| ETHUSDT | 735 | 40.5956 | 0.0552 | 4/6 | 20.23 | 0.0323 | 1.71 | 0.13197712841495707 | pass |
| XRPUSDT | 744 | 44.2028 | 0.0594 | 4/6 | 33.7452 | 0.0382 | 1.553 | 0.13943046794298664 | pass |
| LINKUSDT | 763 | 28.969 | 0.038 | 3/6 | 31.5513 | 0.0211 | 1.8 | 0.19558698281424847 | fail |
| AAVEUSDT | 726 | 19.8877 | 0.0274 | 2/6 | 27.446 | 0.0157 | 1.743 | 0.2920729862336281 | fail |
| **pooled** | 4520 | 121.3779 | 0.0269 | 5/6 | 93.314 (seq) | - | - | 0.08237566018609938 | - |

Holm survivors (alpha 0.05): []

## arm `D40` (candidate) -- fail -- net_r/trade 0.0415 beats the baseline's 0.0269 by 0.0146 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 566 | 24.88 | 0.044 | 5/6 | 17.8388 | 0.027 | 1.63 | 0.19104942316883605 | pass |
| BNBUSDT | 601 | -11.5591 | -0.0192 | 2/6 | 40.4437 | -0.0133 | 1.443 | 0.6566036103987223 | fail |
| ETHUSDT | 570 | 29.3281 | 0.0515 | 5/6 | 21.3776 | 0.031 | 1.662 | 0.17917898232479812 | pass |
| XRPUSDT | 530 | 78.2835 | 0.1477 | 5/6 | 14.3296 | 0.1007 | 1.467 | 0.014939337294159182 | pass |
| LINKUSDT | 613 | -7.5062 | -0.0122 | 3/6 | 40.4654 | -0.0076 | 1.613 | 0.5980860577030708 | fail |
| AAVEUSDT | 554 | 28.9933 | 0.0523 | 4/6 | 14.6534 | 0.0305 | 1.717 | 0.19641655598485008 | pass |
| **pooled** | 3434 | 142.4181 | 0.0415 | 5/6 | 76.0757 (seq) | - | - | 0.033067607326408066 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade 0.0698 beats the baseline's 0.0269 by 0.0429 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 310 | 91.6687 | 0.2957 | 5/6 | 25.2722 | 0.0712 | 4.155 | 0.009950491654741407 | pass |
| BNBUSDT | 361 | 2.1623 | 0.006 | 3/6 | 37.0404 | 0.0018 | 3.33 | 0.4776074868027177 | fail |
| ETHUSDT | 328 | 66.0009 | 0.2012 | 6/6 | 12.9835 | 0.0503 | 3.997 | 0.04802132185235253 | pass |
| XRPUSDT | 344 | 19.1507 | 0.0557 | 4/6 | 34.1774 | 0.0188 | 2.966 | 0.3172208334451781 | pass |
| LINKUSDT | 368 | -32.0702 | -0.0871 | 2/6 | 46.4379 | -0.0246 | 3.542 | 0.8291521393729784 | fail |
| AAVEUSDT | 328 | -4.5259 | -0.0138 | 3/6 | 32.9466 | -0.0034 | 4.048 | 0.5488768599943711 | fail |
| **pooled** | 2039 | 142.3846 | 0.0698 | 4/6 | 105.759 (seq) | - | - | 0.06352359515825451 | - |

Holm survivors (alpha 0.05): []

## arm `D40A` (candidate) -- fail -- net_r/trade 0.0255 beats the baseline's 0.0269 by -0.0014 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SOLUSDT | 482 | 7.4564 | 0.0155 | 3/6 | 14.6143 | 0.0096 | 1.612 | 0.38404381461895165 | fail |
| BNBUSDT | 490 | -32.4697 | -0.0663 | 1/6 | 44.6558 | -0.0464 | 1.427 | 0.9005354942461593 | fail |
| ETHUSDT | 470 | 23.3282 | 0.0496 | 3/6 | 19.3424 | 0.0294 | 1.687 | 0.2050239043876027 | fail |
| XRPUSDT | 446 | 66.4892 | 0.1491 | 4/6 | 12.4374 | 0.0986 | 1.512 | 0.025509337667017445 | pass |
| LINKUSDT | 519 | -26.4901 | -0.051 | 2/6 | 43.2182 | -0.0321 | 1.589 | 0.8296683352308953 | fail |
| AAVEUSDT | 434 | 34.0012 | 0.0783 | 5/6 | 17.6076 | 0.0451 | 1.738 | 0.1359944391204932 | pass |
| **pooled** | 2841 | 72.3146 | 0.0255 | 5/6 | 82.5265 (seq) | - | - | 0.15241579904737562 | - |

Holm survivors (alpha 0.05): []

