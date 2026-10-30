# HARNESS-TRAIL-GAPFILL re-check (2026-10-30)

scripts/backtest_trend.py: stop/TP touched on a bar that opens beyond the level fills at the OPEN (cf_core rule)

Population: all 21 measured harness=trend records in comms/strategy_evidence/ rebuilt by scripts/ops/build_strategy_evidence.py (default 1095d, 4 folds) with the OLD and NEW harness on the SAME data fetched 2026-10-30; rule RULE-D1-STAGE0-NET-OF-FULL-COST (net_r_oos > 0, full cost stack as recorded per leg)

True-open parity on corpus v1 (2,627 trades): old harness 2371/2627 match cf_core (mean gap -0.0292 R); new harness 2627/2627.

**Caveat:** The OLD-harness rebuild today does NOT reproduce the committed 2026-10-28 records (e.g. trend_donchian_eth_4h n 135 committed vs 51 rebuilt; net_r_oos +44.6 vs -9.6). Cause not established here (fetch window / feed / fold differences); the old-vs-new columns are the like-for-like effect of the change, the committed column is context only. Committed records are NOT overwritten.

| leg | cost stack (bps) | n old/new | net R old | net R new | R/trade old | R/trade new | verdict committed | old (today) | new (today) |
|---|---|---|---|---|---|---|---|---|---|
| iwm_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 7/7 | 2.8159 | 2.5318 | 0.4023 | 0.3617 | pass | pass | pass |
| mes_trend_long_1d | fee 7.5/slip 5.0/fund 0.0 | 5/5 | -1.2284 | -1.2284 | -0.2457 | -0.2457 | fail | fail | fail |
| mgc_trend_1h | fee 7.5/slip 5.0/fund 0.0 | 125/125 | 11.6418 | 11.906 | 0.0931 | 0.0952 | pass | pass | pass |
| qld_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 9/9 | -0.3158 | -0.3038 | -0.0351 | -0.0338 | pass | fail | fail |
| qqq_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 9/9 | -0.6002 | -0.711 | -0.0667 | -0.079 | pass | fail | fail |
| scha_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 6/6 | 0.4075 | 0.4471 | 0.0679 | 0.0745 | pass | pass | pass |
| slv_trend_1h | fee 0.0/slip 5.0/fund 0.0 | 67/67 | 59.9577 | 51.6319 | 0.8949 | 0.7706 | pass | pass | pass |
| spy_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 10/10 | 0.5125 | -0.1353 | 0.0513 | -0.0135 | pass | pass | fail |
| tqqq_trend_long_1d | fee 0.0/slip 5.0/fund 0.0 | 11/11 | -2.2319 | -2.1296 | -0.2029 | -0.1936 | pass | fail | fail |
| trend_donchian | fee 11.0/slip 3.0/fund 1.0 | 71/71 | -16.226 | -18.7447 | -0.2285 | -0.264 | fail | fail | fail |
| trend_donchian_ada_4h | fee 11.0/slip 3.0/fund 1.0 | 43/43 | -9.7604 | -9.7604 | -0.227 | -0.227 | fail | fail | fail |
| trend_donchian_avax_4h | fee 11.0/slip 3.0/fund 1.0 | 46/46 | -10.9364 | -12.4253 | -0.2377 | -0.2701 | fail | fail | fail |
| trend_donchian_eth | fee 11.0/slip 3.0/fund 1.0 | 108/108 | 7.9811 | 7.9811 | 0.0739 | 0.0739 | pass | pass | pass |
| trend_donchian_eth_4h | fee 11.0/slip 3.0/fund 1.0 | 51/51 | -9.5664 | -12.4271 | -0.1876 | -0.2437 | pass | fail | fail |
| trend_donchian_eth_prop | fee 11.0/slip 3.0/fund 1.0 | 165/165 | 0.4354 | -4.115 | 0.0026 | -0.0249 | fail | pass | fail |
| trend_donchian_sol | fee 11.0/slip 3.0/fund 1.0 | 58/58 | -2.8779 | -2.8779 | -0.0496 | -0.0496 | fail | fail | fail |
| trend_donchian_sol_4h | fee 11.0/slip 3.0/fund 1.0 | 33/33 | -4.7902 | -4.7902 | -0.1452 | -0.1452 | pass | fail | fail |
| trend_donchian_sol_prop | fee 11.0/slip 3.0/fund 1.0 | 63/63 | -1.9989 | -1.9989 | -0.0317 | -0.0317 | pass | fail | fail |
| trend_donchian_xrp_4h | fee 11.0/slip 3.0/fund 1.0 | 14/14 | 3.4812 | 3.4812 | 0.2487 | 0.2487 | pass | pass | pass |
| trend_donchian_xrp_adx25 | fee 11.0/slip 3.0/fund 1.0 | 14/14 | 4.5946 | 4.5946 | 0.3282 | 0.3282 | pass | pass | pass |
| uso_trend_1h | fee 0.0/slip 5.0/fund 0.0 | 56/56 | 25.1575 | 28.0108 | 0.4492 | 0.5002 | pass | pass | pass |

Pass->fail flips old->new on identical data: spy_trend_long_1d, trend_donchian_eth_prop.
