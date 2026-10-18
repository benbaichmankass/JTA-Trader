# Stage-0 (synthetic leg) -- pullback 1d -- fail

FAIL: B: pooled net_r <= 0 or folds short; F0618: pooled net_r <= 0 or folds short. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 33 | 4.5061 | 0.1365 | 3/6 | 11.0748 | 0.0023 | 58.515 | 0.34477718769845617 | fail |
| ETHUSDT | 37 | -7.74 | -0.2092 | 2/6 | 17.6092 | -0.0045 | 46.216 | 0.7661057086820959 | fail |
| SOLUSDT | 33 | 6.9652 | 0.2111 | 3/6 | 10.0403 | 0.0042 | 50.0 | 0.2716751122005465 | fail |
| XRPUSDT | 29 | -11.732 | -0.4046 | 1/6 | 11.732 | -0.0061 | 65.828 | 0.9441280561143294 | fail |
| ADAUSDT | 37 | -1.8086 | -0.0489 | 3/6 | 11.6747 | -0.001 | 48.865 | 0.5764090761432032 | fail |
| AVAXUSDT | 26 | 12.775 | 0.4913 | 5/6 | 5.185 | 0.0082 | 60.269 | 0.13493411659662158 | pass |
| **pooled** | 195 | 2.9654 | 0.0152 | 3/6 | 48.0833 (seq) | - | - | 0.4530025281714801 | - |

Holm survivors (alpha 0.05): []

## arm `F0618` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 34 | 5.5456 | 0.1631 | 4/6 | 6.2554 | 0.0027 | 59.853 | 0.30719749632517196 | pass |
| ETHUSDT | 37 | -4.942 | -0.1336 | 2/6 | 15.6185 | -0.0025 | 54.378 | 0.6805899549671893 | fail |
| SOLUSDT | 34 | 8.1956 | 0.241 | 3/6 | 5.7638 | 0.0047 | 51.029 | 0.25143076506908024 | fail |
| XRPUSDT | 32 | -12.604 | -0.3939 | 2/6 | 15.8445 | -0.006 | 65.281 | 0.936137841760139 | fail |
| ADAUSDT | 37 | 1.6796 | 0.0454 | 3/6 | 11.5657 | 0.0008 | 55.216 | 0.42793398480283973 | fail |
| AVAXUSDT | 29 | 9.759 | 0.3365 | 3/6 | 5.4468 | 0.0055 | 61.207 | 0.20002446034873594 | fail |
| **pooled** | 203 | 7.6347 | 0.0376 | 2/6 | 44.2879 (seq) | - | - | 0.38236347980638297 | - |

Holm survivors (alpha 0.05): []

