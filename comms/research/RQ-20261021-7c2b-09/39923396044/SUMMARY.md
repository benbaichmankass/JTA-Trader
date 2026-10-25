# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 330 | 6.0905 | 0.0185 | 3/6 | 31.4095 | 0.0066 | 2.799 | 0.4457906516728828 | fail |
| DOGEUSDT | 324 | 18.2161 | 0.0562 | 3/6 | 30.625 | 0.0179 | 3.148 | 0.3223859713140667 | fail |
| LINKUSDT | 338 | -25.0648 | -0.0742 | 2/6 | 35.7196 | -0.0271 | 2.739 | 0.717327145975101 | fail |
| LTCUSDT | 315 | -70.8288 | -0.2249 | 2/6 | 78.4659 | -0.073 | 3.079 | 0.9707757152206318 | fail |
| BCHUSDT | 344 | -62.7512 | -0.1824 | 2/6 | 88.2939 | -0.0663 | 2.753 | 0.9312659360560078 | fail |
| DOTUSDT | 317 | -54.0805 | -0.1706 | 1/6 | 56.1963 | -0.0548 | 3.113 | 0.9219947580661618 | fail |
| **pooled** | 1968 | -188.4179 | -0.0957 | 2/6 | 202.2727 (seq) | - | - | 0.9697816325073914 | - |

Holm survivors (alpha 0.05): []

