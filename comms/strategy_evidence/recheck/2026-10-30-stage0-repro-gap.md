# STAGE0-REPRO-GAP: why the 2026-10-30 trend rebuild "did not reproduce", and re-issued verdicts

Lane STAGE0-REPRO-GAP (dispatched by Manager Session 2026-10-30c). Row `STAGE0-REPRO-GAP`; closes `PI-20261030-56Z4JYMX-0001`. Data in `2026-10-30-stage0-repro-gap.json`.

**Population.** All 22 `harness: trend` records in `comms/strategy_evidence/`. Each was rebuilt with `scripts/ops/build_strategy_evidence.py` at **its own `window_days`** with 4 folds, on candles fetched 2026-10-30 (Binance-vision for `*USDT`, Yahoo otherwise). It was run twice on the same fetched CSV: once with the **old** harness (`main`) and once with the **gap-fixed** harness from PR #21628 (`lane/harness-trail-gapfill`, not merged). Rule: `RULE-D1-STAGE0-NET-OF-FULL-COST` (net_r_oos > 0), using the cost stack each record names.

## Cause (MEASURED, reproduced)

1. **Wrong window, not wrong code.** The HARNESS-TRAIL-GAPFILL re-check rebuilt every record at the builder's **default `--days 365`**. Its population line says "default 1095d", but `DEFAULT_DAYS = 365`. Seven records were measured at a longer window: eth_4h and sol_4h at 1095d, sol_prop at 2170d, xrp_4h and xrp_adx25 at 1460d, tqqq and scha at 6200d. At their own window, the old harness rebuilt today reproduces **every one of the seven to the 4th decimal** (eth_4h 135 / +44.6385, sol_prop 395 / +48.0322, sol_4h 116 / +36.8572, xrp_4h 46 / +7.712, tqqq 118 / +26.2831, …). The 3–6× drop in n was exactly the shorter window.
2. **Rolling window.** A 365d record is "the last 365 days before the run", so it moves every day. Replayed on its committed `data_start..data_end`, it reproduces exactly: eth_prop 165 / −0.252, ada_4h 43 / −6.3444, qqq 8 / +5.2971, spy 11 / +2.3816. qld/qqq/tqqq "pass → fail" decomposes into tqqq (cause 1: 6200d) and qld/qqq (cause 2: 2026-09-24 records whose window has rolled about 5 weeks).
3. **Ruled out.** Config drift: `config_fingerprint` matches `config/strategies.yaml` for all 22. Cost stack: unchanged (Bybit linear 11/3/1 bps; equities 0/5/0). Fold basis: unchanged.
4. **Residual, not explained.** mgc_trend_1h (paper only) replays its pinned window with the same n (118) but net +25.24 vs +25.61. It is paper-only, and its verdict is pass on both. Noted here, not filed.
5. **Yahoo is not same-day deterministic.** spy at 365d read +0.51 in the gap-fill lane's run and −0.34 in this lane's run hours later, most likely because the still-forming daily bar moved. A pinned-window replay removes this.

## Re-issued verdicts: real-money / prop trend legs

Rosters are re-parsed from `config/accounts.yaml` on 2026-10-30. Each row gives the full cost stack, n, and net R.

| leg | real-money / prop accounts | basis | old harness | gap-fixed harness | verdict (gap-fixed) |
|---|---|---|---|---|---|
| trend_donchian_eth_4h | bybit_2, bybit_portfolio | D1, 1095d, closed bar | 135 / +44.64 | 135 / +28.95 | **pass** |
| trend_donchian_eth_4h | ″ | D1, forming bar (the bar it trades), record window, 1m proxy, 11 bps | 209 / +48.23 | 209 / +25.08 | **pass** |
| trend_donchian_sol_prop | bybit_2, bybit_portfolio | D1, 2170d, closed bar | 395 / +48.03 | 395 / +47.57 | **pass** |
| trend_donchian_sol_prop | ″ | D1, forming bar, record window, 11 bps | 575 / +34.64 | 575 / +33.69 | **pass** |
| trend_donchian_xrp_4h | bybit_2, bybit_portfolio | D1, 1460d (decision_bar: closed) | 46 / +7.71 | 46 / +7.71 | **pass** |
| trend_donchian_eth_prop | breakout_2, tradeify_1, velotrade_1 (prop) | D1, 365d (record window) | 165 / −0.25 (committed: fail) | 165 / −4.12 (today's window) | **fail** |
| trend_donchian_eth_prop | ″ | RULE-WF-RECOST-trend_donchian_eth_prop (RQ-20261028-dda7-03: 1095d, 6 folds, n≥88, net>0, ex-max-fold>0, ≥4/6 folds +) | 516 / +29.13, 4/6, ex-max +13.35 → PASS (reproduces the 2026-10-28 grade, n 515 / +29.12) | 516 / +2.32, 3/6, ex-max −7.30 | **FAIL** |

**Live-money reading.** eth_4h, sol_prop and xrp_4h still clear Stage 0 under the gap-fixed harness. The two forming legs also clear it on the bar they actually trade. **eth_prop fails** under the gap-fixed harness on both its D1 record and its pre-registered multi-window rule. With the old harness it passes only the multi-window rule.

## All 22 trend records (D1, own window, closed bar)

| leg | real-money / prop rosters | days | committed n / net / v | lane 365d old n / net | old rebuilt n / net / v | gap-fixed n / net / v | reproduces |
|---|---|---|---|---|---|---|---|
| iwm_trend_long_1d | — (paper/demo only) | 365 | 8 / +2.11 / pass | 7 / +2.82 | 7 / +2.82 / pass | 7 / +2.53 / pass | no |
| mes_trend_long_1d | — (paper/demo only) | 365 | 5 / -1.00 / fail | 5 / -1.23 | 5 / -1.23 / fail | 5 / -1.23 / fail | no |
| mgc_trend_1h | — (paper/demo only) | 365 | 118 / +25.61 / pass | 125 / +11.64 | 125 / +13.04 / pass | 125 / +13.31 / pass | no |
| qld_trend_long_1d | — (paper/demo only) | 365 | 9 / +2.98 / pass | 9 / -0.32 | 9 / -0.32 / fail | 9 / -0.30 / fail | no |
| qqq_trend_long_1d | — (paper/demo only) | 365 | 8 / +5.30 / pass | 9 / -0.60 | 9 / -0.60 / fail | 9 / -0.71 / fail | no |
| scha_trend_long_1d | — (paper/demo only) | 6200 | 78 / +4.64 / pass | 6 / +0.41 | 78 / +4.64 / pass | 78 / +4.70 / pass | yes |
| slv_trend_1h | — (paper/demo only) | 365 | 68 / +53.14 / pass | 67 / +59.96 | 67 / +63.13 / pass | 67 / +54.80 / pass | no |
| splg_trend_long_1d | — (paper/demo only) | 365 | — / — / — | — / — | 7 / -0.48 / fail | 7 / -0.76 / fail | no |
| spy_trend_long_1d | — (paper/demo only) | 365 | 11 / +2.38 / pass | 10 / +0.51 | 10 / -0.34 / fail | 10 / -0.74 / fail | no |
| tqqq_trend_long_1d | — (paper/demo only) | 6200 | 118 / +26.28 / pass | 11 / -2.23 | 118 / +26.28 / pass | 118 / +27.02 / pass | yes |
| trend_donchian | — (paper/demo only) | 365 | 71 / -16.23 / fail | 71 / -16.23 | 71 / -16.23 / fail | 71 / -18.74 / fail | yes |
| trend_donchian_ada_4h | — (paper/demo only) | 365 | 43 / -6.34 / fail | 43 / -9.76 | 43 / -9.76 / fail | 43 / -9.76 / fail | no |
| trend_donchian_avax_4h | — (paper/demo only) | 365 | 47 / -11.02 / fail | 46 / -10.94 | 46 / -10.94 / fail | 46 / -12.43 / fail | no |
| trend_donchian_eth | — (paper/demo only) | 365 | 108 / +6.90 / pass | 108 / +7.98 | 108 / +7.98 / pass | 108 / +7.98 / pass | no |
| trend_donchian_eth_4h | bybit_2, bybit_portfolio | 1095 | 135 / +44.64 / pass | 51 / -9.57 | 135 / +44.64 / pass | 135 / +28.95 / pass | yes |
| trend_donchian_eth_prop | breakout_2, tradeify_1, velotrade_1 | 365 | 165 / -0.25 / fail | 165 / +0.44 | 165 / +0.44 / pass | 165 / -4.12 / fail | no |
| trend_donchian_sol | — (paper/demo only) | 365 | 58 / -2.88 / fail | 58 / -2.88 | 58 / -2.88 / fail | 58 / -2.88 / fail | yes |
| trend_donchian_sol_4h | — (paper/demo only) | 1095 | 116 / +36.86 / pass | 33 / -4.79 | 116 / +36.86 / pass | 116 / +36.86 / pass | yes |
| trend_donchian_sol_prop | bybit_2, bybit_portfolio | 2170 | 395 / +48.03 / pass | 63 / -2.00 | 395 / +48.03 / pass | 395 / +47.57 / pass | yes |
| trend_donchian_xrp_4h | bybit_2, bybit_portfolio | 1460 | 46 / +7.71 / pass | 14 / +3.48 | 46 / +7.71 / pass | 46 / +7.71 / pass | yes |
| trend_donchian_xrp_adx25 | — (paper/demo only) | 1460 | 46 / +9.72 / pass | 14 / +4.59 | 46 / +9.72 / pass | 46 / +9.72 / pass | yes |
| uso_trend_1h | — (paper/demo only) | 365 | 56 / +25.89 / pass | 56 / +25.16 | 55 / +26.19 / pass | 55 / +29.09 / pass | no |

"lane 365d old" is the HARNESS-TRAIL-GAPFILL column that was read as a reproduction failure. "reproduces" means the old-harness rebuild at the record's own `window_days` matches the committed n and net within 0.01R. `no` rows are the 365d rolling-window records; the pinned-window replays above reproduce them.

## Other findings (filed)

- `PI-20261030-QEJFFIDN-0002` (high): eth_4h and sol_prop set no `decision_bar`, so they trade the forming bar (runtime default). The builder measures them on the closed bar and grades them `faithful`. The 2026-10-28 records keep a stale `decision_bar: forming` label over closed-bar numbers. Today both clear Stage 0 on the forming arm too, so no verdict moves.
- `PI-20261030-QEJFFIDN-0001` (medium): `vol_skip_forming_bar_replay._set_costs` uses 7.5 bps for Bybit, while the builder uses 11.0. This lane's forming arms override it to 11.0.

## What changed so this does not recur

`scripts/ops/build_strategy_evidence.py`:
- An omitted `--days` now uses the committed record's own `window_days`.
- Every measured record carries `reproduce` {window_days, window_days_source, folds, data_start, data_end, git_sha, argv}.
- `--window-start/--window-end` replays a pinned window. The window is trimmed in `regime_debt_matrix.trim_csv_to_window`.

Tests are in `tests/test_strategy_evidence.py`; the three new producer tests fail on the old builder. Committed records are **not** overwritten.
