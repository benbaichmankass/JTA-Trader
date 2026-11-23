| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2968 | 0.5 | 0.9182 | 0.13296 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1964 | 0.8388 | 0.01417 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.013 | 0.8335 | -0.05439 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1964 | 0.8268 | 0.01591 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0088 | 0.8215 | -0.03755 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0297 | 0.8196 | -0.02203 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0297 | 0.8067 | -0.02865 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3408 | 0.802 | -0.01822 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 17927 | 0.2395 | 0.7764 | -0.21011 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.003 | 0.7664 | -3e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.003 | 0.76 | -0.00453 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3408 | 0.7244 | 0.01798 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 16103 | 0.0408 | 0.7121 | 0.00098 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 17927 | 0.2395 | 0.7031 | 0.00974 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.3296 | 0.6865 | 0.00495 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 17619 | 0.3231 | 0.6056 | 0.00522 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
