# Stage-0 (synthetic leg) -- squeeze 1h -- pass

PASS: arm WIDE passes (pooled net_r 43.4627); 1 of 4 arms pass. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1132 | -35.3297 | -0.0312 | 2/6 | 65.0664 | -0.0319 | 0.98 | 0.8047635281442644 | fail |
| XRPUSDT | 1188 | -17.847 | -0.015 | 2/6 | 58.6083 | -0.0168 | 0.894 | 0.618455132624784 | fail |
| LINKUSDT | 1141 | -36.357 | -0.0319 | 3/6 | 56.6643 | -0.0326 | 0.979 | 0.7964373604497899 | fail |
| AAVEUSDT | 1070 | -38.7107 | -0.0362 | 1/6 | 56.1573 | -0.0389 | 0.93 | 0.825263774040917 | fail |
| DOGEUSDT | 1194 | 32.4422 | 0.0272 | 4/6 | 41.9692 | 0.0292 | 0.93 | 0.24976948599012733 | pass |
| BNBUSDT | 1166 | -2.2501 | -0.0019 | 4/6 | 46.8533 | -0.0021 | 0.922 | 0.5193474613862337 | fail |
| **pooled** | 6891 | -98.052 | -0.0142 | 1/6 | 132.536 (seq) | - | - | 0.8025731488360419 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade -0.0141 beats the baseline's -0.0142 by 0.0001 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1155 | -34.796 | -0.0301 | 2/6 | 62.6558 | -0.0317 | 0.951 | 0.8036394666294221 | fail |
| XRPUSDT | 1208 | -26.3912 | -0.0218 | 2/6 | 62.332 | -0.0252 | 0.867 | 0.6729283801169523 | fail |
| LINKUSDT | 1160 | -27.9572 | -0.0241 | 2/6 | 47.5812 | -0.0254 | 0.95 | 0.741930209245286 | fail |
| AAVEUSDT | 1084 | -33.7467 | -0.0311 | 1/6 | 55.6218 | -0.0344 | 0.906 | 0.7948424259869789 | fail |
| DOGEUSDT | 1204 | 23.9618 | 0.0199 | 4/6 | 46.284 | 0.0219 | 0.908 | 0.3042449138172765 | pass |
| BNBUSDT | 1181 | 0.5357 | 0.0005 | 4/6 | 47.8768 | 0.0005 | 0.901 | 0.49536353351735657 | pass |
| **pooled** | 6992 | -98.3929 | -0.0141 | 0/6 | 136.5678 (seq) | - | - | 0.8061936965134753 | - |

Holm survivors (alpha 0.05): []

## arm `ST12` (candidate) -- fail -- net_r/trade -0.0014 beats the baseline's -0.0142 by 0.0128 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 1554 | -26.5138 | -0.0171 | 3/6 | 65.1918 | -0.0298 | 0.573 | 0.7456261723261717 | fail |
| XRPUSDT | 1584 | -30.3501 | -0.0192 | 2/6 | 64.4985 | -0.0367 | 0.521 | 0.7003731774965652 | fail |
| LINKUSDT | 1553 | -2.4001 | -0.0015 | 4/6 | 50.7401 | -0.0026 | 0.586 | 0.5220857248876093 | fail |
| AAVEUSDT | 1399 | -43.3522 | -0.031 | 2/6 | 69.8115 | -0.0532 | 0.583 | 0.8596750229989611 | fail |
| DOGEUSDT | 1569 | 45.5743 | 0.029 | 3/6 | 47.958 | 0.0545 | 0.533 | 0.17505058598531803 | fail |
| BNBUSDT | 1507 | 44.2195 | 0.0293 | 4/6 | 37.8292 | 0.0509 | 0.576 | 0.1688206057827496 | pass |
| **pooled** | 9166 | -12.8228 | -0.0014 | 3/6 | 143.4707 (seq) | - | - | 0.5448842398931928 | - |

Holm survivors (alpha 0.05): []

## arm `WIDE` (candidate) -- pass -- pooled net_r 43.4627 > 0 with 4 folds positive and 3 of 6 powered cells pass (breadth floor 3); beats the baseline by 0.074 R/trade

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 113 | 17.3552 | 0.1536 | 4/6 | 9.9825 | 0.1645 | 0.934 | 0.12157286334744255 | pass |
| XRPUSDT | 161 | 21.099 | 0.131 | 4/6 | 12.0607 | 0.1472 | 0.89 | 0.16150797282175627 | pass |
| LINKUSDT | 105 | 11.6208 | 0.1107 | 5/6 | 9.5533 | 0.1207 | 0.917 | 0.177623308224732 | pass |
| AAVEUSDT | 95 | -14.1701 | -0.1492 | 2/6 | 24.869 | -0.1666 | 0.895 | 0.915102789339948 | fail |
| DOGEUSDT | 179 | 8.2525 | 0.0461 | 3/6 | 13.5553 | 0.0519 | 0.888 | 0.33053113505231546 | fail |
| BNBUSDT | 74 | -0.6948 | -0.0094 | 3/6 | 10.9912 | -0.0103 | 0.908 | 0.5259082986356711 | fail |
| **pooled** | 727 | 43.4627 | 0.0598 | 4/6 | 30.388 (seq) | - | - | 0.12269567732621373 | - |

Holm survivors (alpha 0.05): []

