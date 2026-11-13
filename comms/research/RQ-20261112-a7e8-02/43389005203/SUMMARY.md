# Stage-0 (synthetic leg) -- fade 1d -- fail

FAIL: B: pooled net_r <= 0 or folds short; D5: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 102 | -28.5722 | -0.2801 | 1/6 | 27.6609 | None | None | 0.9168540536383327 | fail |
| QQQ | 92 | -28.741 | -0.3124 | 1/6 | 32.9844 | None | None | 0.934026419648804 | fail |
| IWM | 79 | -2.4173 | -0.0306 | 2/6 | 14.3559 | None | None | 0.5484492810374084 | fail |
| DIA | 89 | -1.2892 | -0.0145 | 3/6 | 16.6804 | None | None | 0.5227793651756828 | fail |
| TLT | 68 | -9.1822 | -0.135 | 1/6 | 12.4614 | None | None | 0.70816084185587 | fail |
| IEF | 76 | 3.5363 | 0.0465 | 3/6 | 11.0 | None | None | 0.43298619087452805 | fail |
| GLD | 59 | 9.1229 | 0.1546 | 2/6 | 14.3009 | None | None | 0.3273069382467494 | fail |
| SLV | 64 | 4.6164 | 0.0721 | 2/6 | 17.3776 | None | None | 0.4039167347603735 | fail |
| GDX | 86 | 3.3298 | 0.0387 | 2/6 | 21.2966 | None | None | 0.43865368334725185 | fail |
| **pooled** | 715 | -49.5963 | -0.0694 | 2/6 | 88.5044 (seq) | - | - | 0.7957574716271887 | - |

Holm survivors (alpha 0.05): []

## arm `D5` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 158 | 1.7168 | 0.0109 | 3/6 | 13.543 | None | None | 0.46722597337659916 | fail |
| QQQ | 151 | -12.7569 | -0.0845 | 1/6 | 16.1293 | None | None | 0.7516662553682998 | fail |
| IWM | 136 | -2.9694 | -0.0218 | 4/6 | 18.2317 | None | None | 0.56808250792283 | fail |
| DIA | 145 | 17.9761 | 0.124 | 5/6 | 8.19 | None | None | 0.1714685234486404 | pass |
| TLT | 139 | -15.7173 | -0.1131 | 1/6 | 16.7877 | None | None | 0.830756664559889 | fail |
| IEF | 135 | -16.6186 | -0.1231 | 3/6 | 15.9039 | None | None | 0.8206359622533959 | fail |
| GLD | 119 | -12.8544 | -0.108 | 3/6 | 23.0015 | None | None | 0.764712742118148 | fail |
| SLV | 139 | -21.0585 | -0.1515 | 1/6 | 26.67 | None | None | 0.8801311387643219 | fail |
| GDX | 152 | -17.599 | -0.1158 | 2/6 | 39.4751 | None | None | 0.8212859753975511 | fail |
| **pooled** | 1274 | -79.8803 | -0.0627 | 1/6 | 95.5004 (seq) | - | - | 0.9268344442380492 | - |

Holm survivors (alpha 0.05): []

