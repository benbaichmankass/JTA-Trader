| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2964 | 0.5 | 0.9166 | 0.13233 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1952 | 0.8424 | 0.01871 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.012 | 0.8395 | -0.04816 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1952 | 0.8292 | 0.01783 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0072 | 0.8244 | -0.03208 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0282 | 0.8226 | -0.01929 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0282 | 0.8067 | -0.0279 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3392 | 0.8047 | -0.01649 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0021 | 0.7954 | -0.00381 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 18311 | 0.2366 | 0.7786 | -0.20884 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0021 | 0.76 | -5e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3392 | 0.7139 | 0.02375 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 16583 | 0.0402 | 0.7098 | 0.00091 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 18311 | 0.2366 | 0.7065 | 0.01004 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.3245 | 0.6747 | 0.00413 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 17466 | 0.3107 | 0.6121 | 0.00662 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
