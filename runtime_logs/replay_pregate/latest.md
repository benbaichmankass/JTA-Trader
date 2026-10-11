| Model | Sym/TF | n | base | AUC | brier_lift | Verdict |
|---|---|---:|---:|---:|---:|---|
| mes-regime-1d-lgbm-v2 | MES/1d | 2937 | 0.4998 | 0.9221 | 0.13539 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-lgbm-v2 | MES/15m | 15071 | 0.3798 | 0.8804 | 0.09398 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-yz-v1 | BTCUSDT/5m | 30023 | 0.0013 | 0.8692 | -0.00365 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-5m-lgbm-v1 | SOLUSDT/5m | 30023 | 0.0092 | 0.8609 | -0.03425 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-yz-v1 | BTCUSDT/1h | 30023 | 0.1938 | 0.8444 | 0.01446 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-yz-v1 | BTCUSDT/15m | 30023 | 0.0279 | 0.8403 | -0.03367 | 🟢 TRUSTWORTHY_SIGNAL |
| sol-regime-15m-lgbm-fc-pcv-v1 | SOLUSDT/15m | 20711 | 0.0961 | 0.837 | 0.01463 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-lgbm-v2 | BTCUSDT/5m | 30023 | 0.0013 | 0.8351 | -0.00372 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-1h-lgbm-v2 | BTCUSDT/1h | 30023 | 0.1938 | 0.831 | 0.01665 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-v2 | BTCUSDT/15m | 30023 | 0.0279 | 0.8282 | -0.03332 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-5m-baseline-v1 | BTCUSDT/5m | 30023 | 0.0013 | 0.8226 | -4e-05 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-v1 | ETHUSDT/1h | 30023 | 0.3355 | 0.8025 | -0.01032 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-selfonly-v901ctrl | ETHUSDT/15m | 21959 | 0.2314 | 0.7854 | -0.20779 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-lgbm-fc-pcv-v1 | BTCUSDT/15m | 20231 | 0.037 | 0.7819 | 0.00125 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-1h-lgbm-xasset-v1 | ETHUSDT/1h | 30023 | 0.3355 | 0.7161 | 0.00994 | 🟢 TRUSTWORTHY_SIGNAL |
| eth-regime-15m-lgbm-xasset-v1 | ETHUSDT/15m | 21959 | 0.2314 | 0.716 | 0.01174 | 🟢 TRUSTWORTHY_SIGNAL |
| btc-regime-15m-baseline-v1 | BTCUSDT/15m | 20231 | 0.037 | 0.711 | 0.00072 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-5m-baseline-v1 | MES/5m | 30023 | 0.4207 | 0.7077 | 0.02834 | 🟢 TRUSTWORTHY_SIGNAL |
| mes-regime-15m-baseline-v1 | MES/15m | 15071 | 0.3798 | 0.6487 | 0.01715 | 🟢 TRUSTWORTHY_SIGNAL |

**Errors:**
- `eth-regime-5m-lgbm-v1`: Unterminated string starting at: line 1 column 1241 (char 1240)

_🟢 AUC≥0.55 (discriminates) · 🟡 0.45–0.55 (no edge) · 🔴 <0.45 (anti-predictive). A head that fails here should not earn a live-shadow slot; one already shadow-soaking that scores 🔴 is a demotion candidate._
