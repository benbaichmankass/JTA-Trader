# Stage-0 (synthetic leg) -- fade 1h -- fail

FAIL: FAR: pooled net_r <= 0 or folds short; SWEEP: net_r/trade -0.1447 beats the baseline's -0.1526 by 0.0079 < the 0.05 materiality bar; SWEEP_TP1: net_r/trade -0.1257 beats the baseline's -0.1526 by 0.0269 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline FAR with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `FAR` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 1983 | -322.1794 | -0.1625 | 0/6 | 122.0998 | None | None | 0.9999873195397686 | fail |
| ETHUSDT | 1943 | -308.172 | -0.1586 | 0/6 | 108.4652 | None | None | 0.9999858290510605 | fail |
| SOLUSDT | 2076 | -303.5229 | -0.1462 | 0/6 | 145.497 | None | None | 0.9999098508344442 | fail |
| XRPUSDT | 1875 | -244.7284 | -0.1305 | 0/6 | 63.8067 | None | None | 0.9994454195630535 | fail |
| ADAUSDT | 1975 | -260.3315 | -0.1318 | 1/6 | 162.6835 | None | None | 0.9995374164109028 | fail |
| AVAXUSDT | 2085 | -383.1005 | -0.1837 | 1/6 | 282.4532 | None | None | 0.9999991403675932 | fail |
| **pooled** | 11937 | -1822.0365 | -0.1526 | 0/6 | 1827.5183 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

## arm `SWEEP` (candidate) -- fail -- net_r/trade -0.1447 beats the baseline's -0.1526 by 0.0079 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 1499 | -206.9729 | -0.1381 | 0/6 | 60.5676 | None | None | 0.9995899705200686 | fail |
| ETHUSDT | 1452 | -196.7413 | -0.1355 | 1/6 | 104.9252 | None | None | 0.9993626753528119 | fail |
| SOLUSDT | 1446 | -236.9584 | -0.1639 | 0/6 | 158.4413 | None | None | 0.9999574537462375 | fail |
| XRPUSDT | 1331 | -105.4745 | -0.0792 | 1/6 | 37.163 | None | None | 0.9643341017231646 | fail |
| ADAUSDT | 1354 | -313.0062 | -0.2312 | 0/6 | 215.699 | None | None | 0.9999999747046374 | fail |
| AVAXUSDT | 1409 | -169.2044 | -0.1201 | 1/6 | 119.642 | None | None | 0.9954596315609621 | fail |
| **pooled** | 8491 | -1228.3547 | -0.1447 | 0/6 | 1237.4527 (seq) | - | - | 0.9999999999999999 | - |

Holm survivors (alpha 0.05): []

## arm `SWEEP_TP1` (candidate) -- fail -- net_r/trade -0.1257 beats the baseline's -0.1526 by 0.0269 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 1822 | -260.1145 | -0.1428 | 0/6 | 50.7025 | None | None | 0.9999999995152071 | fail |
| ETHUSDT | 1820 | -224.4298 | -0.1233 | 0/6 | 70.3659 | None | None | 0.9999999317370191 | fail |
| SOLUSDT | 1777 | -206.0211 | -0.1159 | 0/6 | 91.6991 | None | None | 0.99999954886201 | fail |
| XRPUSDT | 1642 | -197.1285 | -0.1201 | 0/6 | 57.4839 | None | None | 0.9999995397542986 | fail |
| ADAUSDT | 1674 | -219.0042 | -0.1308 | 0/6 | 108.2546 | None | None | 0.9999999585850916 | fail |
| AVAXUSDT | 1752 | -211.1602 | -0.1205 | 0/6 | 106.541 | None | None | 0.9999997894717401 | fail |
| **pooled** | 10487 | -1317.8602 | -0.1257 | 0/6 | 1323.3978 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

