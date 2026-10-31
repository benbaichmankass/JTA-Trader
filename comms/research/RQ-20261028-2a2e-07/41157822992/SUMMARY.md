# Stage-0 (synthetic leg) -- pullback 1h -- fail

FAIL: B: pooled net_r <= 0 or folds short; BE1: net_r/trade 0.0118 beats the baseline's 0.0389 by -0.0271 < the 0.05 materiality bar; LONG: net_r/trade -0.0226 beats the baseline's 0.0389 by -0.0615 < the 0.05 materiality bar. Thresholds: n_floor 39, pooled_n_floor 88, folds 6 majority 4, breadth 0.5 over >= 2 powered cells, holm alpha 0.05, baseline B with materiality 0.05 R/trade. Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware fee + slippage + funding. A pass is an input to a re-entry case, never a roster act.

## arm `B` (baseline) -- fail -- pooled net_r <= 0 or folds short

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 800 | 55.1556 | 0.0689 | 4/6 | 37.9307 | 0.0319 | 2.16 | 0.14409874711376136 | pass |
| NEARUSDT | 767 | 58.2473 | 0.0759 | 4/6 | 38.8624 | 0.0341 | 2.23 | 0.11486228733833809 | pass |
| ATOMUSDT | 829 | 9.6583 | 0.0117 | 3/6 | 27.4472 | 0.0053 | 2.196 | 0.420284638927266 | fail |
| FILUSDT | 807 | 47.2099 | 0.0585 | 3/6 | 41.6521 | 0.0272 | 2.147 | 0.18138178934397786 | fail |
| TRXUSDT | 856 | 17.2782 | 0.0202 | 3/6 | 50.6115 | 0.0098 | 2.069 | 0.378364079079731 | fail |
| ETCUSDT | 861 | 3.7176 | 0.0043 | 4/6 | 76.178 | 0.002 | 2.111 | 0.4715297475513204 | pass |
| **pooled** | 4920 | 191.2638 | 0.0389 | 3/6 | 153.7621 (seq) | - | - | 0.06430608905291002 | - |

Holm survivors (alpha 0.05): []

## arm `BE1` (candidate) -- fail -- net_r/trade 0.0118 beats the baseline's 0.0389 by -0.0271 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 928 | 27.2407 | 0.0294 | 4/6 | 31.5832 | 0.0164 | 1.787 | 0.3001234607797353 | pass |
| NEARUSDT | 881 | 63.8901 | 0.0725 | 5/6 | 22.5674 | 0.0391 | 1.855 | 0.08890195358484582 | pass |
| ATOMUSDT | 971 | -34.6328 | -0.0357 | 2/6 | 43.4378 | -0.02 | 1.78 | 0.7715879112479211 | fail |
| FILUSDT | 896 | 44.4314 | 0.0496 | 3/6 | 52.1093 | 0.0265 | 1.87 | 0.18817803619324336 | fail |
| TRXUSDT | 973 | -33.9266 | -0.0349 | 3/6 | 50.5364 | -0.02 | 1.741 | 0.739116305054746 | fail |
| ETCUSDT | 989 | -0.5676 | -0.0006 | 3/6 | 68.0411 | -0.0003 | 1.761 | 0.5043615947609885 | fail |
| **pooled** | 5638 | 66.4338 | 0.0118 | 3/6 | 199.1605 (seq) | - | - | 0.2945521855670826 | - |

Holm survivors (alpha 0.05): []

## arm `LONG` (candidate) -- fail -- net_r/trade -0.0226 beats the baseline's 0.0389 by -0.0615 < the 0.05 materiality bar

| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| AVAXUSDT | 541 | -38.9092 | -0.0719 | 4/6 | 68.7058 | -0.0404 | 1.781 | 0.8592879735191126 | fail |
| NEARUSDT | 521 | 40.5305 | 0.0778 | 4/6 | 38.2214 | 0.0403 | 1.929 | 0.15700520837876925 | pass |
| ATOMUSDT | 568 | -87.8781 | -0.1547 | 1/6 | 101.3956 | -0.0833 | 1.858 | 0.9913042507668135 | fail |
| FILUSDT | 567 | 13.3364 | 0.0235 | 3/6 | 51.1648 | 0.0133 | 1.763 | 0.37848827705929483 | fail |
| TRXUSDT | 589 | 105.0772 | 0.1784 | 5/6 | 28.6732 | 0.0918 | 1.943 | 0.018994546003815387 | pass |
| ETCUSDT | 648 | -109.6741 | -0.1693 | 1/6 | 123.512 | -0.1019 | 1.662 | 0.9965626331847012 | fail |
| **pooled** | 3434 | -77.5177 | -0.0226 | 3/6 | 233.8613 (seq) | - | - | 0.7768009651103319 | - |

Holm survivors (alpha 0.05): []

