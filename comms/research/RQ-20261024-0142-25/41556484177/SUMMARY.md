# Stage-0 (synthetic leg) -- trend 1d -- fail

FAIL: B: pooled net_r <= 0 or folds short; D55: net_r/trade -0.0417 beats the baseline's 0.0717 by -0.1134 < the 0.1 materiality bar; D100: net_r/trade 0.1256 beats the baseline's 0.0717 by 0.0539 < the 0.1 materiality bar. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 42 | 16.0844 | 0.383 | 4/6 | 5.8133 | 0.0102 | 37.619 | 0.16504305859945223 | pass |
| DOGEUSDT | 40 | 20.6334 | 0.5158 | 3/6 | 11.0581 | 0.0141 | 36.575 | 0.1643337176195122 | fail |
| LINKUSDT | 47 | -9.4387 | -0.2008 | 2/6 | 15.0637 | -0.0057 | 35.043 | 0.8231431289960954 | fail |
| LTCUSDT | 41 | -6.9064 | -0.1684 | 3/6 | 13.394 | -0.0045 | 37.39 | 0.8396868210849646 | fail |
| BCHUSDT | 43 | -9.8012 | -0.2279 | 1/6 | 14.6987 | -0.0064 | 35.698 | 0.8682401639661782 | fail |
| DOTUSDT | 30 | 6.8617 | 0.2287 | 4/6 | 7.6622 | 0.0041 | 56.2 | 0.2600605570482749 | pass |
| **pooled** | 243 | 17.4331 | 0.0717 | 3/6 | 46.2942 (seq) | - | - | 0.29434756633518006 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- net_r/trade -0.0417 beats the baseline's 0.0717 by -0.1134 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 33 | 10.2324 | 0.3101 | 3/6 | 7.2094 | 0.0102 | 30.424 | 0.25283472425813036 | fail |
| DOGEUSDT | 32 | 11.0639 | 0.3457 | 1/6 | 10.0858 | 0.013 | 26.5 | 0.2933331062333988 | fail |
| LINKUSDT | 40 | -16.1079 | -0.4027 | 0/6 | 16.1079 | -0.0169 | 23.775 | 0.960184527556584 | fail |
| LTCUSDT | 36 | -13.59 | -0.3775 | 1/6 | 16.7409 | -0.0137 | 27.556 | 0.9846298364193524 | fail |
| BCHUSDT | 32 | -10.7476 | -0.3359 | 0/6 | 12.9112 | -0.0122 | 27.5 | 0.9134855143408545 | fail |
| DOTUSDT | 22 | 11.0122 | 0.5006 | 4/6 | 4.8139 | 0.0071 | 70.318 | 0.13318965449458575 | pass |
| **pooled** | 195 | -8.137 | -0.0417 | 2/6 | 50.931 (seq) | - | - | 0.6062435047405201 | - |

Holm survivors (alpha 0.05): []

## arm `D100` (candidate) -- fail -- net_r/trade 0.1256 beats the baseline's 0.0717 by 0.0539 < the 0.1 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 21 | 16.7577 | 0.798 | 4/6 | 4.9394 | 0.0195 | 40.857 | 0.13767241986700596 | pass |
| DOGEUSDT | 19 | 17.4508 | 0.9185 | 5/6 | 3.108 | 0.0271 | 33.947 | 0.1210588127537578 | indeterminate |
| LINKUSDT | 26 | -8.3103 | -0.3196 | 2/6 | 9.2796 | -0.0136 | 23.5 | 0.8320525884853254 | fail |
| LTCUSDT | 24 | -10.9922 | -0.458 | 1/6 | 13.7795 | -0.0133 | 34.5 | 0.994766700992274 | fail |
| BCHUSDT | 20 | -2.7355 | -0.1368 | 2/6 | 5.9222 | -0.0046 | 29.85 | 0.6567132161686545 | fail |
| DOTUSDT | 19 | 4.03 | 0.2121 | 4/6 | 4.1896 | 0.004 | 53.368 | 0.3098451830690521 | indeterminate |
| **pooled** | 129 | 16.2005 | 0.1256 | 2/6 | 26.897 (seq) | - | - | 0.26114999000576955 | - |

Holm survivors (alpha 0.05): []

