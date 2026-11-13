# ENTRY bar holes: census, hole-safe adoption, re-grade of committed grades (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-ENTRY-HOLE-SAFE-ADOPT` · Tier 1. Gates this adds or changes: none (a window with a gap is regridded and graded, never refused).

**Row:** ML-ENTRY-HOLE-SAFE-ADOPT. Evidence: `comms/research/ml_entry_hole_safe/{census,regrade}.json`; harness `scripts/research/ml_entry_hole_safe_census.py` (no holdout-ledger claim: it re-scores windows the committed records already read). Population: the 60-symbol `E.universe()` 1h USD-M lake, fresh Binance Vision fetch (run date 2026-11-12, bars through 2026-11-11 23:00).

## 1. Census (MEASURED)

On the fresh, complete lake: **24 of 60 symbols have holes, in 2 distinct windows, both in 2022; the lake has no hole after 2022-04-03.**

| window (after → before, UTC) | missing hours | symbols |
|---|---|---|
| 2022-02-25 23:00 → 2022-03-01 00:00 | 72 | 24 (FIL FLM FTM IOTA KNC KSM LRC LTC MKR NEAR OMG RLC SOL STORJ SUSHI TRB TRX VET WAVES XLM XRP YFI ZEC ZIL) |
| 2022-03-31 23:00 → 2022-04-03 00:00 | 48 | the same 24 |

Each affected symbol: 2 holes, 120 missing hours. `ml_entry_bar_gaps.py` shows the daily archive HAS these days (FIL: 72 and 48 of 72/48 present), but the monthly-then-daily merge in `fetch_through` only back-fills the current month, so they stay holes in the training table. **The 2026-10-28 hole of the grade runs is not in today's lake**: the archive was incomplete when run 42257779569 (11-06) and 42473814600 (11-08) fetched, and is complete now. It is a *transient* hole (a late archive), so it recurs whenever a grade fetches inside the archive's publication lag; the 2022 holes are permanent and sit in every training set.

## 2. Default switched; legacy vs hole-safe table (MEASURED, complete lake)

`build_table(..., hole_safe=True)` is now the default (every `E.build_table` caller: candidate grade, retrain, diag/lever/regime/TP-revision scripts, sizing, cadence). `ml_entry_tp_revision.feature_panel` regrids too (it called `features_symbol` directly). `hole_safe=False` reproduces a legacy table. Equity builders (`ml_entry_equity`, `ml_entry_alpaca_score`) are NOT touched: equity sessions are legitimately non-contiguous and must never be regridded to 1h.

Training-table diff, legacy → hole-safe, complete lake: rows 790,209 → 788,294; **2,016 legacy-only rows** (1,008 in 2022-03 and 1,008 in 2022-04 = 24 symbols × 42 decision rows, i.e. the 168 bars after each hole at a 4 h decision cadence, whose positional features spanned it), 101 safe-only rows (cross-sectional rows that regain a defined breadth/rank). On the 788,193 common rows labels are identical (0.0% differ) and per-symbol features are identical (0.0%) except the three cross-sectional columns (`xs_rank_ret24` 0.053%, `breadth_up24` 0.046%, `rel_vol` 0.055%; 432 rows, all at the 2022 hole timestamps). **Effect on training: 0.26% of rows removed, nothing else moves.** A served-model retrain on this table follows the normal evidence path; none is done here.

## 3. Re-grade of the committed grade records (MEASURED; both records reproduce exactly with the grade-time hole)

Method: rebuild with the 2026-10-28 bars deleted (the grade's data state); the legacy build reproduces each committed number to the digit, which validates the harness. Rows cut at `window_end − 1 day` (labels need 24 forward bars) so window rows match the record (3234). Served/candidate scored with the registered policy at tau 0.1.

| record | build | window rows | served n / mean net R | candidate n / mean net R | rule (cand ≥ served) |
|---|---|---|---|---|---|
| **42257779569** (promotion grade of the served v1r20261106; served = v1, candidate = committed booster, sha 0c748e1a… verified) | as committed | 3234 | 342 / −0.0918 | 288 / −0.0369 | **pass** |
| | hole present, legacy (reproduces) | 3234 | 342 / −0.0918 | 288 / −0.0369 | pass |
| | hole present, **hole-safe** | 1234 | 126 / +0.0412 | 138 / −0.3083 | **fail** |
| | **complete lake**, hole-safe (= legacy, no hole) | 3822 | 367 / −0.1081 | 344 / −0.1403 | **fail** (−0.0322) |
| **42473814600** (served = v1r20261106; candidate booster NOT committed) | as committed | 3234 | 317 / −0.1316 | 311 / −0.2205 | fail |
| | hole present, legacy (reproduces served) | 3234 | 317 / −0.1316 | — | — |
| | hole present, **hole-safe** | 1234 | 167 / −0.4260 | refit 139 / −0.1603 | — |
| | **complete lake**, hole-safe | 3822 | 373 / −0.2127 | refit 361 / −0.0936 | — |

Caveats, stated: (a) the 42473814600 candidate is a **refit as of 2026-10-25 on the complete hole-safe table**, not the graded booster (not committed, LightGBM refit is not bit-reproducible: its legacy-on-holed score, n 323 / −0.1168, differs from the committed 311 / −0.2205), so its rows are indicative, never a verdict. (b) The two models' gap is inside noise (se ≈ 0.06 per mean) in every row; what is firm is that the sign of cand − served flips for 42257779569.

## 4. What this means for the manager (flagged, not decided here)

1. **42257779569's "pass" does not survive complete data.** The promotion grade of the currently served model (v1r20261106 replaced v1, rule: candidate ≥ served on the same window) read cand −0.0369 vs served −0.0918 on a table with the 10-28 hole; on the complete lake the same two committed boosters read cand −0.1403 vs served −0.1081, and hole-safe on the holed data reads −0.3083 vs +0.0412. Under the registered rule that is a **fail** in both corrected builds. The operator approved the swap on the numbers in the record (the PR body already noted −0.0369, not the +0.0018 first shown). This is a Tier-3 question about the served model: surfaced for the manager, nothing changed here.
2. 42473814600's fail and its candidate comparison are an artifact of the hole in the served leg's number (−0.1316 vs −0.2127 complete); the candidate leg cannot be re-scored exactly.

## 5. SERVING path (read only; no runtime change)

`src/runtime/ml_decision_features.py::features_symbol` is a verbatim serving copy of the research function: positional `rolling(24/168/14)`, `shift(k)` and `diff()` over whatever bars it is handed, and `ATR` via `rolling(ATR_N)`. `src/units/strategies/ml_entry.py::order_package` passes `candles_df` (closed 1h bars, last = decision bar) straight to `F.decision_row` with only a `len >= MIN_BARS` check, **no contiguity check** on the own frame, the reference frames, or the 200-bar tails taken for the cross-section (`fr.iloc[-200:]`). So **if a live candle fetch ever returns a frame with a missing hour inside the last ~168-200 bars, the live row is a seam-computed row** (the same defect, 168 bars of corrupted `ret_*`/`vol_*`), scored and traded on real money. Whether the live candle source can produce such a hole was NOT measured here (no live read in this lane). Filed as a separate Tier-2 row (see the checklist): measure live hole incidence from the candle store/audit log first, then regrid or skip in `decision_row`.
