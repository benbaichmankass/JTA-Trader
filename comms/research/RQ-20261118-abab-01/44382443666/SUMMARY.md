# Stage-0 (synthetic leg) -- trend 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; D55: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DASHUSDT | 224 | 4.9343 | 0.022 | 4/6 | 31.4271 | 0.0028 | 7.892 | 0.4330047317757263 | pass |
| ONTUSDT | 225 | 2.3262 | 0.0103 | 2/6 | 23.0763 | 0.0013 | 7.827 | 0.4624167045467834 | fail |
| NEOUSDT | 212 | 2.0621 | 0.0097 | 3/6 | 21.2079 | 0.0011 | 8.487 | 0.4674443818850975 | fail |
| SNXUSDT | 211 | -24.1174 | -0.1143 | 1/6 | 30.7164 | -0.0141 | 8.132 | 0.8585563333512962 | fail |
| MANAUSDT | 203 | -18.5479 | -0.0914 | 3/6 | 36.5383 | -0.0123 | 7.439 | 0.7854250592986621 | fail |
| SANDUSDT | 197 | 13.6286 | 0.0692 | 3/6 | 18.5474 | 0.0087 | 7.966 | 0.3010791342547383 | fail |
| **pooled** | 1272 | -19.7139 | -0.0155 | 4/6 | 100.179 (seq) | - | - | 0.6251426162840983 | - |

Holm survivors (alpha 0.05): []

## arm `D55` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| DASHUSDT | 171 | 15.5503 | 0.0909 | 4/6 | 26.1778 | 0.0123 | 7.393 | 0.2821690962876814 | pass |
| ONTUSDT | 170 | 3.4392 | 0.0202 | 4/6 | 13.2081 | 0.0026 | 7.704 | 0.4335676714539619 | pass |
| NEOUSDT | 169 | 5.4186 | 0.0321 | 4/6 | 20.3965 | 0.0041 | 7.836 | 0.4051726966069702 | pass |
| SNXUSDT | 159 | -17.0393 | -0.1072 | 3/6 | 24.6557 | -0.0126 | 8.506 | 0.8219402349638376 | fail |
| MANAUSDT | 150 | -1.3581 | -0.0091 | 2/6 | 16.3596 | -0.0013 | 6.979 | 0.5261165160086487 | fail |
| SANDUSDT | 147 | 37.0357 | 0.2519 | 5/6 | 12.2215 | 0.0299 | 8.426 | 0.06022349509027303 | pass |
| **pooled** | 966 | 43.0466 | 0.0446 | 3/6 | 48.7931 (seq) | - | - | 0.2152537354821319 | - |

Holm survivors (alpha 0.05): []

