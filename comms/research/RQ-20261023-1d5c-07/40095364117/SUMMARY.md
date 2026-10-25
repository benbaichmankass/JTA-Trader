# Stage-0 (synthetic leg) -- pullback 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; DI: net_r/trade -0.0013 beats the baseline's -0.0019 by 0.0006 < the 0.05 materiality bar; LONG: net_r/trade -0.0326 beats the baseline's -0.0019 by -0.0307 < the 0.05 materiality bar; BE1: net_r/trade 0.0188 beats the baseline's -0.0019 by 0.0207 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 411 | 38.5985 | 0.0939 | 4/6 | 27.6563 | 0.021 | 4.465 | 0.14469657267242775 | pass |
| LINKUSDT | 433 | -6.6079 | -0.0153 | 2/6 | 41.0708 | -0.0037 | 4.108 | 0.5736876490470793 | fail |
| DOGEUSDT | 383 | 32.1317 | 0.0839 | 4/6 | 34.4197 | 0.0175 | 4.797 | 0.19158796339858886 | pass |
| LTCUSDT | 429 | -83.0585 | -0.1936 | 2/6 | 117.8476 | -0.0469 | 4.131 | 0.9966877148508616 | fail |
| BCHUSDT | 390 | 20.4256 | 0.0524 | 3/6 | 28.9263 | 0.0112 | 4.675 | 0.29306435745935844 | fail |
| DOTUSDT | 383 | -6.0605 | -0.0158 | 3/6 | 20.1729 | -0.0035 | 4.559 | 0.5677890126797343 | fail |
| **pooled** | 2429 | -4.5707 | -0.0019 | 2/6 | 166.8446 (seq) | - | - | 0.5209870271897323 | - |

Holm survivors (alpha 0.05): []

## arm `DI` (candidate) -- fail -- net_r/trade -0.0013 beats the baseline's -0.0019 by 0.0006 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 379 | 41.8816 | 0.1105 | 4/6 | 26.87 | 0.0256 | 4.313 | 0.12575190289410576 | pass |
| LINKUSDT | 392 | -0.6063 | -0.0015 | 3/6 | 28.2163 | -0.0004 | 3.994 | 0.5070511095064489 | fail |
| DOGEUSDT | 366 | 31.5578 | 0.0862 | 3/6 | 32.8373 | 0.0188 | 4.583 | 0.19015933496078818 | fail |
| LTCUSDT | 387 | -94.1245 | -0.2432 | 1/6 | 114.1465 | -0.0585 | 4.155 | 0.9996545853344057 | fail |
| BCHUSDT | 359 | 5.1157 | 0.0142 | 3/6 | 35.9284 | 0.0031 | 4.645 | 0.441125649064148 | fail |
| DOTUSDT | 344 | 13.2886 | 0.0386 | 4/6 | 16.7535 | 0.0082 | 4.705 | 0.35360257660640415 | pass |
| **pooled** | 2227 | -2.8859 | -0.0013 | 3/6 | 136.0156 (seq) | - | - | 0.513746321740486 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade -0.0326 beats the baseline's -0.0019 by -0.0307 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 293 | 30.2618 | 0.1033 | 3/6 | 23.3582 | 0.0258 | 4.01 | 0.15802729432964702 | fail |
| LINKUSDT | 284 | 7.3554 | 0.0259 | 3/6 | 29.7635 | 0.0069 | 3.742 | 0.3945903520324322 | fail |
| DOGEUSDT | 289 | -14.5431 | -0.0503 | 3/6 | 42.1864 | -0.0131 | 3.849 | 0.6930046518896044 | fail |
| LTCUSDT | 298 | -32.2939 | -0.1084 | 1/6 | 53.2898 | -0.0294 | 3.691 | 0.882816392455423 | fail |
| BCHUSDT | 299 | -20.9235 | -0.07 | 2/6 | 42.2346 | -0.0193 | 3.618 | 0.7543233776730549 | fail |
| DOTUSDT | 266 | -26.2845 | -0.0988 | 3/6 | 41.5997 | -0.0265 | 3.731 | 0.8243925339357552 | fail |
| **pooled** | 1729 | -56.4286 | -0.0326 | 3/6 | 194.6614 (seq) | - | - | 0.7889856068603172 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0188 beats the baseline's -0.0019 by 0.0207 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 459 | 60.2538 | 0.1313 | 4/6 | 25.7232 | 0.0338 | 3.886 | 0.04965699632069259 | pass |
| LINKUSDT | 496 | -10.7417 | -0.0217 | 2/6 | 41.7693 | -0.0063 | 3.42 | 0.6231265412457455 | fail |
| DOGEUSDT | 458 | 23.3297 | 0.0509 | 4/6 | 44.3987 | 0.0132 | 3.864 | 0.2603689164581574 | pass |
| LTCUSDT | 488 | -67.2264 | -0.1378 | 1/6 | 103.5079 | -0.0394 | 3.496 | 0.9867819874430774 | fail |
| BCHUSDT | 436 | 27.1584 | 0.0623 | 4/6 | 22.5159 | 0.0155 | 4.026 | 0.22033525589941594 | pass |
| DOTUSDT | 444 | 19.5848 | 0.0441 | 4/6 | 19.2026 | 0.0117 | 3.772 | 0.2879024152773677 | pass |
| **pooled** | 2781 | 52.36 | 0.0188 | 3/6 | 102.2592 (seq) | - | - | 0.2686250491303539 | - |

Holm survivors (alpha 0.05): []

