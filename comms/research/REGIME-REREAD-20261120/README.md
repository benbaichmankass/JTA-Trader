# REGIME-REREAD-20261120 — 1-D regime OFF cells re-read on the fixed regime tooling

> Lane ML-PRIMARY-16, 2026-11-20, Tier 1 read. Queue item PI-20261120-7ITMUEB1-0008. Gates this adds or changes: none.
> **Nothing is flipped by this record.** Every keep / flip-candidate below is input to a Tier-3 proposal (regime-selectivity skill, Rule 2).

## What was run

`scripts/research/regime_cell_walkforward.py` on main `b0f2a3727`. That tree includes the open-stamped `candle_io.resample_ohlcv`
and the causal `entry_bar_locator` (#27654); both were read in `scripts/candle_io.py`. The harness grids (#27566) are included per the
queue item's text; that part was NOT separately verified (corrected 2026-11-20 at close-out).
The verdict is the fixed fold panel (3, 4, 5): `stable_drag` = pooled < 0 AND a strict majority of folds negative at every panel size.
The feed is Binance-vision BTCUSDT, the same feed as the July evidence, so the comparison is like for like. A Bybit-native re-read is not part of this record.
The runs were made in the lane sandbox. Each `*.json` holds the full argv-reproducible result and each `*.log` holds the text verdict.
Local paths are scrubbed to `<workdir>`.

- **htf_pullback_trend_2h** (BTCUSDT 2h): window pinned to the July A5 record's window, 2024-08-04 .. 2026-07-27,
  `--days 900`. Fidelity `approximate`: the omitted lever is `decision_bar`, a config lever the harness does not model.
  The July record read `faithful`; why it now reads `approximate` (e.g. whether `decision_bar` was added to the leg config after July) is
  UNVERIFIED (corrected 2026-11-20 at close-out: the earlier wording asserted it).
- **trend_donchian / fvg_range_15m / fade_breakout_4h**: window 2024-11-15 .. 2026-11-15 (`--days 740`). These cells have only
  matrix comments as evidence, no walk-forward record, so this run is their first Rule-2 gate.

## Population

Every 1-D OFF cell in `config/regime_policy.yaml` whose strategy is on a live roster. All of these legs are on `bybit_1`
(the demo floor) only, and **none is on a real-money roster**: the policy keys match leg names exactly, verified against
`config/accounts.yaml` on 2026-11-20. vwap and gld_pullback_1h are on no roster and were not run.

## Per cell (field: the JSON `cell_verdict`)

| # | cell (OFF side) | n (side) | pooled R | verdict | July / comment | disposition |
|---|---|--:|--:|---|---|---|
| 4 | trending htf_pullback_trend_2h **long** | 44 | −12.39 | stable_drag | −6.85 / n42, stable_drag | **KEEP**, strengthened |
| 1 | trending htf_pullback_trend_2h **short** | 58 | +8.75 | no_stable_drag | +7.89 / n54, no_stable_drag | **FLIP-CANDIDATE (weak)**: OFF is not justified, but fold 3 is +7.85 of +8.75 (90%) |
| 2 | transitional htf_pullback_trend_2h **short** | 12 | −2.17 | no_stable_drag, fold_sensitive | comment −4R | **FLIP-CANDIDATE (thin)**: not `stable_drag`, n 12 |
| 3a | chop htf_pullback_trend_2h **long** | 11 | +3.40 | no_stable_drag | comment −8R | **FLIP-CANDIDATE (thin)**: the cell's sign has inverted, n 11 |
| 3b | chop htf_pullback_trend_2h **short** | 6 | +0.57 | insufficient_n (< 10) | comment −4R | **NO FINDING**: leave as is |
| — | trending / transitional trend_donchian **short** | 0 | — | no_trades (vacuous) | −28R / −24R | **NO-OP CELL**: the leg is `long_only: true` |
| — | trending fvg_range_15m, trending fade_breakout_4h (both sides) | 0 | — | no_trades (vacuous) | none | **NO-OP CELL**: both legs set `adx_max: 20`, so they never fire in `trending` |
| — | chop fvg_range_15m **long** | 16 | −9.53 | no_stable_drag, fold_sensitive | −17R (both sides) | **KEEP pending**: negative, but not `stable_drag` (k4 2/4) |
| — | chop fvg_range_15m **short** | 14 | +4.78 | no_stable_drag | −17R (both sides) | **FLIP-CANDIDATE (thin)**: positive, n 14 |

### New finding (not an existing OFF cell)

**transitional trend_donchian LONG is ON, and it is a `stable_drag`**: n 41, pooled −15.07R, folds negative 3/3, 4/4 and 4/5.
The adjacent trending long is +13.57R, so the router allows the leg's long side in exactly the regime where it loses.
This is an affirmative, restrictive case (Rule 2 met on the 1-D cell), for a Tier-3 proposal to set `transitional.trend_donchian.long: off`.
The leg is on bybit_1 only. Fidelity is `approximate` (`decision_bar` omitted).

## Not covered here (next steps)

- **2-D cells (5) chop/calm trend_donchian long and (6) trending/calm squeeze_breakout_4h short**: these are enforced only for a symbol
  with an ADVISORY vol head (`intents.py` `vol_enforced = vol_gated and vol_is_ml`). Re-reading them needs `--vol-labels` from
  `ml_vol_label_replay.py`, which is trainer-side. The other 2-D cells (ict_scalp_5m ×2, trend_donchian trending/volatile and
  transitional/calm) follow on the same labels.
- A Bybit-native re-read of the same cells. It is robustness only; the July evidence and the live router's label are BTC-based.
