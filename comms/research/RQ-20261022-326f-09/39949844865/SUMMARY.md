# Stage-0 (synthetic leg) -- fade 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 2204 | -403.268 | -0.183 | 0/6 | 131.1225 | None | None | 0.9999996130292697 | fail |
| DOGEUSDT | 2035 | -368.6102 | -0.1811 | 0/6 | 219.5944 | None | None | 0.9999995149898532 | fail |
| LINKUSDT | 2382 | -398.0396 | -0.1671 | 0/6 | 257.3066 | None | None | 0.9999985856257692 | fail |
| LTCUSDT | 2246 | -138.71 | -0.0618 | 1/6 | 70.026 | None | None | 0.946852753520653 | fail |
| BCHUSDT | 2177 | -294.7024 | -0.1354 | 1/6 | 144.012 | None | None | 0.9998554765132825 | fail |
| DOTUSDT | 2244 | -337.811 | -0.1505 | 1/6 | 166.0527 | None | None | 0.9999717567058832 | fail |
| **pooled** | 13288 | -1941.139 | -0.1461 | 0/6 | 1961.7947 (seq) | - | - | 1.0 | - |

Holm survivors (alpha 0.05): []

