# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm T30 passes (pooled net_r 57.4572); 2 of 4 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `T30` (arm) -- pass -- pooled net_r 57.4572 > 0 with 4 folds positive and 4 of 8 powered cells pass (breadth floor 4)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 36 | 2.2764 | 0.0632 | 3/6 | 5.9016 | 0.0018 | 36.056 | 0.3869246617740772 | fail |
| IAUM | 20 | 22.3147 | 1.1157 | 4/6 | 1.445 | 0.053 | 21.05 | 0.02535737499340595 | pass |
| TLT | 37 | -8.3327 | -0.2252 | 2/6 | 11.8104 | -0.0145 | 15.541 | 0.8737472999895461 | fail |
| IEF | 34 | 0.6741 | 0.0198 | 2/6 | 9.4457 | 0.001 | 18.912 | 0.47873398570353365 | fail |
| SLV | 42 | 14.5953 | 0.3475 | 5/6 | 6.8068 | 0.0194 | 17.881 | 0.11492447363718106 | pass |
| USO | 38 | 12.5339 | 0.3298 | 5/6 | 5.0738 | 0.014 | 23.526 | 0.15408999821718233 | pass |
| GDX | 37 | 4.1274 | 0.1116 | 2/6 | 5.2483 | 0.0041 | 27.459 | 0.31871340220988026 | fail |
| XLE | 33 | 9.2681 | 0.2809 | 5/6 | 5.9595 | 0.0084 | 33.303 | 0.18962602600923462 | pass |
| XLU | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLU', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLU_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLP | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLP', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLP_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLF | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLF', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLF_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| **pooled** | 277 | 57.4572 | 0.2074 | 4/6 | 15.9414 (seq) | - | - | 0.02577198063837049 | - |

Holm survivors (alpha 0.05): []

## arm `T55` (arm) -- fail -- pooled passes but only 1 of 7 powered cells pass (< 4): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 32 | -2.3774 | -0.0743 | 2/6 | 5.2649 | -0.0024 | 30.875 | 0.6260267586448073 | fail |
| IAUM | 18 | 17.5849 | 0.9769 | 4/6 | 1.0548 | 0.0469 | 20.833 | 0.04872379429009211 | indeterminate |
| TLT | 27 | -7.2758 | -0.2695 | 2/6 | 7.5817 | -0.0195 | 13.815 | 0.8965631921453638 | fail |
| IEF | 25 | 2.0844 | 0.0834 | 3/6 | 6.5706 | 0.0049 | 17.12 | 0.41508538452761934 | fail |
| SLV | 30 | 14.851 | 0.495 | 3/6 | 6.1311 | 0.0257 | 19.267 | 0.11365377129779569 | fail |
| USO | 28 | 10.914 | 0.3898 | 5/6 | 4.056 | 0.0155 | 25.143 | 0.13481837973866567 | pass |
| GDX | 30 | 1.2176 | 0.0406 | 3/6 | 6.116 | 0.0016 | 25.9 | 0.4399212482619924 | fail |
| XLE | 27 | 5.7044 | 0.2113 | 3/6 | 5.3565 | 0.0084 | 25.296 | 0.2841954525309893 | fail |
| XLU | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLU', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLU_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLP | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLP', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLP_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLF | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLF', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLF_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| **pooled** | 217 | 42.7031 | 0.1968 | 4/6 | 20.1907 (seq) | - | - | 0.051389961692302866 | - |

Holm survivors (alpha 0.05): []

## arm `T30X` (arm) -- pass -- pooled net_r 52.8033 > 0 with 4 folds positive and 4 of 8 powered cells pass (breadth floor 4)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 36 | 1.7784 | 0.0494 | 2/6 | 6.0823 | 0.0014 | 36.056 | 0.41118531882148945 | fail |
| IAUM | 20 | 21.9505 | 1.0975 | 4/6 | 1.4898 | 0.0521 | 21.05 | 0.026995721184792883 | pass |
| TLT | 37 | -9.1169 | -0.2464 | 2/6 | 12.2174 | -0.0159 | 15.541 | 0.8945959880666761 | fail |
| IEF | 34 | -0.9356 | -0.0275 | 2/6 | 10.2858 | -0.0015 | 18.912 | 0.5295307841685637 | fail |
| SLV | 42 | 14.1363 | 0.3366 | 5/6 | 6.9302 | 0.0188 | 17.881 | 0.12220828682843049 | pass |
| USO | 38 | 12.2212 | 0.3216 | 5/6 | 5.1155 | 0.0137 | 23.526 | 0.15997457550163668 | pass |
| GDX | 37 | 3.8364 | 0.1037 | 2/6 | 5.51 | 0.0038 | 27.459 | 0.3306574775842918 | fail |
| XLE | 33 | 8.9331 | 0.2707 | 5/6 | 6.0382 | 0.0081 | 33.303 | 0.1982221340377096 | pass |
| XLU | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLU', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLU_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLP | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLP', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLP_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLF | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLF', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLF_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| **pooled** | 277 | 52.8033 | 0.1906 | 4/6 | 16.7354 (seq) | - | - | 0.03667377744464708 | - |

Holm survivors (alpha 0.05): []

## arm `T55X` (arm) -- fail -- pooled passes but only 1 of 7 powered cells pass (< 4): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| SCHA | 32 | -2.8454 | -0.0889 | 2/6 | 5.4191 | -0.0029 | 30.875 | 0.6497362752187352 | fail |
| IAUM | 18 | 17.2636 | 0.9591 | 4/6 | 1.1081 | 0.046 | 20.833 | 0.05142766431737243 | indeterminate |
| TLT | 27 | -7.8641 | -0.2913 | 1/6 | 7.8641 | -0.0211 | 13.815 | 0.9133569117817433 | fail |
| IEF | 25 | 0.8085 | 0.0323 | 3/6 | 6.9571 | 0.0019 | 17.12 | 0.4668318608310233 | fail |
| SLV | 30 | 14.5363 | 0.4845 | 3/6 | 6.2141 | 0.0251 | 19.267 | 0.11842608202783539 | fail |
| USO | 28 | 10.6789 | 0.3814 | 5/6 | 4.1121 | 0.0152 | 25.143 | 0.13981885091408924 | pass |
| GDX | 30 | 0.9857 | 0.0329 | 3/6 | 6.3247 | 0.0013 | 25.9 | 0.4513039516840914 | fail |
| XLE | 27 | 5.4099 | 0.2004 | 3/6 | 5.5053 | 0.0079 | 25.296 | 0.2941996444584144 | fail |
| XLU | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLU', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLU_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLP | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLP', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLP_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| XLF | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/Metis-Insights/Metis-Insights/scripts/ops/fetch_backtest_candles.py', '--symbol', 'XLF', '--interval', 'D', '--days', '4300', '--output', 'comms/research/RQ-20261025-bda2-01/40256550846/data/XLF_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| **pooled** | 217 | 38.973 | 0.1796 | 4/6 | 21.2296 (seq) | - | - | 0.0681241450999785 | - |

Holm survivors (alpha 0.05): []

