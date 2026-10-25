# Stage-0 (synthetic leg) -- trend 2h -- fail

FAIL: B: pooled net_r 248.8357 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3); D40: net_r/trade 0.0513 beats the baseline's 0.0556 by -0.0043 < the 0.05 materiality bar; D40A: net_r/trade 0.0296 beats the baseline's 0.0556 by -0.026 < the 0.05 materiality bar; LONG: net_r/trade 0.0289 beats the baseline's 0.0556 by -0.0267 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 248.8357 > 0 with 5 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 757 | 20.8458 | 0.0275 | 4/6 | 21.8848 | 0.0168 | 1.637 | 0.2827793701857978 | pass |
| NEARUSDT | 728 | 19.0309 | 0.0261 | 3/6 | 24.5808 | 0.0147 | 1.773 | 0.2862691101677788 | fail |
| ATOMUSDT | 770 | 7.5747 | 0.0098 | 3/6 | 30.2056 | 0.0056 | 1.752 | 0.41406825395890334 | fail |
| FILUSDT | 662 | 109.2641 | 0.1651 | 6/6 | 18.7379 | 0.0932 | 1.772 | 0.0012159472595534447 | pass |
| TRXUSDT | 801 | 49.5991 | 0.0619 | 4/6 | 31.8177 | 0.0389 | 1.592 | 0.10478073541369232 | pass |
| ETCUSDT | 761 | 42.5248 | 0.0559 | 4/6 | 22.0934 | 0.0362 | 1.545 | 0.1313493290842495 | pass |
| **pooled** | 4479 | 248.8357 | 0.0556 | 5/6 | 68.3704 (seq) | - | - | 0.002651373739567096 | - |

Holm survivors (alpha 0.05): ['FILUSDT']

## arm `D40` (candidate) -- fail -- net_r/trade 0.0513 beats the baseline's 0.0556 by -0.0043 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 577 | 21.6162 | 0.0375 | 4/6 | 34.6446 | 0.0239 | 1.565 | 0.25180113425461526 | pass |
| NEARUSDT | 571 | 2.2449 | 0.0039 | 3/6 | 31.7149 | 0.0024 | 1.643 | 0.4696845893669546 | fail |
| ATOMUSDT | 591 | -5.8854 | -0.01 | 2/6 | 48.2251 | -0.0057 | 1.732 | 0.5762966270501181 | fail |
| FILUSDT | 502 | 91.1622 | 0.1816 | 5/6 | 17.2844 | 0.1125 | 1.615 | 0.0027344036189323757 | pass |
| TRXUSDT | 625 | 31.6114 | 0.0506 | 3/6 | 35.7413 | 0.0362 | 1.398 | 0.1818160167730793 | fail |
| ETCUSDT | 555 | 34.8321 | 0.0628 | 4/6 | 28.609 | 0.0421 | 1.491 | 0.14443885887369762 | pass |
| **pooled** | 3421 | 175.5794 | 0.0513 | 4/6 | 80.4905 (seq) | - | - | 0.012938717354199679 | - |

Holm survivors (alpha 0.05): ['FILUSDT']

## arm `D40A` (candidate) -- fail -- net_r/trade 0.0296 beats the baseline's 0.0556 by -0.026 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 490 | 23.8973 | 0.0488 | 4/6 | 22.653 | 0.0307 | 1.589 | 0.2207887616041624 | pass |
| NEARUSDT | 476 | -9.672 | -0.0203 | 3/6 | 44.1659 | -0.0128 | 1.584 | 0.6426096045360785 | fail |
| ATOMUSDT | 480 | -12.7772 | -0.0266 | 3/6 | 38.8984 | -0.015 | 1.772 | 0.699896875686448 | fail |
| FILUSDT | 429 | 44.5504 | 0.1038 | 4/6 | 20.6865 | 0.0654 | 1.589 | 0.06593822810651606 | pass |
| TRXUSDT | 514 | -5.5193 | -0.0107 | 2/6 | 41.2755 | -0.0079 | 1.367 | 0.5728092842819781 | fail |
| ETCUSDT | 444 | 43.255 | 0.0974 | 4/6 | 16.4345 | 0.0659 | 1.479 | 0.07744682413983034 | pass |
| **pooled** | 2833 | 83.731 | 0.0296 | 4/6 | 49.9944 (seq) | - | - | 0.11708186085206368 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade 0.0289 beats the baseline's 0.0556 by -0.0267 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 440 | -13.7782 | -0.0313 | 3/6 | 22.6785 | -0.0215 | 1.457 | 0.724770905164308 | fail |
| NEARUSDT | 440 | 16.0639 | 0.0365 | 5/6 | 19.2611 | 0.0244 | 1.494 | 0.2762393641416343 | pass |
| ATOMUSDT | 444 | -11.175 | -0.0252 | 3/6 | 35.549 | -0.0156 | 1.612 | 0.6736101626302657 | fail |
| FILUSDT | 413 | 22.8301 | 0.0553 | 3/6 | 23.1363 | 0.0413 | 1.34 | 0.18957801328560725 | fail |
| TRXUSDT | 493 | 71.7005 | 0.1454 | 5/6 | 15.7984 | 0.0944 | 1.54 | 0.014374857176759433 | pass |
| ETCUSDT | 444 | -8.2524 | -0.0186 | 2/6 | 37.3869 | -0.0137 | 1.359 | 0.6184551158878286 | fail |
| **pooled** | 2674 | 77.387 | 0.0289 | 4/6 | 62.0521 (seq) | - | - | 0.12093042666684378 | - |

Holm survivors (alpha 0.05): []

