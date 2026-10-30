| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2951 | 0.4998 | 0.9182 | 0.13304 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.0086 | 0.8664 | -0.03382 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-yz-v1 | BTCUSDT/5m | 30023 | 0.0017 | 0.8595 | -0.00332 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1937 | 0.8431 | 0.01918 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.026 | 0.839 | -0.02652 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-5m-lgbm-v1 | ETHUSDT/5m | 30023 | 0.0045 | 0.8381 | -0.02171 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-15m-lgbm-fc-pcv-v1 | SOLUSDT/15m | 18983 | 0.0937 | 0.8347 | 0.0137 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1937 | 0.83 | 0.01851 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.026 | 0.8189 | -0.02978 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0017 | 0.8156 | -0.00357 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3366 | 0.8026 | -0.01336 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0017 | 0.7904 | -3e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-fc-pcv-v1 | BTCUSDT/15m | 18407 | 0.0365 | 0.7862 | 0.00129 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 20231 | 0.2255 | 0.7811 | -0.21068 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3366 | 0.7262 | 0.03002 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.4483 | 0.7186 | 0.02986 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 18407 | 0.0365 | 0.7168 | 0.00078 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 20231 | 0.2255 | 0.7141 | 0.00976 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 16064 | 0.3934 | 0.6487 | 0.01773 | 🟢 TRUSTWORTHY_SIGNAL |

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
