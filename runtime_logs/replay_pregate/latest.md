| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2948 | 0.5 | 0.9209 | 0.13471 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.0086 | 0.8679 | -0.03488 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1933 | 0.8441 | 0.01842 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-yz-v1 | BTCUSDT/5m | 30023 | 0.0016 | 0.8405 | -0.00298 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0265 | 0.8399 | -0.02584 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-15m-lgbm-fc-pcv-v1 | SOLUSDT/15m | 19175 | 0.0951 | 0.8369 | 0.01457 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1933 | 0.8306 | 0.01968 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0047 | 0.8283 | -0.022 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0265 | 0.8239 | -0.02874 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0016 | 0.8178 | -0.00343 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3362 | 0.8028 | -0.01185 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-fc-pcv-v1 | BTCUSDT/15m | 18695 | 0.0371 | 0.7873 | 0.00136 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 20423 | 0.227 | 0.7823 | -0.20958 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0016 | 0.7793 | -4e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3362 | 0.7369 | 0.03394 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 18695 | 0.0371 | 0.717 | 0.00081 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.4414 | 0.7167 | 0.02992 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 20423 | 0.227 | 0.7141 | 0.01017 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 15788 | 0.3914 | 0.6493 | 0.01777 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
