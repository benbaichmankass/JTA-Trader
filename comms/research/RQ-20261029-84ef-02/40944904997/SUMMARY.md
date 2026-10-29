# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r 127.8053 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3); LONG: net_r/trade 0.1332 beats the baseline's 0.0871 by 0.0461 < the 0.05 materiality bar. Thresholds: n_floor 30, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 127.8053 > 0 with 4 folds positive and 4 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 237 | 34.1874 | 0.1443 | 3/6 | 11.9398 | 0.0209 | 6.89 | 0.14447424448194401 | fail |
| ETHUSDT | 242 | 26.8694 | 0.111 | 4/6 | 18.4008 | 0.0156 | 7.119 | 0.1933505247541757 | pass |
| SOLUSDT | 233 | 33.2644 | 0.1428 | 5/6 | 15.2941 | 0.0203 | 7.031 | 0.13705259750715465 | pass |
| XRPUSDT | 255 | 22.7889 | 0.0894 | 4/6 | 28.3681 | 0.0155 | 5.78 | 0.2283309598856132 | pass |
| ADAUSDT | 260 | -5.2538 | -0.0202 | 3/6 | 17.4595 | -0.0032 | 6.29 | 0.5767330654591422 | fail |
| AVAXUSDT | 241 | 15.9489 | 0.0662 | 5/6 | 23.4717 | 0.01 | 6.588 | 0.2683617358245032 | pass |
| **pooled** | 1468 | 127.8053 | 0.0871 | 4/6 | 70.119 (seq) | - | - | 0.03879258735979092 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade 0.1332 beats the baseline's 0.0871 by 0.0461 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 163 | 45.5266 | 0.2793 | 5/6 | 14.211 | 0.0402 | 6.95 | 0.057482123506161165 | pass |
| ETHUSDT | 172 | 36.1375 | 0.2101 | 4/6 | 17.0651 | 0.031 | 6.779 | 0.10769070136699244 | pass |
| SOLUSDT | 164 | 35.5913 | 0.217 | 4/6 | 14.2851 | 0.0328 | 6.612 | 0.11005914472876455 | pass |
| XRPUSDT | 179 | 20.0287 | 0.1119 | 3/6 | 26.4857 | 0.0238 | 4.692 | 0.23573947229567233 | fail |
| ADAUSDT | 197 | -1.9764 | -0.01 | 2/6 | 24.45 | -0.0023 | 4.366 | 0.5289691177884102 | fail |
| AVAXUSDT | 180 | 5.1657 | 0.0287 | 3/6 | 26.093 | 0.0056 | 5.095 | 0.4118661645184418 | fail |
| **pooled** | 1055 | 140.4733 | 0.1332 | 5/6 | 72.0597 (seq) | - | - | 0.018665947056677033 | - |

Holm survivors (alpha 0.05): []

