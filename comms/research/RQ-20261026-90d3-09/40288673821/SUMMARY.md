# Stage-0 (synthetic leg) -- fade 4h -- fail

FAIL: B: pooled net_r <= 0 or folds short; M15: net_r/trade -0.1735 beats the baseline's -0.0517 by -0.1218 < the 0.05 materiality bar; M25: net_r/trade -0.1162 beats the baseline's -0.0517 by -0.0645 < the 0.05 materiality bar; TRL: pooled net_r <= 0 or folds short. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 553 | -29.0442 | -0.0525 | 2/6 | 94.4426 | None | None | 0.7505820500882512 | fail |
| NEARUSDT | 566 | -24.4731 | -0.0432 | 2/6 | 61.104 | None | None | 0.7038320163064954 | fail |
| ATOMUSDT | 584 | -41.8284 | -0.0716 | 3/6 | 41.2846 | None | None | 0.825012068919968 | fail |
| FILUSDT | 462 | 34.3051 | 0.0743 | 3/6 | 28.2067 | None | None | 0.2081335212272904 | fail |
| TRXUSDT | 558 | -75.0331 | -0.1345 | 2/6 | 33.1699 | None | None | 0.955999960312801 | fail |
| ETCUSDT | 551 | -33.0658 | -0.06 | 1/6 | 50.4278 | None | None | 0.7893029518510243 | fail |
| **pooled** | 3274 | -169.1406 | -0.0517 | 2/6 | 226.9553 (seq) | - | - | 0.9440348056465532 | - |

Holm survivors (alpha 0.05): []

## arm `M15` (candidate) -- fail -- net_r/trade -0.1735 beats the baseline's -0.0517 by -0.1218 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 94 | 1.8785 | 0.02 | 4/6 | 7.2544 | None | None | 0.43621219414749596 | pass |
| NEARUSDT | 113 | -27.9032 | -0.2469 | 0/6 | 23.1579 | None | None | 0.9855920884124376 | fail |
| ATOMUSDT | 106 | -13.0349 | -0.123 | 3/6 | 15.5913 | None | None | 0.8572906140588681 | fail |
| FILUSDT | 82 | -31.6792 | -0.3863 | 0/6 | 30.9215 | None | None | 0.9996037288351832 | fail |
| TRXUSDT | 133 | -16.8337 | -0.1266 | 1/6 | 13.8195 | None | None | 0.9031974143391049 | fail |
| ETCUSDT | 111 | -23.3119 | -0.21 | 1/6 | 20.4816 | None | None | 0.9791435367576189 | fail |
| **pooled** | 639 | -110.8842 | -0.1735 | 0/6 | 116.6259 (seq) | - | - | 0.999939961417308 | - |

Holm survivors (alpha 0.05): []

## arm `M25` (candidate) -- fail -- net_r/trade -0.1162 beats the baseline's -0.0517 by -0.0645 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 417 | -19.01 | -0.0456 | 3/6 | 42.2898 | None | None | 0.7713024011303897 | fail |
| NEARUSDT | 448 | -50.9128 | -0.1136 | 2/6 | 55.0588 | None | None | 0.9689595787071903 | fail |
| ATOMUSDT | 469 | -69.3627 | -0.1479 | 0/6 | 51.6061 | None | None | 0.9955822568707813 | fail |
| FILUSDT | 373 | -27.0765 | -0.0726 | 2/6 | 41.5792 | None | None | 0.8567357881526905 | fail |
| TRXUSDT | 477 | -88.2023 | -0.1849 | 0/6 | 46.4837 | None | None | 0.9995460958834825 | fail |
| ETCUSDT | 435 | -49.6353 | -0.1141 | 1/6 | 35.6803 | None | None | 0.975129271600199 | fail |
| **pooled** | 2619 | -304.2009 | -0.1162 | 0/6 | 322.242 (seq) | - | - | 0.9999990325526169 | - |

Holm survivors (alpha 0.05): []

## arm `TRL` (candidate) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 191 | -7.3505 | -0.0385 | 2/6 | 33.1559 | None | None | 0.5918778617370808 | fail |
| NEARUSDT | 225 | -27.6068 | -0.1227 | 1/6 | 31.2626 | None | None | 0.8452094149487406 | fail |
| ATOMUSDT | 231 | 4.1805 | 0.0181 | 3/6 | 29.3392 | None | None | 0.4616209768460917 | fail |
| FILUSDT | 197 | 42.3094 | 0.2148 | 5/6 | 24.1421 | None | None | 0.12029062171438765 | pass |
| TRXUSDT | 238 | 16.9922 | 0.0714 | 3/6 | 33.5778 | None | None | 0.33245953328002986 | fail |
| ETCUSDT | 209 | -15.3867 | -0.0736 | 2/6 | 40.0603 | None | None | 0.7279942624230112 | fail |
| **pooled** | 1291 | 13.1383 | 0.0102 | 2/6 | 89.429 (seq) | - | - | 0.43791556563395095 | - |

Holm survivors (alpha 0.05): []

