# Stage-0 (synthetic leg) -- pullback 1d -- fail

FAIL: B: pooled net_r 58.9542 > 0 with 5 folds positive and 3 of 6 powered cells pass (breadth floor 3); LONG: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 58.9542 > 0 with 5 folds positive and 3 of 6 powered cells pass (breadth floor 3)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 30 | 16.3397 | 0.5447 | 4/6 | 8.0139 | 0.0087 | 62.333 | 0.19787886960994688 | pass |
| DOGEUSDT | 26 | 38.4818 | 1.4801 | 3/6 | 5.5269 | 0.0201 | 73.577 | 0.04459874683516021 | fail |
| LINKUSDT | 30 | 11.3956 | 0.3799 | 4/6 | 6.4383 | 0.0062 | 61.7 | 0.16912221611813255 | pass |
| LTCUSDT | 36 | -8.8529 | -0.2459 | 2/6 | 17.0412 | -0.0051 | 48.25 | 0.8780122344373483 | fail |
| BCHUSDT | 36 | -2.3873 | -0.0663 | 1/6 | 8.9845 | -0.0013 | 50.306 | 0.6209195245255758 | fail |
| DOTUSDT | 25 | 3.9778 | 0.1591 | 4/6 | 3.1893 | 0.0022 | 72.64 | 0.27991676330229187 | pass |
| **pooled** | 183 | 58.9542 | 0.3222 | 5/6 | 25.4838 (seq) | - | - | 0.0419579386640844 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 30 | 15.8697 | 0.529 | 3/6 | 5.9782 | 0.014 | 37.867 | 0.20307001065580327 | fail |
| DOGEUSDT | 23 | 49.6485 | 2.1586 | 4/6 | 4.0756 | 0.0587 | 36.783 | 0.022265702555803547 | pass |
| LINKUSDT | 25 | 12.4958 | 0.4998 | 4/6 | 6.3671 | 0.0126 | 39.64 | 0.14217215233096536 | pass |
| LTCUSDT | 30 | -1.2217 | -0.0407 | 2/6 | 10.4914 | -0.001 | 40.3 | 0.5577463364959327 | fail |
| BCHUSDT | 25 | 1.1437 | 0.0457 | 3/6 | 5.5485 | 0.0014 | 32.16 | 0.43402963789385063 | fail |
| DOTUSDT | 22 | -9.7222 | -0.4419 | 1/6 | 13.4409 | -0.0132 | 33.5 | 0.9780900078672496 | fail |
| **pooled** | 155 | 68.2134 | 0.4401 | 3/6 | 22.6614 (seq) | - | - | 0.02643083425939172 | - |

Holm survivors (alpha 0.05): []

