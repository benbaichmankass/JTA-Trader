# Stage-0 (synthetic leg) -- fade 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; M15: net_r/trade -0.1735 beats the baseline's -0.1051 by -0.0684 < the 0.05 materiality bar; M25: net_r/trade -0.1527 beats the baseline's -0.1051 by -0.0476 < the 0.05 materiality bar; TRL: net_r/trade -0.1135 beats the baseline's -0.1051 by -0.0084 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 1088 | -96.8857 | -0.089 | 2/6 | 78.0722 | None | None | 0.9423596844173441 | fail |
| NEARUSDT | 1137 | -77.5542 | -0.0682 | 1/6 | 59.0229 | None | None | 0.8958431059590155 | fail |
| ATOMUSDT | 1201 | -126.7487 | -0.1055 | 1/6 | 94.9856 | None | None | 0.9797751768029825 | fail |
| FILUSDT | 950 | -34.1465 | -0.0359 | 2/6 | 36.2807 | None | None | 0.7327739056468916 | fail |
| TRXUSDT | 1171 | -270.8706 | -0.2313 | 0/6 | 144.3316 | None | None | 0.9999929421967743 | fail |
| ETCUSDT | 1086 | -90.7485 | -0.0836 | 1/6 | 65.3648 | None | None | 0.9408659736969609 | fail |
| **pooled** | 6633 | -696.9539 | -0.1051 | 0/6 | 743.0378 (seq) | - | - | 0.9999988924942412 | - |

Holm survivors (alpha 0.05): []

## arm `M15` (candidate) -- fail -- net_r/trade -0.1735 beats the baseline's -0.1051 by -0.0684 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 181 | -60.7275 | -0.3355 | 0/6 | 45.0169 | None | None | 0.9999891354381347 | fail |
| NEARUSDT | 227 | -26.5886 | -0.1171 | 1/6 | 22.01 | None | None | 0.9371539007677434 | fail |
| ATOMUSDT | 192 | -29.2822 | -0.1525 | 1/6 | 31.5853 | None | None | 0.9658080634110746 | fail |
| FILUSDT | 182 | -37.3685 | -0.2053 | 0/6 | 30.6773 | None | None | 0.99394722826713 | fail |
| TRXUSDT | 248 | -34.4681 | -0.139 | 3/6 | 32.7589 | None | None | 0.9711215551467511 | fail |
| ETCUSDT | 250 | -33.6477 | -0.1346 | 1/6 | 25.578 | None | None | 0.9679808723306111 | fail |
| **pooled** | 1280 | -222.0823 | -0.1735 | 0/6 | 232.5057 (seq) | - | - | 0.9999999792361298 | - |

Holm survivors (alpha 0.05): []

## arm `M25` (candidate) -- fail -- net_r/trade -0.1527 beats the baseline's -0.1051 by -0.0476 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 817 | -202.782 | -0.2482 | 0/6 | 146.2503 | None | None | 0.9999999991306866 | fail |
| NEARUSDT | 915 | -70.3542 | -0.0769 | 1/6 | 60.3165 | None | None | 0.9709509232958385 | fail |
| ATOMUSDT | 946 | -121.1572 | -0.1281 | 0/6 | 79.1522 | None | None | 0.9991733006866993 | fail |
| FILUSDT | 744 | -92.9937 | -0.125 | 1/6 | 48.5781 | None | None | 0.9978958451071729 | fail |
| TRXUSDT | 990 | -225.9889 | -0.2283 | 0/6 | 110.4877 | None | None | 0.9999999973335787 | fail |
| ETCUSDT | 871 | -93.1726 | -0.107 | 1/6 | 58.4992 | None | None | 0.9964772360085954 | fail |
| **pooled** | 5283 | -806.4507 | -0.1527 | 0/6 | 808.7117 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- net_r/trade -0.1135 beats the baseline's -0.1051 by -0.0084 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 370 | -65.4072 | -0.1768 | 2/6 | 49.7057 | None | None | 0.9539040921984148 | fail |
| NEARUSDT | 445 | 7.764 | 0.0174 | 2/6 | 48.4464 | None | None | 0.4389927400283876 | fail |
| ATOMUSDT | 458 | -64.2526 | -0.1403 | 1/6 | 47.1788 | None | None | 0.9447659669141986 | fail |
| FILUSDT | 342 | -8.6737 | -0.0254 | 1/6 | 35.8379 | None | None | 0.5906914998697357 | fail |
| TRXUSDT | 481 | -131.2615 | -0.2729 | 0/6 | 52.2679 | None | None | 0.9989714235249054 | fail |
| ETCUSDT | 421 | -23.9646 | -0.0569 | 3/6 | 37.7925 | None | None | 0.718939910317413 | fail |
| **pooled** | 2517 | -285.7974 | -0.1135 | 1/6 | 292.3544 (seq) | - | - | 0.9972236645161195 | - |

Holm survivors (alpha 0.05): []

