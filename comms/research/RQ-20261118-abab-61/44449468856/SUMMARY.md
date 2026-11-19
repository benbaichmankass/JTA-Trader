# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; VW100: net_r/trade -0.0046 beats the baseline's -0.0028 by -0.0018 < the 0.13 materiality bar. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 279 | 39.57 | 0.1418 | 4/6 | 22.6404 | 0.0246 | 5.77 | 0.12373938273633434 | pass |
| DOGEUSDT | 271 | 1.4556 | 0.0054 | 3/6 | 43.0946 | 0.0009 | 5.832 | 0.4808106458958623 | fail |
| LINKUSDT | 289 | 3.7012 | 0.0128 | 4/6 | 38.7127 | 0.0024 | 5.25 | 0.4537428491589169 | pass |
| LTCUSDT | 287 | -35.6075 | -0.1241 | 2/6 | 61.0912 | -0.0238 | 5.208 | 0.8838028906471114 | fail |
| BCHUSDT | 282 | -2.2998 | -0.0082 | 4/6 | 36.7923 | -0.0014 | 5.643 | 0.5287525541339184 | fail |
| DOTUSDT | 276 | -11.6172 | -0.0421 | 2/6 | 34.1518 | -0.0077 | 5.436 | 0.6414439069055359 | fail |
| **pooled** | 1684 | -4.7969 | -0.0028 | 3/6 | 158.4322 (seq) | - | - | 0.5246642887763427 | - |

Holm survivors (alpha 0.05): []

## arm `VW100` (candidate) -- fail -- net_r/trade -0.0046 beats the baseline's -0.0028 by -0.0018 < the 0.13 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 263 | 41.7938 | 0.1589 | 4/6 | 21.5727 | 0.0272 | 5.841 | 0.10920891731586913 | pass |
| DOGEUSDT | 258 | -4.6515 | -0.018 | 3/6 | 50.4506 | -0.003 | 6.037 | 0.5643800827231858 | fail |
| LINKUSDT | 270 | 3.8063 | 0.0141 | 4/6 | 34.0818 | 0.0026 | 5.388 | 0.4521061932300664 | pass |
| LTCUSDT | 267 | -39.2797 | -0.1471 | 2/6 | 64.7367 | -0.0268 | 5.484 | 0.9129000881747631 | fail |
| BCHUSDT | 267 | 6.518 | 0.0244 | 4/6 | 34.9535 | 0.0042 | 5.747 | 0.41829649473413966 | pass |
| DOTUSDT | 256 | -15.4633 | -0.0604 | 2/6 | 31.8374 | -0.0106 | 5.678 | 0.6964464921662075 | fail |
| **pooled** | 1581 | -7.2748 | -0.0046 | 3/6 | 166.3258 (seq) | - | - | 0.5383962867208631 | - |

Holm survivors (alpha 0.05): []

