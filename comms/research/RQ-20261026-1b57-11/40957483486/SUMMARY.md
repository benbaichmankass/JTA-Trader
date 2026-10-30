# Stage-0 (synthetic leg) -- trend 2h -- indeterminate

INDETERMINATE: B: pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge; D55: pooled n 4160 < floor 5500: underpowered, never FAIL on thin n. Thresholds: n_floor 39, pooled_n_floor 5500, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled passes but only 5 of 12 powered cells pass (< 6): one symbol's edge

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 795 | -35.9848 | -0.0453 | 1/6 | 58.0423 | -0.0291 | 1.556 | 0.8606237303993627 | fail |
| DOGEUSDT | 726 | 41.4627 | 0.0571 | 3/6 | 34.0637 | 0.037 | 1.544 | 0.12512537463573192 | fail |
| LINKUSDT | 764 | 29.995 | 0.0393 | 3/6 | 31.5513 | 0.0218 | 1.803 | 0.1875523912828187 | fail |
| LTCUSDT | 763 | -89.2279 | -0.1169 | 0/6 | 98.397 | -0.069 | 1.694 | 0.998580820696438 | fail |
| BCHUSDT | 765 | -3.4626 | -0.0045 | 3/6 | 49.5042 | -0.0028 | 1.623 | 0.5375382740722872 | fail |
| DOTUSDT | 737 | 9.5926 | 0.013 | 3/6 | 49.6666 | 0.0074 | 1.758 | 0.3923198770183415 | fail |
| AVAXUSDT | 758 | 16.2457 | 0.0214 | 4/6 | 22.7473 | 0.0131 | 1.639 | 0.3271892373548427 | pass |
| NEARUSDT | 729 | 19.2856 | 0.0265 | 4/6 | 24.5808 | 0.0149 | 1.775 | 0.28377974970065334 | pass |
| ATOMUSDT | 772 | 6.9733 | 0.009 | 3/6 | 30.2056 | 0.0052 | 1.751 | 0.4208286580873323 | fail |
| FILUSDT | 662 | 110.5461 | 0.167 | 6/6 | 18.7379 | 0.0939 | 1.778 | 0.0010932999046023438 | pass |
| TRXUSDT | 803 | 47.4674 | 0.0591 | 4/6 | 31.8177 | 0.0372 | 1.59 | 0.1150855588591489 | pass |
| ETCUSDT | 763 | 41.8062 | 0.0548 | 5/6 | 22.0934 | 0.0355 | 1.544 | 0.13541853418796934 | pass |
| **pooled** | 9037 | 194.6991 | 0.0215 | 4/6 | 126.3962 (seq) | - | - | 0.05592069117789278 | - |

Holm survivors (alpha 0.05): ['FILUSDT']

## arm `D55` (candidate) -- indeterminate -- pooled n 4160 < floor 5500: underpowered, never FAIL on thin n

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 362 | -4.292 | -0.0119 | 3/6 | 41.3384 | -0.0036 | 3.322 | 0.5443589511972285 | fail |
| DOGEUSDT | 332 | 39.9315 | 0.1203 | 4/6 | 29.3192 | 0.0386 | 3.118 | 0.13749429693304271 | pass |
| LINKUSDT | 369 | -32.0175 | -0.0868 | 2/6 | 46.4379 | -0.0245 | 3.538 | 0.8286683306865086 | fail |
| LTCUSDT | 339 | -49.9351 | -0.1473 | 2/6 | 81.5274 | -0.039 | 3.772 | 0.9509861393071174 | fail |
| BCHUSDT | 332 | 34.2445 | 0.1031 | 5/6 | 30.1737 | 0.0279 | 3.703 | 0.18856959529232425 | pass |
| DOTUSDT | 325 | 0.6206 | 0.0019 | 4/6 | 32.8821 | 0.0004 | 4.261 | 0.4924636791437696 | pass |
| AVAXUSDT | 335 | 19.6539 | 0.0587 | 4/6 | 24.6501 | 0.0158 | 3.703 | 0.2967705695873314 | pass |
| NEARUSDT | 346 | -9.2566 | -0.0268 | 2/6 | 24.7893 | -0.0072 | 3.72 | 0.6096114648311401 | fail |
| ATOMUSDT | 352 | -29.3626 | -0.0834 | 1/6 | 63.0919 | -0.0212 | 3.942 | 0.8083944108771133 | fail |
| FILUSDT | 327 | 9.7802 | 0.0299 | 2/6 | 52.3614 | 0.0093 | 3.214 | 0.3927333359657903 | fail |
| TRXUSDT | 385 | -4.7414 | -0.0123 | 2/6 | 40.632 | -0.0041 | 3.008 | 0.550442972066038 | fail |
| ETCUSDT | 356 | 0.4084 | 0.0011 | 2/6 | 68.3398 | 0.0004 | 3.141 | 0.4955934291531617 | fail |
| **pooled** | 4160 | -24.9669 | -0.006 | 3/6 | 286.819 (seq) | - | - | 0.5805966419117787 | - |

Holm survivors (alpha 0.05): []

