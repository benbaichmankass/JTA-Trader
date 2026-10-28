# Stage-0 (synthetic leg) -- trend 1w -- indeterminate

INDETERMINATE: W10: pooled net_r <= 0 or folds short; W20: only 1 powered cell(s) (< 2): breadth cannot be read. Thresholds: n_floor 10, pooled_n_floor 39, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `W10` (arm) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 12 | 5.6563 | 0.4714 | 3/6 | 3.3064 | 0.0048 | 99.169 | 0.2683843007071005 | fail |
| DOGEUSDT | 6 | -1.5774 | -0.2629 | 1/6 | 2.8389 | -0.0009 | 290.5 | 0.7245072307523986 | indeterminate |
| LINKUSDT | 10 | -4.8794 | -0.4879 | 1/6 | 6.1805 | -0.0035 | 139.3 | 0.9788014470770511 | fail |
| LTCUSDT | 7 | -0.1459 | -0.0208 | 2/6 | 3.1518 | -0.0001 | 266.0 | 0.516068220021448 | indeterminate |
| BCHUSDT | 10 | -3.443 | -0.3443 | 1/6 | 6.0546 | -0.0023 | 149.8 | 0.8572869832103227 | fail |
| DOTUSDT | 6 | -1.267 | -0.2112 | 1/6 | 2.5434 | -0.0007 | 305.669 | 0.7476025774705821 | indeterminate |
| **pooled** | 51 | -5.6567 | -0.1109 | 1/6 | 21.3661 (seq) | - | - | 0.7033740767871244 | - |

Holm survivors (alpha 0.05): []

## arm `W20` (arm) -- indeterminate -- only 1 powered cell(s) (< 2): breadth cannot be read

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| BNBUSDT | 12 | 5.5049 | 0.4587 | 3/6 | 3.4579 | 0.0053 | 85.75 | 0.2741049472429622 | fail |
| DOGEUSDT | 9 | -2.8174 | -0.313 | 1/6 | 4.7483 | -0.0047 | 66.108 | 0.7082766671864525 | indeterminate |
| LINKUSDT | 8 | -3.7533 | -0.4692 | 1/6 | 4.1381 | -0.0037 | 126.0 | 0.9898956482176722 | indeterminate |
| LTCUSDT | 7 | -3.3669 | -0.481 | 1/6 | 4.0717 | -0.0021 | 234.003 | 0.944422744014295 | indeterminate |
| BCHUSDT | 8 | -2.4689 | -0.3086 | 2/6 | 3.2585 | -0.0022 | 143.5 | 0.9289697441876433 | indeterminate |
| DOTUSDT | 4 | -1.7906 | -0.4476 | 0/6 | 1.7906 | -0.0011 | 404.25 | 0.8612032389092568 | indeterminate |
| **pooled** | 48 | -8.6924 | -0.1811 | 2/6 | 17.6287 (seq) | - | - | 0.7936997369059644 | - |

Holm survivors (alpha 0.05): []

