# Confidence-score model: item 1, the data audit (read-only, no training)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none. Read-only measurement; no model fit, no runtime or config change.
> Parent: [`CONFIDENCE-SCORE-MODEL-DESIGN-2026-11-09.md`](CONFIDENCE-SCORE-MODEL-DESIGN-2026-11-09.md) § 4 item 1. Row: `CONFIDENCE-SCORE-EVERY-TRADE`.

**Method.** Read-only `/api/diag/*` through `scripts/ops/diag_fetch.sh` at 2026-11-09 ~14:35Z (served by `https://ict-bot.duckdns.org`). `journal?table=trades` and `journal?table=order_packages` were paged with `limit=1000&offset=N` until the whole table was read; the DB was never copied. Row counts match `db_info` exactly (trades 6998 = 6998, order_packages 5788 = 5788), so every figure below is over the WHOLE table unless a population is named. Provenance: all counts are `MEASURED` from journal rows; R values derived from columns would be `ESTIMATED` (bar-granularity stops, no fills), and none is used for a conclusion here.

## 1. Closed trades per book and per strategy

Population: `trades` rows with `status='closed'`, n = **2567** of 6998 rows (rest: rejected 3828, exchange_rejected 445, orphaned 131, open 18, rejected_too_small 6, error 3). All `is_backtest = 0`. Table window: `timestamp` 2026-05-01 to 2026-11-09.

| book (`account_id`) | closed | first close | last close | note |
|---|---|---|---|---|
| bybit_1 (Stage-1 soak, paper) | 1675 | 2026-05-20 | 2026-11-09 | |
| bybit_2 (real money) | 521 | 2026-05-09 | 2026-11-09 | |
| bybit_portfolio (mirror) | 112 | 2026-07-20 | 2026-11-09 | |
| alpaca_paper | 112 | n/a | 2026-11-09 | one row (id 6131) has `closed_at='1790835474843'`, an epoch-ms string, not ISO: a writer defect, filed below |
| alpaca_portfolio | 68 | 2026-07-17 | 2026-10-15 | |
| ib_paper | 67 | 2026-06-13 | 2026-11-02 | |
| alpaca_options_paper | 8 | 2026-06-27 | 2026-06-27 | |
| alpaca_live | 4 | 2026-07-15 | 2026-09-28 | |

By class: paper 2042, real_money 525 (`is_demo` 1 / 0 agree). 62 distinct strategy names, none null. Exit reasons (top): sl 613, reconciler_filled 397, pairs_revert 277, pairs_stop 232, tp 201, sl_cross 153.

Per strategy (closed, all books): **6** strategies have >= 100, **16** have >= 50, **22** have >= 30. The head: vwap 362 (322 on bybit_2), pairs_sol_eth_a 187, pairs_sol_eth_b 185, pairs_bnb_btc_a 175, pairs_bnb_btc_b 173, ict_scalp_5m 114, ict_scalp_avax_5m 88, ada_pullback_2h 76, eth_pullback_2h 71, squeeze_breakout_4h 70, xrp_pullback_2h 68, ict_scalp_sol_5m 65, trend_donchian 64, trend_donchian_eth_4h 59, htf_pullback_trend_2h 59.

Real-money only: 18 strategies, 525 trades, **vwap 322 of them (61%)**, ict_scalp_5m 41, orphan_adopt 23, trend_donchian_eth_4h 20, xrp_pullback_2h 20, eth_pullback_2h 19, ada_pullback_2h 18, trend_donchian 17; no real-money strategy other than vwap exceeds 41 closed trades.

Caveats that bind the sample: the four `pairs_*` strategies (720 closed) are two-leg trades whose per-leg R is not the trade outcome; `pnl` is null on 161 closed rows (105 bybit_1, 18 bybit_2, 15 alpaca_paper, 12 alpaca_portfolio, 8 ib_paper, 3 bybit_portfolio), so a net-P&L label cannot be formed for them; entry, stop and exit price are all present on 2394 of 2567 closed rows (a gross R is derivable for those, not net of fees); 2163 of 2567 carry an `order_package_id` (the join to entry features; all 2163 resolve to a package), and **the 404 without one include all 362 `vwap` closed trades**, so the strategy that is 61% of real-money closes has no entry-feature join today.

Implication for the design: a single pooled confidence model has about 2000 labelled closed trades at most, but per-strategy fits are viable for ~6 strategies and thin (< 50) for most; a pooled model must be validated per strategy before it is claimed for any one.

## 2. Is there a per-trade path (open R / peak R through time)?

Yes, two tables exist, with different grain; neither is a fill-level record.

- `position_path_history`: append-only, one row per (order_package_id, bar_ts), written each exit-loop pass (~30 s) and upserted within a bar; carries `peak_r`, `mae_r`, `sl_r`, `tp_r`, `atr`, `adx` (source: `src/runtime/position_path_history.py`). Retention 90 days. **2295 rows** at read time. The writer shipped 2026-10-15, so it can only cover trades from then on. **Not measured here: how many distinct packages / closed trades those 2295 rows cover.** `position_path_history` is not an allowlisted `journal` table and no diag route returns per-package coverage, so the share of closed trades with a path is `could-not-look`, not zero. Filed as a follow-up.
- `position_telemetry`: one upserted row per package (latest pass wins), read through `/api/diag/position_telemetry` (783 rows): 465 closed (463 stamped final), 14 open, 304 `unknown_no_trade_id`; `peak_gradeable` 514; `peak_provenance` is `estimated`, and `peak_r_is_lower_bound` is flagged.

So for checkpoint labels (design § 3.1 re-score sample) the live path covers at most the ~465 closed trades with a final telemetry row, and only the sub-population with path-history rows from 2026-10-15; for everything earlier (2567 closed trades), open R / peak R through time must be RECONSTRUCTED from fills plus bars, and would be `ESTIMATED` at bar-extreme granularity. The two sources must not be mixed without a provenance flag.

## 3. Candidate inputs served at entry time on the live path

Source: the `meta` and `signal_logic` JSON of `order_packages`, plus first-class columns. Population: all 5788 packages (created 2026-05-02 to 2026-11-09), then the 1847 packages linked to a closed trade, then the 239 created since 2026-10-26. Share = packages where the key is non-null.

| design § 3.2 input | served at entry? | all 5788 | linked to closed (1847) | since 2026-10-26 (239) |
|---|---|---|---|---|
| strategy id, direction, symbol | yes: columns | 100% | 100% | 100% |
| entry, sl, tp (R:R, stop distance) | yes: columns, numeric | 100% | 100% | 100% |
| timeframe | meta | 89% | 100% | 100% |
| ATR (`atr`; `atr14` on `ml_entry`) | meta | 72% | 59% | 75% |
| `risk_per_unit` | meta | 51% | 61% | 97% |
| `adx_14` | meta | 58% | 55% | 84% |
| `regime` + `vol_regime` | meta | 58% / 52% | 55% / 55% | 84% / 84% |
| `entry_time` | meta | 49% | 58% | 89% |
| `tp_r` | meta | 37% | 38% | 54% |
| `sized_qty_by_account` (book context) | meta | 87% | 61% | 100% |
| entry-model score | `model_scores` non-empty | 18% (1070) | 25% (455) | 27% (64) |
| funding | none: 0 packages carry a `funding*` key | 0% | 0% | 0% |
| OI | only `e4_oi_shock_1h`, 20 packages (the `oi_` keys) | 0.3% | 0.8% (15) | 8% (20) |
| book depth / imbalance | none: 0 packages | 0% | 0% | 0% |

A first probe for "basis" matched 153 packages but every match is the key `tp_basis` (a take-profit label), not funding basis; it is not counted. Per-strategy gaps matter more than the pooled share: `atr`, `regime` and `vol_regime` are not written by every strategy (`vwap` writes its own `vwap`/`std_dev`/`deviation_std` set), so any pooled feature must be tested per strategy for 100% presence or imputed under a declared rule. `ml_entry` (29 packages) carries zero `model_scores` and its own `p_long`/`p_short`/`features`/`model_id`/`tau` in `meta`; that is where its score lives.

`model_scores`, last package scored per model id: `execution-quality-baseline-v0` 2026-11-09; `eth-regime-1h-lgbm-v1` and `-xasset-v1` 2026-11-08; `btc-regime-5m-*` 2026-11-06; `btc-regime-1h-lgbm-v2/-yz-v1` 2026-10-28; `setup-quality-baseline-v0` 2026-10-21; `setup-quality-audit-baseline-v0` 2026-10-11; `conviction-meta-v1` and `setup-quality-lgbm-v2` 2026-09-29 (the JC-SA-02 demotions, no package scored since); the `trade-outcome-*` and `prop-mission-policy` baselines 2026-06-30. None is a general confidence score for an order package.

Book depth (ETH and SOL, 2023-01 onward) and funding/basis/OI exist in the research lake or builders but are NOT on the live package today; the design's rule "anything not servable live is out" therefore removes funding, OI (all but one strategy) and book depth from the first model unless item 2 (shared feature builder) serves them.

## 4. The package `confidence` field

Population: all 5788 packages; parse failures 0, nulls 0 (2553 distinct values).

- `confidence == 1.0` on **2317 of 5788 (40.0%)**.
- It is not uniform across strategies: **`vwap` 2040 of 2081 (98.0%, 2 distinct values)** accounts for 88% of all the 1.0s. Three strategies are 1.0 on every package and six have a single distinct value (64 strategies in total). Others with many 1.0s: `trend_donchian_eth_prop` 45 of 131, `trend_donchian_eth` 30 of 63, `mgc_trend_1h` 53 of 345, `htf_pullback_trend_2h` 20 of 100. The rest carry a continuous value (e.g. `ict_scalp_avax_5m` 1 of 210, 205 distinct).
- Among the 1847 packages linked to a closed trade: 109 are 1.0 (5.9%), 1294 distinct values; none of the 109 is `vwap` (top: ml_entry 15, trend_donchian_eth 15, htf_pullback_trend_2h 14), because **no closed `vwap` trade has an `order_package_id`: 0 of 362** (vwap has 2081 packages and 362 closed trades, no join between them).
- The 200 most recent packages (2026-10-29 to 2026-11-09): **64 of 200 = 1.0** (the manager's 11:15Z read was 61 of 200; the window moved).

Reading: for `vwap` and a few others `confidence` is a strategy default, not a model output, and must render as "—" and be excluded from any label, feature or calibration reference. For the non-constant strategies it is a strategy-computed heuristic of unknown calibration; whether it carries any information about the outcome is NOT measured here (that is a model-stage question, not a data audit).

## 5. What this changes in the design

1. Labelled samples (entry-feature join exists for 2163 closed trades, none of them `vwap`): ~2000 closed trades with a derivable gross R, ~2400 minus 161 null-`pnl` for net; `vwap` is 61% of real money. The money test must be per strategy or per class, and say so before the run.
2. Re-score checkpoints: the live path covers ~465 closed trades (telemetry) from 2026-10-15; the rest is reconstruction (`ESTIMATED`). Item 4 (replay corpus) is where the larger sample comes from.
3. Inputs servable today are strategy id, direction, R:R, stop distance (ATR where present), timeframe, regime/vol/ADX (84% recently), entry model score where one exists. Funding, OI and book depth are not served; including them depends on item 2.
4. `confidence` must not be a feature or label anywhere; 40% of the table is a default.

## 6. Limits and follow-ups

- `position_path_history` per-package coverage is `could-not-look` (no read route); follow-up: an allowlisted diag read or a `system-actions` read count of distinct `order_package_id` in it.
- `closed_at` malformed on trade id 6131 (epoch-ms string) and `pnl` null on 161 closed rows are writer/reconciler defects worth a separate look; neither was investigated here.
- `journal?table=order_packages` pages are not snapshot-consistent (the table is ordered by a mutable `updated_at`; the route reports `page_stability`); the 5788 unique ids matched `db_info`, so no skip or repeat showed up in this walk.
- Counts are a 14:35Z snapshot; 18 trades and 15 packages were open and are excluded from the closed population.
