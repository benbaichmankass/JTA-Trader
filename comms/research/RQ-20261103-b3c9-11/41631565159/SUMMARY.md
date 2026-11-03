# Stage-0 (synthetic leg) -- fade 1d -- indeterminate

INDETERMINATE: B: pooled net_r <= 0 or folds short; L: 0 of 12 cells measured (< half); S: 0 of 12 cells measured (< half). Thresholds: n_floor 20, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.1 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | 94 | -15.718 | -0.1672 | 2/6 | 14.5711 | None | None | 0.8259039308769005 | fail |
| ETHUSDT | 96 | -46.8372 | -0.4879 | 1/6 | 39.277 | None | None | 0.9992657368243947 | fail |
| SOLUSDT | 95 | -9.4226 | -0.0992 | 3/6 | 23.9397 | None | None | 0.6954426329655126 | fail |
| XRPUSDT | 82 | -42.7585 | -0.5214 | 0/6 | 40.5322 | None | None | 0.9999710468665602 | fail |
| ADAUSDT | 87 | -8.5348 | -0.0981 | 3/6 | 15.256 | None | None | 0.7045296604445853 | fail |
| AVAXUSDT | 87 | -1.173 | -0.0135 | 2/6 | 11.9629 | None | None | 0.5269572791614205 | fail |
| BNBUSDT | 91 | -25.5994 | -0.2813 | 2/6 | 21.537 | None | None | 0.9525765038779357 | fail |
| DOGEUSDT | 72 | 0.5228 | 0.0073 | 4/6 | 15.272 | None | None | 0.4868626492026851 | pass |
| LINKUSDT | 96 | -11.3036 | -0.1177 | 2/6 | 26.4552 | None | None | 0.7480955435870984 | fail |
| LTCUSDT | 81 | 32.208 | 0.3976 | 5/6 | 13.7984 | None | None | 0.05137350218079034 | pass |
| BCHUSDT | 83 | -27.4046 | -0.3302 | 2/6 | 29.0814 | None | None | 0.9700328857984695 | fail |
| DOTUSDT | 91 | -13.0716 | -0.1436 | 3/6 | 12.2481 | None | None | 0.8039060157077818 | fail |
| **pooled** | 1055 | -169.0918 | -0.1603 | 1/6 | 188.5073 (seq) | - | - | 0.998824578655364 | - |

Holm survivors (alpha 0.05): []

## arm `L` (candidate) -- indeterminate -- 0 of 12 cells measured (< half)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BTCUSDT_1d_L.log |
| ETHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_ETHUSDT_1d_L.log |
| SOLUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_SOLUSDT_1d_L.log |
| XRPUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_XRPUSDT_1d_L.log |
| ADAUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_ADAUSDT_1d_L.log |
| AVAXUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_AVAXUSDT_1d_L.log |
| BNBUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BNBUSDT_1d_L.log |
| DOGEUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_DOGEUSDT_1d_L.log |
| LINKUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_LINKUSDT_1d_L.log |
| LTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_LTCUSDT_1d_L.log |
| BCHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BCHUSDT_1d_L.log |
| DOTUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_DOTUSDT_1d_L.log |

Holm survivors (alpha 0.05): []

## arm `S` (candidate) -- indeterminate -- 0 of 12 cells measured (< half)

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BTCUSDT_1d_S.log |
| ETHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_ETHUSDT_1d_S.log |
| SOLUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_SOLUSDT_1d_S.log |
| XRPUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_XRPUSDT_1d_S.log |
| ADAUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_ADAUSDT_1d_S.log |
| AVAXUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_AVAXUSDT_1d_S.log |
| BNBUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BNBUSDT_1d_S.log |
| DOGEUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_DOGEUSDT_1d_S.log |
| LINKUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_LINKUSDT_1d_S.log |
| LTCUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_LTCUSDT_1d_S.log |
| BCHUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_BCHUSDT_1d_S.log |
| DOTUSDT | - | - | - | - | - | - | - | - | harness_failed: exit 2; log fade_DOTUSDT_1d_S.log |

Holm survivors (alpha 0.05): []

