# Stage-0 (synthetic leg) -- squeeze 1h -- fail

FAIL: T48: pooled net_r <= 0 or folds short; T6: net_r/trade -0.0082 beats the baseline's -0.0034 by -0.0048 < the 0.0 materiality bar; T12: pooled net_r <= 0 or folds short; T24: net_r/trade -0.0043 beats the baseline's -0.0034 by -0.0009 < the 0.0 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.67 over >= 2 powered cells, holm alpha 0.05, baseline T48 with materiality 0.0 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `T48` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DOGEUSDT | 546 | 57.2467 | 0.1048 | 5/6 | 15.3448 | 0.1071 | 0.979 | 0.0398107168699479 | pass |
| ADAUSDT | 515 | -50.4752 | -0.098 | 2/6 | 64.7502 | -0.0996 | 0.984 | 0.9713956434803049 | fail |
| LINKUSDT | 528 | -12.1574 | -0.023 | 3/6 | 26.4929 | -0.023 | 1.003 | 0.6584803398680825 | fail |
| **pooled** | 1589 | -5.3847 | -0.0034 | 2/6 | 47.798 (seq) | - | - | 0.5415898294506849 | - |

Holm survivors (alpha 0.05): []

## arm `T6` (candidate) -- fail -- net_r/trade -0.0082 beats the baseline's -0.0034 by -0.0048 < the 0.0 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DOGEUSDT | 817 | 22.7712 | 0.0279 | 4/6 | 12.8908 | 0.1178 | 0.237 | 0.19746632263831942 | pass |
| ADAUSDT | 802 | -24.3974 | -0.0304 | 2/6 | 34.0075 | -0.1273 | 0.239 | 0.8804904924690441 | fail |
| LINKUSDT | 827 | -18.4731 | -0.0223 | 2/6 | 28.4282 | -0.0939 | 0.238 | 0.8330158334252957 | fail |
| **pooled** | 2446 | -20.0984 | -0.0082 | 2/6 | 46.0773 (seq) | - | - | 0.697466518084711 | - |

Holm survivors (alpha 0.05): []

## arm `T12` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DOGEUSDT | 752 | 43.2254 | 0.0575 | 5/6 | 13.4556 | 0.1349 | 0.426 | 0.0764125996568607 | pass |
| ADAUSDT | 739 | -42.3118 | -0.0573 | 1/6 | 65.2125 | -0.133 | 0.431 | 0.9687061316351422 | fail |
| LINKUSDT | 767 | -3.2462 | -0.0042 | 3/6 | 26.2731 | -0.0098 | 0.432 | 0.5535550832416459 | fail |
| **pooled** | 2258 | -2.3318 | -0.001 | 3/6 | 44.1873 (seq) | - | - | 0.5207334211530132 | - |

Holm survivors (alpha 0.05): []

## arm `T24` (candidate) -- fail -- net_r/trade -0.0043 beats the baseline's -0.0034 by -0.0009 < the 0.0 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DOGEUSDT | 643 | 54.8637 | 0.0853 | 4/6 | 14.1931 | 0.1223 | 0.698 | 0.03558418351298525 | pass |
| ADAUSDT | 619 | -62.3747 | -0.1008 | 1/6 | 77.1739 | -0.1429 | 0.705 | 0.9927805953214225 | fail |
| LINKUSDT | 634 | -0.6994 | -0.0011 | 5/6 | 33.3348 | -0.0015 | 0.714 | 0.5100523951864466 | fail |
| **pooled** | 1896 | -8.2102 | -0.0043 | 4/6 | 43.7907 (seq) | - | - | 0.5672909047215113 | - |

Holm survivors (alpha 0.05): []

