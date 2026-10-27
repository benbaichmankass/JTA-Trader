# Stage-0 (synthetic leg) -- fade 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; R20: net_r/trade -0.1734 beats the baseline's -0.1147 by -0.0587 < the 0.05 materiality bar; R20MID: net_r/trade -0.1504 beats the baseline's -0.1147 by -0.0357 < the 0.05 materiality bar; R20TRL: net_r/trade -0.1101 beats the baseline's -0.1147 by 0.0046 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 548 | -95.7368 | -0.1747 | 1/6 | 85.2285 | None | None | 0.9938474876222934 | fail |
| XRPUSDT | 491 | -32.6432 | -0.0665 | 2/6 | 37.8274 | None | None | 0.7976209143978528 | fail |
| LINKUSDT | 622 | -112.8611 | -0.1814 | 1/6 | 102.9772 | None | None | 0.9952256498858502 | fail |
| DOGEUSDT | 490 | -15.4687 | -0.0316 | 2/6 | 51.7412 | None | None | 0.6538956044618137 | fail |
| BNBUSDT | 563 | -87.3977 | -0.1552 | 2/6 | 61.084 | None | None | 0.9837522999432544 | fail |
| AVAXUSDT | 555 | -30.8016 | -0.0555 | 2/6 | 94.4426 | None | None | 0.7631847461702377 | fail |
| **pooled** | 3269 | -374.9119 | -0.1147 | 0/6 | 411.2102 (seq) | - | - | 0.9999162824674029 | - |

Holm survivors (alpha 0.05): []

## arm `R20` (candidate) -- fail -- net_r/trade -0.1734 beats the baseline's -0.1147 by -0.0587 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 224 | -31.4321 | -0.1403 | 1/6 | 38.5438 | None | None | 0.896849566862396 | fail |
| XRPUSDT | 191 | -0.0009 | -0.0 | 3/6 | 20.0047 | None | None | 0.500010062961201 | fail |
| LINKUSDT | 245 | -27.5888 | -0.1126 | 2/6 | 31.4916 | None | None | 0.837019517593404 | fail |
| DOGEUSDT | 200 | -71.251 | -0.3563 | 0/6 | 62.9757 | None | None | 0.9997669752234387 | fail |
| BNBUSDT | 243 | -55.269 | -0.2274 | 1/6 | 40.4997 | None | None | 0.9834032953846766 | fail |
| AVAXUSDT | 202 | -40.7133 | -0.2016 | 1/6 | 49.4155 | None | None | 0.9490663477281184 | fail |
| **pooled** | 1305 | -226.2552 | -0.1734 | 0/6 | 250.0908 (seq) | - | - | 0.9999066411141128 | - |

Holm survivors (alpha 0.05): []

## arm `R20MID` (candidate) -- fail -- net_r/trade -0.1504 beats the baseline's -0.1147 by -0.0357 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 280 | -49.5283 | -0.1769 | 0/6 | 39.205 | None | None | 0.9953740183910472 | fail |
| XRPUSDT | 231 | -36.8828 | -0.1597 | 1/6 | 31.3417 | None | None | 0.9822450100794622 | fail |
| LINKUSDT | 300 | -50.6181 | -0.1687 | 0/6 | 46.8254 | None | None | 0.9909698168548225 | fail |
| DOGEUSDT | 255 | -45.1986 | -0.1772 | 0/6 | 45.9542 | None | None | 0.9955006578186023 | fail |
| BNBUSDT | 290 | -44.7648 | -0.1544 | 1/6 | 30.0688 | None | None | 0.9868504409897418 | fail |
| AVAXUSDT | 254 | -15.1105 | -0.0595 | 2/6 | 20.8835 | None | None | 0.773330056752036 | fail |
| **pooled** | 1610 | -242.104 | -0.1504 | 0/6 | 253.301 (seq) | - | - | 0.9999998521334754 | - |

Holm survivors (alpha 0.05): []

## arm `R20TRL` (candidate) -- fail -- net_r/trade -0.1101 beats the baseline's -0.1147 by 0.0046 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| ADAUSDT | 209 | -2.2585 | -0.0108 | 2/6 | 25.5556 | None | None | 0.5309895708482446 | fail |
| XRPUSDT | 184 | -23.2953 | -0.1266 | 2/6 | 19.8218 | None | None | 0.8422782516649537 | fail |
| LINKUSDT | 238 | -53.9166 | -0.2265 | 1/6 | 43.4143 | None | None | 0.9769256330524917 | fail |
| DOGEUSDT | 198 | -37.7447 | -0.1906 | 1/6 | 51.6043 | None | None | 0.8974804201858682 | fail |
| BNBUSDT | 234 | -12.6011 | -0.0539 | 3/6 | 21.5145 | None | None | 0.6516332631882298 | fail |
| AVAXUSDT | 192 | -8.4182 | -0.0438 | 2/6 | 33.1559 | None | None | 0.6048762182382883 | fail |
| **pooled** | 1255 | -138.2351 | -0.1101 | 1/6 | 182.6773 (seq) | - | - | 0.9744569722567863 | - |

Holm survivors (alpha 0.05): []

