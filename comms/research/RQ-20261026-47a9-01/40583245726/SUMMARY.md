# Stage-0 (synthetic leg) -- trend 1d -- indeterminate

INDETERMINATE: T30: only 0 powered cell(s) (< 2): breadth cannot be read; T30X: only 0 powered cell(s) (< 2): breadth cannot be read. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `T30` (arm) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '1900', '--output', 'comms/research/RQ-20261026-47a9-01/40583245726/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 15 | -0.7113 | -0.0474 | 3/6 | 4.2562 | -0.0013 | 37.733 | 0.5684279097637763 | indeterminate |
| IAUM | 16 | 22.8618 | 1.4289 | 5/6 | 1.019 | 0.0588 | 24.312 | 0.020960165885549085 | indeterminate |
| TLT | 14 | -6.9877 | -0.4991 | 2/6 | 7.477 | -0.0325 | 15.357 | 0.9866649435579659 | indeterminate |
| IEF | 16 | -7.0384 | -0.4399 | 1/6 | 7.0384 | -0.0222 | 19.812 | 0.9619899077128159 | indeterminate |
| SLV | 17 | 11.1104 | 0.6536 | 4/6 | 1.8618 | 0.0288 | 22.706 | 0.09208766857532258 | indeterminate |
| USO | 16 | 5.8235 | 0.364 | 4/6 | 2.8363 | 0.0222 | 16.375 | 0.27083260761118966 | indeterminate |
| GDX | 16 | 5.2647 | 0.329 | 3/6 | 3.1652 | 0.0115 | 28.625 | 0.2421855789340387 | indeterminate |
| XLE | 17 | 2.6905 | 0.1583 | 3/6 | 5.1783 | 0.0061 | 26.059 | 0.37658278456995264 | indeterminate |
| **pooled** | 127 | 33.0135 | 0.2599 | 4/6 | 15.9414 (seq) | - | - | 0.058818567419405776 | - |

Holm survivors (alpha 0.05): []

## arm `T30X` (arm) -- indeterminate -- only 0 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '1900', '--output', 'comms/research/RQ-20261026-47a9-01/40583245726/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 15 | -0.8858 | -0.0591 | 3/6 | 4.3361 | -0.0016 | 37.733 | 0.5849222521524426 | indeterminate |
| IAUM | 16 | 22.5826 | 1.4114 | 5/6 | 1.038 | 0.0581 | 24.312 | 0.021947849653218086 | indeterminate |
| TLT | 14 | -7.2501 | -0.5179 | 2/6 | 7.7039 | -0.0337 | 15.357 | 0.9887534489310765 | indeterminate |
| IEF | 16 | -7.6521 | -0.4783 | 1/6 | 7.6521 | -0.0241 | 19.812 | 0.9721843026776118 | indeterminate |
| SLV | 17 | 10.9613 | 0.6448 | 4/6 | 1.8993 | 0.0284 | 22.706 | 0.09478382887397241 | indeterminate |
| USO | 16 | 5.6934 | 0.3558 | 3/6 | 2.8494 | 0.0217 | 16.375 | 0.2751859789433262 | indeterminate |
| GDX | 16 | 5.1521 | 0.322 | 3/6 | 3.2545 | 0.0112 | 28.625 | 0.24683919962601042 | indeterminate |
| XLE | 17 | 2.5217 | 0.1483 | 3/6 | 5.3017 | 0.0057 | 26.059 | 0.3839894101297763 | indeterminate |
| **pooled** | 127 | 31.1233 | 0.2451 | 4/6 | 16.5596 (seq) | - | - | 0.06999238106913103 | - |

Holm survivors (alpha 0.05): []

