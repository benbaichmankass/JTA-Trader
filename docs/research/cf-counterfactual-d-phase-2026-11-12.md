# Counterfactual phase B2 / D2 / D3 — live backfill, option pricing, book-level $ sim (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · rows `CF-B2-BULK-LIVE`, `CF-D2-LTR-PRICING`, `CF-D3-BOOKSIM`, `AM-REGRADE-BOOKSIM` (Tier 1 research; design `docs/plans/counterfactual-everywhere-DESIGN-2026-10-29.md` § 3-5).

## Gates this adds or changes

None. Read-only research tooling and committed records. Nothing is applied, no config or mandate is touched, no class graduates.

Everything below is **ESTIMATED** (engine replay), never MEASURED. Population is named in every section. Balances and USD totals are not committed.

## CF-B2 — every closed live + paper package (`scripts/research/cf_bulk_live.py`)

* **Read:** the VM journal paged by `offset` (`order_packages` 5,884 rows in 40 pages, `trades` 7,104 rows in 8; 0 failed pages), oldest package 2026-05-02. The live grader's `limit=150` window would have seen 2.5% of it.
* **Closed-package n: 2,517** (`status=closed`). By status: closed 2,517 · orphaned 1,693 · rejected 1,473 · emitted 135 · shadow 48 · open 18. Closed packages with a closed leg, per account (a package on two accounts counts on both): bybit_1 1,621 · bybit_2 178 · bybit_portfolio 121 · alpaca_paper 105 · alpaca_portfolio 68 · ib_paper 39 · alpaca_options_paper 6 · alpaca_live 4.
* **Graded 841; not graded 1,676, every one with one reason:** `pairs_two_leg` 716 (a two-symbol package; the single-path engine cannot replay it) · `no_filled_leg` 646 (625 of them `vwap`: closed packages whose trade rows never filled) · `no_bars_non_crypto` 152 (Binance Vision has no equities/futures; a Yahoo/IB bar source is the gap) · `legs_not_closed` 115 · `horizon_not_passed` 47. Accounted: 841 + 1,676 = 2,517.
* **CF-BULK-LIVE fidelity rule (registered before the run: `abs_gap_r` ≤ 0.10 on ≥ 80% of graded) — FAIL.** Overall 28.7% of 836 within 0.10 R (median gap 0.34 R, p90 1.88 R). Per leg (33 strategies): 0 PASS, 23 FAIL (n ≥ 10), 10 INDETERMINATE (n < 10). The gap is not noise:
  * **mechanical exits** (`sl` 339, `tp` 141, `sl_cross` 13, `tp_cross` 4): 44% within tolerance, median gap ≈ 0.11–0.13 R (5m bars, fill price, cost recording);
  * **discretionary / managed exits** (`reconciler_filled` 190, `intent_reduce_executed` 77, `stale_stop` 21, `exit_head` 11, `live_review_close` 6, `intent_reduce` 7): 0–11% within tolerance, median 0.9–1.3 R. Management actions are **not replayed** (`position_path_history` is not read per package), so the replay holds where the live trade was managed.
* **Meaning:** the engine is NOT good enough to price live decisions at 5m with no action replay; every arm from this run is `ESTIMATED_LOW_FIDELITY`. The follow-ups that would move it are named, not hidden: replay `position_path_history` actions per package, a 1m bar source, and an equities bar source. Not a P&L claim.
* **Records:** `comms/research/cf_bulk_live/2026-11-12/` (`records.jsonl.gz` one engine record per graded package, `manifest.json`, `fidelity.json`, `skips.json`).

## CF-D2 — every option class priced at every review (`scripts/research/cf_ltr_option_pricing.py`)

* **Why:** `outcomes.jsonl` prices only the class recommended (416 of 537 rows are `hold`, `delta_r` 0 by construction). Here a fixed grid is priced at **every** review (652 reviews × 8 cells = 5,216 cells, each in exactly one state).
* **Grid (registered before the run, levels from the review's own state):** `hold`, `close`, `partial_close_50`, `tighten_trail_1r` (mark − 1R), `tighten_be`, `move_tp_extend_1r`, `move_tp_pullin_half`, `widen_sl_half_r`. Engine: `live_review_counterfactual.price_review` unchanged, on Binance Vision 5m bars (so reviews older than the live candle window are priceable).
* **Written to `comms/live_review/option_pricing.jsonl` (+ `.summary.json`), NOT `outcomes.jsonl`** — a deliberate deviation from the row text: `outcomes.jsonl` rows are graded CALLS joined to `reviews.jsonl` on `review_id` (the grade loop dedupes on it), and option prices are not calls; synthetic `<review_id>::<class>` rows there would corrupt the per-class grades. A reader can join on `review_id`.
* **Priced population (mean `delta_r` vs hold, R; CI bootstrapped by PACKAGE, reviews of one package are one path):** only reviews whose hold replay reproduces the realised exit are priced, so the cells are small — **166 reviews on 51 packages** for close / partial / TP moves, 80 on 18 (trail), 65 on 19 (break-even), 150 on 47 (widen).

| class | priced n (packages) | mean delta_r | 95% CI |
|---|---|---|---|
| close | 166 (51) | +0.270 | [+0.034, +0.467] |
| partial_close_50 | 166 (51) | +0.135 | [+0.017, +0.233] |
| tighten_trail_1r | 80 (18) | +0.091 | [+0.026, +0.165] |
| tighten_be | 65 (19) | +0.193 | [−0.169, +0.520] |
| move_tp_extend_1r | 166 (51) | +0.137 | [+0.039, +0.235] |
| move_tp_pullin_half | 166 (51) | −0.078 | [−0.155, −0.013] |
| widen_sl_half_r | 150 (47) | +0.083 | [−0.172, +0.382] |

* **Read with care (do not graduate on this):** 51 packages, all legs pooled, selection by the fidelity gate (it drops reviews whose realised exit was a managed one, 135 `replay_mismatch` + 72 `hold_replay_unresolved`), reviews are triggered by giveback and so over-sample reversals, and a stop fills at its price (flatters every tighten). It contradicts the whole-trade DESK-LIFECYCLE-S0 read (management lost −0.12 to −0.16 R) because it is a different population (review-triggered states, not every bar). A class graduates only on the book-level grade below.
* Not priced: 169 reviews on non-crypto packages (`no_bars_non_crypto`), and the rest by named reason in `option_pricing.summary.json` (`review_state_missing` 88, `replay_mismatch` ~135, `hold_replay_unresolved*` 72, …).

## CF-D3 + AM-REGRADE-BOOKSIM — book-level $ sim with the real sizer (`scripts/research/cf_booksim.py`)

* **Sizer:** imports `RiskManager.position_size` (production, no copy), run with `available_usd = balance` (no pledged-margin model). Books compound on their own realised P&L; the account's `daily_dd_switch` is modelled when armed (`bybit_2`: keep open, block new, realised P&L only). Units: the books are simulated in USD and **graded in account-R** (`net USD / (start balance × risk_pct)`), because the rule's R1 (0.05 R per trade) is in R. A first run fed raw $ to R1 (a $0.05 threshold) and was discarded; the units fix changed the R1/R2/R3 labels, not the outcome. Start balance is an estimate (median of the account's own sized legs / risk_pct) and stays in memory.
* **Population:** the 841 gradable packages (crypto, non-pairs, closed, horizon passed): bybit_2 148, bybit_portfolio 101, bybit_1 786 packages; the books take the packages each account actually traded (the sizer or the daily switch may skip some: hold books n=139 / 95 / 786).
* **Arms (registered before the run, one representative per class, not the best in sample):** each class fires once at a fixed causal time (first bar at/after `t_entry + 0.25 × horizon`): `tighten_sl` stop → mark − 1R · `widen_sl` stop → 0.5R further out · `move_tp` pull-in to mark + 1R · `partial_close` 50% · `close` 100%. **R4 controls:** 60 causal matched-random books per class and account (same action, time drawn over `[t_entry, t_entry + horizon)`; never sees the exit). Rule: `RULE-AM-RISK-ADJUSTED-V1`, `basis='book_usd_sim'` (`graduation_eligible=True`), n(A) ≥ 39 met on every book. A class passes only if it passes on both Stage-2 accounts (`bybit_2` AND its mirror `bybit_portfolio`); `bybit_1` is reported.

| class (account-R, bybit_2 / bybit_portfolio) | R1 cost per trade (≤0.05) | dd cut (≥15%) | CVaR5 cut (≥15%) | folds held (≥4/6) | R4 control | label |
|---|---|---|---|---|---|---|
| tighten_sl | 0.112 / 0.096 | 21% / 7% | 20% / 15% | 4 / 3 | not beaten (both) | fails_R1 · fails_R1_R3 |
| widen_sl | 0.009 / 0.006 | 4% / 3% | 11% / 18% | 0 / 2 | not beaten (both) | fails_R2_R3 · fails_R3 |
| move_tp | 0.186 / 0.096 | 20% / 4% | 31% / 13% | 4 / 0 | not beaten (both) | fails_R1 · fails_R1_R2_R3 |
| partial_close | 0.095 / 0.066 | 16% / 8% | 22% / 14% | 4 / 0 | not beaten (both) | fails_R1 · fails_R1_R2_R3 |
| close | 0.188 / 0.131 | 18% / −4% | 45% / 28% | 3 / 3 | not beaten (both) | fails_R1_R3 · fails_R1_R3 |

* **Decision of record: no class passes. Nothing graduates, no PR per class is opened, `advice_only` is unchanged.** The picture is consistent across all three books: every class cuts risk on the real-money book (dd −16% to −21%, CVaR −11% to −45%) at an R cost above the 0.05 R bar, and the cheapest class (`widen_sl`) cuts almost no risk.
* **What this does and does not say:** one registered action per class at one causal trigger on one 6-month crypto population; it is not a lever sweep, and a different trigger could read differently (the research loop's lever units own that). The B2 fidelity result applies: the hold path is the declared bracket + own trail, not the live-managed path, which is exactly the baseline the arms are measured against. Margin pledged and venue refusals are unmodelled.
* **Records:** `comms/research/cf_booksim/2026-11-12/` (`summary.json`, `verdicts.json`, account-R only). Re-run: `python3 scripts/research/cf_booksim.py run --out <dir> --controls 60`.

## Not done, named

* B1 (`CF-B1-BULK-BACKTEST`, 352k backtest jobs) was not run here; the book sim used the B2 live+paper population, since the B1 shards are not in the repo. A re-grade on the backtest corpus is a separate unit.
* Equities / futures packages (152 + the alpaca/ib legs) need a non-Binance bar source: `no_bars_non_crypto`.
* The fidelity gap's biggest lever (replaying each package's recorded in-trade actions) is the next step before any arm from `cf_bulk_live` is promoted from `ESTIMATED_LOW_FIDELITY`.
