# Can the giveback predictor gate the exit levers? (EXIT-GIVEBACK-PREDICTOR-GATE, 2026-10-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `EXIT-GIVEBACK-PREDICTOR-GATE` (Tier 1, Sonnet; operator order "3 then 2 then 1", this row third). No `src/` or `config/` file is touched. **MEASURED** = read from a committed result or the code (locator given); **INFERRED** = my reading.

## Answer

**The gate has already been tested where the predictor had its best skill, and it failed; a third and fourth leg are pre-registered below.** The predictor's skill is real only in log-loss, and it is small.

## 1. What eba2-04 and eba2-01 measured

| Claim | Status | Locator |
|---|---|---|
| Label: binary "big giveback" = peak-to-exit R at or above the training folds' median (`big_quantile` 0.5), read at bar k=6 on trades still open | MEASURED | `research/queue/RQ-20261022-eba2-01.yaml` `run.command`; `scripts/research/path_metric_giveback.py::giveback_label` |
| Inputs: baseline `open_r_k, peak_r_k, bars_since_peak_k` (eba2-04 adds `vol_ratio_k`) plus `chop_k, er_k, shape_k, early_k`, all from bars 1..k | MEASURED | same script, `BASE_FEATURES`, `PATH_FEATURES`; result `measurement.features` |
| Out-of-sample: leave-one-fold-out over 6 calendar folds by entry time, 2020-07-01 .. 2026-10-15 | MEASURED | result `measurement.pooled.per_fold` |
| eba2-01 pooled (6 sibling legs, n=1209 open at bar 6): ll_gain +0.0115 on a 0.6902 base, 5/6 folds; **r2_gain -0.0046, 1/6 folds** | MEASURED | `research/results/RQ-20261022-eba2-01/39871232618.jsonl` `measurement.pooled` |
| eba2-04 pooled (4 legs, vol-controlled, n=835): ll_gain +0.0145 on 0.6814, 5/6 folds; **r2_gain -0.0005, 3/6 folds** | MEASURED | `research/results/RQ-20261022-eba2-04/39999067424.jsonl` `measurement.pooled` |
| Per leg with log-loss skill >= 0.01 and a pass: eba2-04 ada_pullback_2h (+0.0190, n=275), xrp_pullback_2h (+0.0136, n=352); eba2-01 eth_pullback_2h (+0.0165, n=327), trend_donchian_ada_4h (+0.0159, n=159). trend_donchian_eth_4h read -0.033 (0/6); xrp_4h n=44 indeterminate; avax/sol 2h, sol/avax 4h failed | MEASURED | same files, `per_leg` |
| The "PASS" is the log-loss clause only; the R2 clause failed everywhere (full-model R2 is below the baseline's on most legs) | MEASURED | same |
| A log-loss gain of 0.01-0.02 against 0.69 (ln 2 = 0.693) means the flag is barely better than a coin | INFERRED (no AUC was recorded) | |
| Population: Binance perp candles, 2h pullback and 4h Donchian legs, trades open at bar 6, net of fee 7.5 + slippage 3.0 + funding 1.0 bps/window(which accounts roster each leg was NOT checked this session) | MEASURED | result `cost_policy` |

## 2. The gate was already tested, on the two best legs, and failed

`RQ-20261022-eba2-07` (ada_pullback_2h) and `-08` (xrp_pullback_2h): out-of-fold triggers at P >= 0.5 (146 of 275 and 179 of 352 scored trades flagged, so about half), arms MB/MT gated against UB/UT ungated. Both `fail` / `incumbent_stands` (MEASURED, `research/results/RQ-20261022-eba2-07/40033389616.jsonl`, `-08/40039461443.jsonl`). Gated tight trail MT: ada +4.59 R vs bar 8.04 (4 of 6 folds, needs 5); xrp -9.92 R. Ungated UT: ada -21.2, xrp -26.0. The gated arm beat the ungated one on both legs, so the predictor's selection is not nothing, but it does not clear the declared exit. Those triggers had no volatility control and a 0.5 threshold.

## 3. Gaps found, and fixed in this PR (Tier 1, `scripts/research/`)

1. **The replace grade never enforced the "beats its unconditional control" clause** that eba2-07's registered rule states (MEASURED: `grade_replace` compares to the incumbent only; the 07/08 results show `"control": null`). Added `--vs-control CAND=CTRL`; a control arm is never itself a candidate.
2. **The trigger had no volatility control and no selectivity.** Added `--trigger-baseline-extra vol_ratio_k` and `--trigger-p-threshold`.
3. **No null for the gate.** Added `--trigger-shuffle-seed`: a seeded random flag set with the same number of flags (reads no label or price), token `@trigger_file_random`. A gate that does not beat it is tightening a random subset.
Tests: `tests/test_path_metric_giveback.py` (2 new), `tests/test_exit_lever_ablation_vs_control.py` (3 new). Defaults are byte-identical to before.

## 4. Bias guard: the harness fills a stop at the stop price

A tightened trade exits more often by stop, and a stop that fills at its own price (not at a gap) flatters it. `MT - A` is therefore biased toward the lever. `MT` and `RT` tighten the same number of trades, so `MT - RT` carries the same fill artifact in both and cancels it; the decision rule requires MT to beat RT and UT in at least 5 of 6 folds, and a PASS still needs a gap-adjusted re-run before any Tier-3 note. PR #19856 (closed-bar exit timing) does not change the harness fill.

## 5. Units (pre-registered; each `would_dispatch` in `dispatch_queue.py` dry run)

`RQ-20261024-9a7e-01` ada_pullback_2h, `-02` xrp_pullback_2h (re-asked with a vol-controlled, selective P >= 0.6 gate plus the random null), `-03` eth_pullback_2h, `-04` trend_donchian_ada_4h (the two legs with log-loss skill and no gate test). Arms A / MT / UT / RT, 6 calendar folds, replace grade, full cost stack, `roadmap: L-ATM`, theme `live_strategy`. Power: MDE 2.8/sqrt(n) sd = 0.14 / 0.14 / 0.15 / 0.17; the 0.02 R/trade bar is below what one leg can resolve (see `exit-failed-levers-diag-2026-10-24.md`, finding 1), so the 5-of-6-fold rule and the two control contrasts carry the verdict, and a PASS is a discovery that needs one confirmation unit.

INFERRED expectation, not a result: given log-loss skill of about 0.015 and two prior fails, the likely outcome is FAIL on all four. The units exist so the answer is a measurement.
