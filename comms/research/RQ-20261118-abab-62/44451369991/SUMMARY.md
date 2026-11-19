# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; TV90: net_r/trade 0.0027 beats the baseline's -0.0028 by 0.0055 < the 0.13 materiality bar. Thresholds: n_floor 39, pooled_n_floor 1500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.13 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

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

## arm `TV90` (candidate) -- fail -- net_r/trade 0.0027 beats the baseline's -0.0028 by 0.0055 < the 0.13 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 365 | 51.8514 | 0.1421 | 4/6 | 22.6443 | 0.0376 | 3.775 | 0.03849270799598288 | pass |
| DOGEUSDT | 351 | 7.6482 | 0.0218 | 4/6 | 38.2513 | 0.0055 | 3.932 | 0.3956139400869337 | pass |
| LINKUSDT | 368 | 11.9191 | 0.0324 | 3/6 | 29.1811 | 0.0094 | 3.428 | 0.3322522280028689 | fail |
| LTCUSDT | 366 | -25.0562 | -0.0685 | 3/6 | 53.635 | -0.0194 | 3.536 | 0.8414816557093193 | fail |
| BCHUSDT | 357 | -32.3697 | -0.0907 | 3/6 | 62.7124 | -0.0233 | 3.884 | 0.8929663182415666 | fail |
| DOTUSDT | 341 | -8.1178 | -0.0238 | 3/6 | 21.6046 | -0.0064 | 3.741 | 0.6142886504536454 | fail |
| **pooled** | 2148 | 5.8756 | 0.0027 | 3/6 | 139.7315 (seq) | - | - | 0.4652051313166306 | - |

Holm survivors (alpha 0.05): []

