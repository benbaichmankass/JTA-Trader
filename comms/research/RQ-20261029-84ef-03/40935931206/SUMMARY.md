# Stage-0 (synthetic leg) -- trend 1d -- pass

PASS: arm LO passes (pooled net_r 314.2437); 2 of 2 arms pass. Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `LO` (arm) -- pass -- pooled net_r 314.2437 > 0 with 6 folds positive and 11 of 13 powered cells pass (breadth floor 7)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 67 | 34.2213 | 0.5108 | 5/6 | 4.3857 | 0.0114 | 44.731 | 0.0018277121047573063 | pass |
| QQQ | 79 | 43.4649 | 0.5502 | 6/6 | 3.2276 | 0.0153 | 36.051 | 0.0008181246912618773 | pass |
| IWM | 82 | 7.0908 | 0.0865 | 5/6 | 5.0078 | 0.0029 | 29.72 | 0.24557093879482067 | pass |
| GLD | 102 | 49.0202 | 0.4806 | 5/6 | 5.1424 | 0.0292 | 16.48 | 0.001934725444664173 | pass |
| SLV | 103 | 29.637 | 0.2877 | 6/6 | 5.3806 | 0.0201 | 14.32 | 0.025157122971706913 | pass |
| TLT | 96 | 9.1199 | 0.095 | 4/6 | 11.3575 | 0.0064 | 14.75 | 0.23136636346173944 | pass |
| IEF | 92 | 13.0438 | 0.1418 | 3/6 | 13.0366 | 0.0085 | 16.685 | 0.17062420051210103 | fail |
| USO | 94 | 10.5986 | 0.1128 | 3/6 | 8.7079 | 0.0056 | 20.223 | 0.16561634496777067 | fail |
| GDX | 95 | 7.1374 | 0.0751 | 4/6 | 7.3896 | 0.0045 | 16.8 | 0.2786038137140158 | pass |
| TQQQ | 82 | 33.1211 | 0.4039 | 6/6 | 4.3247 | 0.0161 | 25.159 | 0.004848417453065906 | pass |
| QLD | 85 | 44.7358 | 0.5263 | 6/6 | 3.062 | 0.0172 | 30.529 | 0.0007876075838705051 | pass |
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/JTA-Trader/JTA-Trader/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '7300', '--output', 'comms/research/RQ-20261029-84ef-03/40935931206/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| IAUM | 34 | 18.108 | 0.5326 | 4/6 | 4.7023 | 0.0395 | 13.471 | 0.0839247541094354 | pass |
| SCHA | 69 | 14.9456 | 0.2166 | 4/6 | 4.9213 | 0.007 | 31.145 | 0.07707948905767475 | pass |
| **pooled** | 1080 | 314.2437 | 0.291 | 6/6 | 26.3038 (seq) | - | - | 9.201015704623618e-12 | - |

Holm survivors (alpha 0.05): ['QLD', 'QQQ', 'SPY', 'GLD', 'TQQQ']

## arm `LO_TS20` (arm) -- pass -- pooled net_r 250.0393 > 0 with 6 folds positive and 12 of 13 powered cells pass (breadth floor 7)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| SPY | 137 | 24.2739 | 0.1772 | 5/6 | 4.8536 | 0.0111 | 16.0 | 0.010608271029784967 | pass |
| QQQ | 144 | 30.6642 | 0.2129 | 6/6 | 4.0444 | 0.0137 | 15.597 | 0.006775651226086954 | pass |
| IWM | 122 | 2.6317 | 0.0216 | 4/6 | 6.0886 | 0.0014 | 15.115 | 0.3991878563396214 | pass |
| GLD | 125 | 39.0708 | 0.3126 | 5/6 | 5.4444 | 0.0251 | 12.464 | 0.005824378852254506 | pass |
| SLV | 114 | 30.7606 | 0.2698 | 6/6 | 4.8696 | 0.0224 | 12.035 | 0.018450090130993343 | pass |
| TLT | 107 | 15.1564 | 0.1416 | 4/6 | 9.9435 | 0.0118 | 12.028 | 0.12063845584697552 | pass |
| IEF | 109 | 12.9052 | 0.1184 | 3/6 | 11.2853 | 0.0097 | 12.239 | 0.17195985849673617 | fail |
| USO | 118 | 14.4635 | 0.1226 | 4/6 | 7.4072 | 0.0093 | 13.229 | 0.10069620173118654 | pass |
| GDX | 111 | 7.0682 | 0.0637 | 4/6 | 8.2634 | 0.005 | 12.838 | 0.26927779177056466 | pass |
| TQQQ | 122 | 23.4632 | 0.1923 | 6/6 | 5.4834 | 0.0133 | 14.492 | 0.026561318818747306 | pass |
| QLD | 142 | 28.488 | 0.2006 | 6/6 | 4.6844 | 0.0133 | 15.042 | 0.011359566436199701 | pass |
| SPLG | - | - | - | - | - | - | - | - | fetch_failed: CalledProcessError: Command '['/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3', '/home/runner/work/JTA-Trader/JTA-Trader/scripts/ops/fetch_backtest_candles.py', '--symbol', 'SPLG', '--interval', 'D', '--days', '7300', '--output', 'comms/research/RQ-20261029-84ef-03/40935931206/data/SPLG_D.csv', '--source', 'yfinance']' returned non-zero exit status 1. |
| IAUM | 40 | 14.5535 | 0.3638 | 4/6 | 4.7023 | 0.0342 | 10.65 | 0.0737716002040486 | pass |
| SCHA | 109 | 6.5419 | 0.06 | 4/6 | 5.3406 | 0.0041 | 14.697 | 0.25587090748122354 | pass |
| **pooled** | 1500 | 250.0393 | 0.1667 | 6/6 | 30.1814 (seq) | - | - | 6.133617740474131e-09 | - |

Holm survivors (alpha 0.05): []

