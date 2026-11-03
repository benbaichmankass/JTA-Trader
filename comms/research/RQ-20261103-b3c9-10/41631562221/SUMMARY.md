# Stage-0 (synthetic leg) -- squeeze 1d -- indeterminate

INDETERMINATE: B: pooled net_r 16.2544 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6); L: 0 of 12 cells measured (< half); S: 0 of 12 cells measured (< half). Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- pass -- pooled net_r 16.2544 > 0 with 4 folds positive and 6 of 12 powered cells pass (breadth floor 6)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 45 | -3.2138 | -0.0714 | 2/6 | 11.7579 | -0.0034 | 21.0 | 0.6326107585174278 | fail |
| ETHUSDT | 48 | 2.7769 | 0.0579 | 4/6 | 5.3501 | 0.0029 | 20.188 | 0.39804435794354676 | pass |
| SOLUSDT | 42 | 1.8319 | 0.0436 | 4/6 | 6.286 | 0.0021 | 20.381 | 0.41710665794331914 | pass |
| XRPUSDT | 53 | -9.1836 | -0.1733 | 3/6 | 16.7398 | -0.0079 | 21.811 | 0.8322083817450683 | fail |
| ADAUSDT | 49 | 8.3425 | 0.1703 | 4/6 | 4.7458 | 0.0091 | 18.755 | 0.19744535810291863 | pass |
| AVAXUSDT | 40 | -1.703 | -0.0426 | 1/6 | 6.4537 | -0.0021 | 20.125 | 0.5877050371690578 | fail |
| BNBUSDT | 46 | 19.0932 | 0.4151 | 5/6 | 4.2147 | 0.0193 | 21.478 | 0.0811552496518878 | pass |
| DOGEUSDT | 46 | 6.8326 | 0.1485 | 4/6 | 4.6662 | 0.006 | 24.826 | 0.2105113789674054 | pass |
| LINKUSDT | 51 | -0.3604 | -0.0071 | 2/6 | 11.9609 | -0.0003 | 20.471 | 0.5178187251331117 | fail |
| LTCUSDT | 47 | -4.1511 | -0.0883 | 2/6 | 13.6835 | -0.0037 | 23.809 | 0.7078997957796619 | fail |
| BCHUSDT | 48 | -6.2023 | -0.1292 | 2/6 | 13.0579 | -0.007 | 18.396 | 0.7475211978821732 | fail |
| DOTUSDT | 45 | 2.1924 | 0.0487 | 4/6 | 4.6757 | 0.0021 | 23.511 | 0.3663613891568831 | pass |
| **pooled** | 560 | 16.2544 | 0.029 | 4/6 | 54.2232 (seq) | - | - | 0.30482573961904413 | - |

Holm survivors (alpha 0.05): []

## arm `L` (candidate) -- indeterminate -- 0 of 12 cells measured (< half)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BTCUSDT_1d_L.log |
| ETHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_ETHUSDT_1d_L.log |
| SOLUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_SOLUSDT_1d_L.log |
| XRPUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_XRPUSDT_1d_L.log |
| ADAUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_ADAUSDT_1d_L.log |
| AVAXUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_AVAXUSDT_1d_L.log |
| BNBUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BNBUSDT_1d_L.log |
| DOGEUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_DOGEUSDT_1d_L.log |
| LINKUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_LINKUSDT_1d_L.log |
| LTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_LTCUSDT_1d_L.log |
| BCHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BCHUSDT_1d_L.log |
| DOTUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_DOTUSDT_1d_L.log |

Holm survivors (alpha 0.05): []

## arm `S` (candidate) -- indeterminate -- 0 of 12 cells measured (< half)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BTCUSDT_1d_S.log |
| ETHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_ETHUSDT_1d_S.log |
| SOLUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_SOLUSDT_1d_S.log |
| XRPUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_XRPUSDT_1d_S.log |
| ADAUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_ADAUSDT_1d_S.log |
| AVAXUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_AVAXUSDT_1d_S.log |
| BNBUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BNBUSDT_1d_S.log |
| DOGEUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_DOGEUSDT_1d_S.log |
| LINKUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_LINKUSDT_1d_S.log |
| LTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_LTCUSDT_1d_S.log |
| BCHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_BCHUSDT_1d_S.log |
| DOTUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log squeeze_DOTUSDT_1d_S.log |

Holm survivors (alpha 0.05): []

