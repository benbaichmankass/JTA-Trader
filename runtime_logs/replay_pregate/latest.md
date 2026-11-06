| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2956 | 0.5 | 0.9181 | 0.13334 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.0098 | 0.8589 | -0.03777 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1941 | 0.8444 | 0.01746 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0052 | 0.8383 | -0.02452 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0264 | 0.8373 | -0.02522 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-15m-lgbm-fc-pcv-v1 | SOLUSDT/15m | 18215 | 0.0965 | 0.8341 | 0.01434 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-yz-v1 | BTCUSDT/5m | 30023 | 0.0018 | 0.8327 | -0.00332 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1941 | 0.8315 | 0.0191 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0264 | 0.8226 | -0.02847 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0018 | 0.8097 | -0.00347 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3373 | 0.8008 | -0.01627 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-fc-pcv-v1 | BTCUSDT/15m | 17735 | 0.0376 | 0.786 | 0.00138 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0018 | 0.783 | -4e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 19463 | 0.2304 | 0.7798 | -0.21003 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 17735 | 0.0376 | 0.7175 | 0.00084 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3373 | 0.7114 | 0.02613 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 19463 | 0.2304 | 0.7106 | 0.00993 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.3036 | 0.6746 | 0.00728 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 16823 | 0.3032 | 0.6088 | 0.0067 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
