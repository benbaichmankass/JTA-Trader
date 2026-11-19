# Stage-0 (synthetic leg) -- pullback 1d -- indeterminate

INDETERMINATE: A: pooled net_r <= 0 or folds short; LONG: only 0 powered cell(s) (< 2): breadth cannot be read; SHORT: only 0 powered cell(s) (< 2): breadth cannot be read. Thresholds: n_floor 20, pooled_n_floor 60, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline A with materiality 0.02 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `A` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| IEF | 24 | -1.5775 | -0.0657 | 3/6 | 6.3712 | -0.0019 | 34.042 | 0.5964075210835367 | fail |
| TLT | 25 | -2.9291 | -0.1172 | 3/6 | 5.913 | -0.0032 | 36.44 | 0.6479399497674891 | fail |
| SLV | 29 | 11.6181 | 0.4006 | 2/6 | 9.3721 | 0.0137 | 29.276 | 0.2349175754239471 | fail |
| GLD | 21 | 18.2708 | 0.87 | 6/6 | 4.0941 | 0.019 | 45.762 | 0.040457325327832847 | pass |
| GDX | 26 | -0.6373 | -0.0245 | 3/6 | 7.6576 | -0.0007 | 35.231 | 0.5339467100424907 | fail |
| **pooled** | 125 | 24.7446 | 0.198 | 2/6 | 19.9789 (seq) | - | - | 0.13639968029880994 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| IEF | 13 | -6.2256 | -0.4789 | 2/6 | 6.2256 | -0.0165 | 29.0 | 0.9587818922670855 | indeterminate |
| TLT | 12 | -3.4324 | -0.286 | 2/6 | 3.9252 | -0.0085 | 33.5 | 0.8661127149204602 | indeterminate |
| SLV | 16 | 20.3034 | 1.269 | 3/6 | 3.3152 | 0.0358 | 35.438 | 0.09801324319557286 | indeterminate |
| GLD | 13 | 18.7198 | 1.44 | 5/6 | 2.0403 | 0.0293 | 49.077 | 0.026106502756419903 | indeterminate |
| GDX | 14 | 5.524 | 0.3946 | 2/6 | 2.9937 | 0.0103 | 38.286 | 0.20443561855759623 | indeterminate |
| **pooled** | 68 | 34.8894 | 0.5131 | 2/6 | 13.9812 (seq) | - | - | 0.0397929358862364 | - |

Holm survivors (alpha 0.05): []

## arm `SHORT` (candidate) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| IEF | 14 | 1.8009 | 0.1286 | 4/6 | 4.2227 | 0.0038 | 34.214 | 0.3803877204223457 | indeterminate |
| TLT | 14 | 5.5751 | 0.3982 | 4/6 | 3.0354 | 0.0085 | 46.929 | 0.21524937348103712 | indeterminate |
| SLV | 13 | -5.5748 | -0.4288 | 1/6 | 7.6267 | -0.0127 | 33.846 | 0.9298844031975825 | indeterminate |
| GLD | 12 | -4.5241 | -0.377 | 3/6 | 6.0931 | -0.0126 | 29.917 | 0.8505799906266938 | indeterminate |
| GDX | 13 | -7.1672 | -0.5513 | 2/6 | 7.3975 | -0.0184 | 29.923 | 0.9810117024975366 | indeterminate |
| **pooled** | 66 | -9.8904 | -0.1499 | 2/6 | 19.2235 (seq) | - | - | 0.8134541817280065 | - |

Holm survivors (alpha 0.05): []

