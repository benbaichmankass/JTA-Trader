# Stage-0 (synthetic leg) -- trend 2h -- fail

FAIL: B: pooled net_r <= 0 or folds short; D40: net_r/trade -0.0026 beats the baseline's -0.0075 by 0.0049 < the 0.05 materiality bar; D40A: net_r/trade -0.0177 beats the baseline's -0.0075 by -0.0102 < the 0.05 materiality bar; LONG: net_r/trade -0.033 beats the baseline's -0.0075 by -0.0255 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 793 | -22.8321 | -0.0288 | 1/6 | 47.0946 | -0.0185 | 1.558 | 0.7541714227285778 | fail |
| LINKUSDT | 763 | 28.969 | 0.038 | 3/6 | 31.5513 | 0.0211 | 1.8 | 0.19558698281424847 | fail |
| LTCUSDT | 762 | -88.9585 | -0.1167 | 0/6 | 98.397 | -0.0689 | 1.695 | 0.9985441765119937 | fail |
| BCHUSDT | 763 | -1.2144 | -0.0016 | 3/6 | 49.5042 | -0.001 | 1.625 | 0.5131754580960131 | fail |
| DOTUSDT | 736 | 9.1001 | 0.0124 | 3/6 | 49.6666 | 0.007 | 1.757 | 0.39767890972308556 | fail |
| DOGEUSDT | 725 | 40.8638 | 0.0564 | 3/6 | 34.0637 | 0.0365 | 1.543 | 0.1285495553570163 | fail |
| **pooled** | 4542 | -34.0695 | -0.0075 | 3/6 | 175.3338 (seq) | - | - | 0.657954173372133 | - |

Holm survivors (alpha 0.05): []

## arm `D40` (candidate) -- fail -- net_r/trade -0.0026 beats the baseline's -0.0075 by 0.0049 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 601 | -11.5591 | -0.0192 | 2/6 | 40.4437 | -0.0133 | 1.443 | 0.6566036103987223 | fail |
| LINKUSDT | 613 | -7.5062 | -0.0122 | 3/6 | 40.4654 | -0.0076 | 1.613 | 0.5980860577030708 | fail |
| LTCUSDT | 583 | -70.6125 | -0.1211 | 1/6 | 75.4732 | -0.0759 | 1.596 | 0.9970510624498359 | fail |
| BCHUSDT | 556 | 37.4932 | 0.0674 | 5/6 | 33.4663 | 0.0424 | 1.591 | 0.12205295826667256 | pass |
| DOTUSDT | 574 | 14.7568 | 0.0257 | 2/6 | 40.4155 | 0.015 | 1.712 | 0.32420324695306746 | fail |
| DOGEUSDT | 536 | 28.4632 | 0.0531 | 4/6 | 17.891 | 0.041 | 1.295 | 0.1840879697334638 | pass |
| **pooled** | 3463 | -8.9649 | -0.0026 | 3/6 | 114.7008 (seq) | - | - | 0.5482330125376903 | - |

Holm survivors (alpha 0.05): []

## arm `D40A` (candidate) -- fail -- net_r/trade -0.0177 beats the baseline's -0.0075 by -0.0102 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 490 | -32.4697 | -0.0663 | 1/6 | 44.6558 | -0.0464 | 1.427 | 0.9005354942461593 | fail |
| LINKUSDT | 519 | -26.4901 | -0.051 | 2/6 | 43.2182 | -0.0321 | 1.589 | 0.8296683352308953 | fail |
| LTCUSDT | 464 | -67.2302 | -0.1449 | 1/6 | 69.3857 | -0.0885 | 1.638 | 0.9984848922614076 | fail |
| BCHUSDT | 440 | 34.9555 | 0.0794 | 5/6 | 26.2724 | 0.045 | 1.764 | 0.11522572748140736 | pass |
| DOTUSDT | 477 | -4.6648 | -0.0098 | 3/6 | 35.1185 | -0.006 | 1.617 | 0.5660744451327593 | fail |
| DOGEUSDT | 441 | 45.756 | 0.1038 | 5/6 | 14.7885 | 0.0823 | 1.26 | 0.06306618445477585 | pass |
| **pooled** | 2831 | -50.1443 | -0.0177 | 2/6 | 112.434 (seq) | - | - | 0.773768234008628 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade -0.033 beats the baseline's -0.0075 by -0.0255 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 467 | 5.369 | 0.0115 | 1/6 | 34.9712 | 0.0072 | 1.605 | 0.4154435700659791 | fail |
| LINKUSDT | 468 | -9.1158 | -0.0195 | 2/6 | 35.5027 | -0.0122 | 1.591 | 0.6502658947587799 | fail |
| LTCUSDT | 460 | -49.2735 | -0.1071 | 2/6 | 63.3321 | -0.0663 | 1.615 | 0.9833160872399446 | fail |
| BCHUSDT | 446 | -13.6684 | -0.0306 | 3/6 | 36.1869 | -0.0215 | 1.428 | 0.6971148881151729 | fail |
| DOTUSDT | 450 | -27.714 | -0.0616 | 3/6 | 61.4188 | -0.0417 | 1.476 | 0.8622349703167884 | fail |
| DOGEUSDT | 433 | 4.524 | 0.0104 | 2/6 | 40.9331 | 0.0084 | 1.25 | 0.4345019800853819 | fail |
| **pooled** | 2724 | -89.8803 | -0.033 | 2/6 | 210.9294 (seq) | - | - | 0.9271315929725019 | - |

Holm survivors (alpha 0.05): []

