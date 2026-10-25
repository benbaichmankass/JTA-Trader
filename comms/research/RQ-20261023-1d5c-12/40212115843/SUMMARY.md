# Stage-0 (synthetic leg) -- fade 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; MID: net_r/trade -0.1428 beats the baseline's -0.0771 by -0.0657 < the 0.05 materiality bar; TRL: net_r/trade -0.0836 beats the baseline's -0.0771 by -0.0065 < the 0.05 materiality bar; TP1: net_r/trade -0.1205 beats the baseline's -0.0771 by -0.0434 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 563 | -86.3091 | -0.1533 | 1/6 | 61.084 | None | None | 0.9825719742479504 | fail |
| LINKUSDT | 620 | -110.7451 | -0.1786 | 1/6 | 102.9772 | None | None | 0.9945271642701403 | fail |
| DOGEUSDT | 489 | -14.3916 | -0.0294 | 2/6 | 51.7412 | None | None | 0.6437247103382432 | fail |
| LTCUSDT | 559 | -27.6606 | -0.0495 | 3/6 | 58.9035 | None | None | 0.7416171790649511 | fail |
| BCHUSDT | 532 | 10.3852 | 0.0195 | 4/6 | 45.5109 | None | None | 0.4037091799129786 | pass |
| DOTUSDT | 551 | -26.8547 | -0.0487 | 3/6 | 25.7974 | None | None | 0.7370663477605869 | fail |
| **pooled** | 3314 | -255.5801 | -0.0771 | 1/6 | 276.9557 (seq) | - | - | 0.9936767313970949 | - |

Holm survivors (alpha 0.05): []

## arm `MID` (candidate) -- fail -- net_r/trade -0.1428 beats the baseline's -0.0771 by -0.0657 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 290 | -44.7648 | -0.1544 | 1/6 | 30.0688 | None | None | 0.9868504409897418 | fail |
| LINKUSDT | 299 | -49.5776 | -0.1658 | 0/6 | 46.8254 | None | None | 0.9897780644159621 | fail |
| DOGEUSDT | 255 | -45.1986 | -0.1772 | 0/6 | 45.9542 | None | None | 0.9955006578186023 | fail |
| LTCUSDT | 321 | -24.0637 | -0.075 | 2/6 | 33.9774 | None | None | 0.8673591798422207 | fail |
| BCHUSDT | 277 | -40.2783 | -0.1454 | 1/6 | 27.6164 | None | None | 0.9821765155883951 | fail |
| DOTUSDT | 271 | -40.7222 | -0.1503 | 1/6 | 50.8148 | None | None | 0.9816755234806321 | fail |
| **pooled** | 1713 | -244.6044 | -0.1428 | 1/6 | 265.9884 (seq) | - | - | 0.9999997512433987 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- net_r/trade -0.0836 beats the baseline's -0.0771 by -0.0065 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 234 | -12.6011 | -0.0539 | 3/6 | 21.5145 | None | None | 0.6516332631882298 | fail |
| LINKUSDT | 237 | -52.8761 | -0.2231 | 1/6 | 43.4143 | None | None | 0.9748085443226165 | fail |
| DOGEUSDT | 198 | -37.7447 | -0.1906 | 1/6 | 51.6043 | None | None | 0.8974804201858682 | fail |
| LTCUSDT | 232 | -8.1578 | -0.0352 | 2/6 | 35.6236 | None | None | 0.6035947133499 | fail |
| BCHUSDT | 213 | 18.3722 | 0.0863 | 4/6 | 23.6014 | None | None | 0.2751051229514915 | pass |
| DOTUSDT | 209 | -17.5795 | -0.0841 | 4/6 | 41.7393 | None | None | 0.7349616701402819 | fail |
| **pooled** | 1323 | -110.5858 | -0.0836 | 2/6 | 147.2929 (seq) | - | - | 0.9350243067116273 | - |

Holm survivors (alpha 0.05): []

## arm `TP1` (candidate) -- fail -- net_r/trade -0.1205 beats the baseline's -0.0771 by -0.0434 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 298 | -44.8847 | -0.1506 | 0/6 | 31.8367 | None | None | 0.9952301041655972 | fail |
| LINKUSDT | 313 | -36.3588 | -0.1162 | 4/6 | 28.0 | None | None | 0.9799444661579539 | fail |
| DOGEUSDT | 250 | -49.9505 | -0.1998 | 2/6 | 48.0 | None | None | 0.9992010886916383 | fail |
| LTCUSDT | 320 | -32.7168 | -0.1022 | 1/6 | 35.0 | None | None | 0.9656586058696173 | fail |
| BCHUSDT | 273 | -26.92 | -0.0986 | 2/6 | 19.0 | None | None | 0.9480376312365643 | fail |
| DOTUSDT | 276 | -17.5792 | -0.0637 | 2/6 | 22.0 | None | None | 0.8539745284017122 | fail |
| **pooled** | 1730 | -208.4087 | -0.1205 | 1/6 | 233.1907 (seq) | - | - | 0.9999997216871891 | - |

Holm survivors (alpha 0.05): []

