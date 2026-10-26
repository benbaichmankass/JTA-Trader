| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2948 | 0.5 | 0.9209 | 0.13471 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.0088 | 0.8693 | -0.03479 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1933 | 0.8429 | 0.01595 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0268 | 0.8385 | -0.02599 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-15m-lgbm-fc-pcv-v1 | SOLUSDT/15m | 19367 | 0.0959 | 0.8382 | 0.01494 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-yz-v1 | BTCUSDT/5m | 30023 | 0.0016 | 0.8371 | -0.00311 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0048 | 0.8315 | -0.02287 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1933 | 0.83 | 0.01925 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0268 | 0.8227 | -0.02991 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0016 | 0.8133 | -0.00328 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3361 | 0.803 | -0.01079 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-fc-pcv-v1 | BTCUSDT/15m | 18791 | 0.0374 | 0.7863 | 0.00136 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 20615 | 0.2276 | 0.7836 | -0.20943 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0016 | 0.7797 | -4e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3361 | 0.7266 | 0.01292 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.4413 | 0.7164 | 0.02986 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 18791 | 0.0374 | 0.7159 | 0.00081 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 20615 | 0.2276 | 0.7133 | 0.01013 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 15737 | 0.3923 | 0.6477 | 0.01738 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
