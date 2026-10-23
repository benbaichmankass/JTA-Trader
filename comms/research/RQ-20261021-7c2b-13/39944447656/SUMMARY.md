# Stage-0 (synthetic leg) -- trend 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 445 | -8.9456 | -0.0201 | 2/6 | 36.3691 | -0.0236 | 0.852 | 0.630666451971312 | fail |
| DOGEUSDT | 410 | -13.3049 | -0.0325 | 3/6 | 59.6281 | -0.0496 | 0.654 | 0.6735005887258423 | fail |
| LINKUSDT | 393 | 44.0473 | 0.1121 | 4/6 | 16.536 | 0.1131 | 0.991 | 0.0554159732388243 | pass |
| LTCUSDT | 393 | -30.6254 | -0.0779 | 1/6 | 40.796 | -0.0844 | 0.923 | 0.8866126615619097 | fail |
| BCHUSDT | 406 | 3.4811 | 0.0086 | 2/6 | 19.0352 | 0.0099 | 0.865 | 0.4519296694446418 | fail |
| DOTUSDT | 383 | -2.7339 | -0.0071 | 3/6 | 52.8542 | -0.0078 | 0.92 | 0.5364962247178144 | fail |
| **pooled** | 2430 | -8.0807 | -0.0033 | 3/6 | 135.006 (seq) | - | - | 0.5468632690670738 | - |

Holm survivors (alpha 0.05): []

