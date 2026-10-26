# Stage-0 (synthetic leg) -- trend 1w -- indeterminate

INDETERMINATE: W10: pooled net_r <= 0 or folds short; W20: only 1 powered cell(s) (< 2): breadth cannot be read. Thresholds: n_floor 10, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `W10` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 10 | 4.4859 | 0.4486 | 1/6 | 1.9797 | 0.0026 | 174.3 | 0.26465822504824543 | fail |
| ETHUSDT | 14 | 1.3005 | 0.0929 | 3/6 | 3.084 | 0.0009 | 108.5 | 0.38296845159637366 | fail |
| SOLUSDT | 8 | 1.7905 | 0.2238 | 2/6 | 3.688 | 0.0012 | 186.375 | 0.35933037485091024 | indeterminate |
| XRPUSDT | 7 | -0.0905 | -0.0129 | 2/6 | 2.5295 | -0.0001 | 255.003 | 0.5142106373453568 | indeterminate |
| ADAUSDT | 7 | 0.8372 | 0.1196 | 2/6 | 1.0351 | 0.0004 | 268.002 | 0.3912377175268008 | indeterminate |
| AVAXUSDT | 4 | 1.5281 | 0.382 | 2/6 | 1.0277 | 0.0008 | 455.0 | 0.3203359766934421 | indeterminate |
| **pooled** | 50 | 9.8515 | 0.197 | 3/6 | 10.3495 (seq) | - | - | 0.16633279905594106 | - |

Holm survivors (alpha 0.05): []

## arm `W20` (arm) -- indeterminate -- only 1 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 9 | 4.7688 | 0.5299 | 2/6 | 1.4158 | 0.0031 | 168.777 | 0.24347323566068113 | indeterminate |
| ETHUSDT | 11 | -1.6135 | -0.1467 | 1/6 | 5.6253 | -0.001 | 144.452 | 0.6435062950043695 | fail |
| SOLUSDT | 9 | -1.804 | -0.2004 | 2/6 | 4.7173 | -0.0014 | 140.0 | 0.6813027225240681 | indeterminate |
| XRPUSDT | 7 | -1.8174 | -0.2596 | 1/6 | 3.2514 | -0.0029 | 89.999 | 0.7384480707800083 | indeterminate |
| ADAUSDT | 7 | -1.91 | -0.2729 | 1/6 | 3.855 | -0.0014 | 194.999 | 0.7579698312712928 | indeterminate |
| AVAXUSDT | 6 | -0.7787 | -0.1298 | 1/6 | 2.3735 | -0.0005 | 260.169 | 0.5898340842506957 | indeterminate |
| **pooled** | 49 | -3.1545 | -0.0644 | 2/6 | 19.4331 (seq) | - | - | 0.6273843990361668 | - |

Holm survivors (alpha 0.05): []

