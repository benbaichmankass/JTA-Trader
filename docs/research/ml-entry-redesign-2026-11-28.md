# ml_entry (D3) redesign: a rule picks the side, a linear model decides; plus a market-neutral cross-section arm. Registered design (2026-11-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PRIMARY (session_01AFoLuLpCY5gABbqk3EBUeV) · row `ML-ENTRY-REDESIGN`

**Gates this adds or changes:** none. This is a research design. The live ml_entry stays the D3 incumbent until a tested replacement beats it (OPERATING-PLAN § 2, "Each decision keeps its tested incumbent until a better one passes", operator 2026-11-28).

Operator, 2026-11-28 ~09:30Z, popup relayed by Manager 2026-11-28b, verbatim: *"Step back: redesign (Recommended)"*. At ~09:50Z: *"if we've tried a few levers and we think that it's worth doing a redesign instead of more levers, then like we should definitely do that."*

## 1. Diagnosis: why another lever on this recipe will not do it

Every number below is read from committed records; none was re-run for this doc.

- **The base is about zero.** The recipe, refit per dev fold, earns +0.0030 R/decision over n 71,334 (8 dev folds) and +0.0034 out of time over n 12,089 (`ML-D3-UNLOCK-20261123`).
- **33 levers have been tried on this base, with 0 passes.** This covers recency, bigger learners, a tabular foundation model, a recurrent net, side gates, calibration, caps, brackets and feature families (`docs/research/ml-entry-new-information-classes-2026-11-27.md` § 1; f1a0, c4e2, 7ab1, 9e73).
- **The side is the problem, and it follows the regime.**
  - Live: served v1 lost money after 11-01, with longs −0.46 R and shorts +0.21 R (c4e2-01, n 867).
  - The long/short split tracks the market regime: corr 0.89 over 13 folds (`ml-entry-side-by-fold-2026-11-23.md`).
  - Live SHAP shows the side is set by market-wide inputs (btc_vol24, btc_ret24).
- **The current design asks one model to do two jobs:** pick a direction, and size an edge that is mostly market beta. The label is per-side net R in a fixed 2/3 ATR, 24 h bracket. The policy takes the better side above tau. In this setup, the direction call is a beta bet the model cannot time, and the per-decision edge left after costs is +0.003.
- **The read ledger shows ml-entry's held-out year 2025-10-01..2026-11-20 has 32 overlapping graded reads** (`read_ledger.py`, 2026-11-28). Any new arm graded there faces the M13 bar at N ≥ 33. So selection must happen on dev folds, with a small pre-registered arm count. One confirming read happens on the held-out year, at the deflated bar.

## 2. The redesign: three changes, each answering one finding

### 2.1 Target: separate the side from the decision (answers "the side is beta")

**Arm R1: meta-labelling on a rule's direction (López de Prado).**
- A fixed, causal rule chooses the side. The house time-series-momentum signal is used: the sign of `ret_168`, the same signal d3a1-01 used as a gate.
- The model predicts only whether to take that rule's trade: P(net R > 0 | features), net of the full cost stack, with the same bracket.
- The model never chooses the side, so beta timing leaves the learning problem.
- The incumbent comparison is the rule taken unconditionally (the "always take" baseline), plus the current recipe.

**Arm R2: market-neutral cross-sectional rank (side-neutral by construction).**
- At each decision bar, the model ranks the 60 perps by expected forward 24 h return relative to the cross-sectional mean.
- The book is long top-k and short bottom-k, equal risk, so it is dollar- and beta-neutral.
- The market move that drives the live long deficit cancels inside the book.
- The baseline is the same book ranked by raw `ret_24` (cross-sectional reversal/momentum), which is the cheapest known edge of this shape.
- Execution difference, stated: R2 is a paired book, not a single-leg entry. A PASS feeds a new D3 variant (a paired-entry leg), not the existing single-leg ml_entry.

### 2.2 Family: non-gbdt (answers "gbdt holds 14 of 19 open family slots" and "bigger learners overfit")

- Both arms use a **regularised linear model on rank-gaussianised features**: logistic regression with an elastic-net penalty for R1, ridge regression for R2. The penalty is chosen on inner folds of the training span only.
- Why linear: the per-decision edge is about 0.01 R and the noise is about 1 R per trade. At that signal-to-noise, a low-variance learner that cannot fit interactions is the principled first family. The gbdt variance (c4e2-03: bigger learners overfit) is the cost the redesign removes.
- One LightGBM twin of each arm is reported beside it, descriptive and not graded, so the family effect is measured rather than assumed.

### 2.3 Inputs: the current 20 features plus market context, rank-normalised per bar

- Same universe, decision grid and dev folds as c692-01 / c4e2. No new data source, so the test isolates the target and family change.
- The compact derivatives state (`F2c` + `F5c`, unit A of the 11-27 plan) joins only if that unit passes on its own.

## 3. How it is graded (MEASURE-READ-LEDGER-PBO)

1. **Selection on dev folds only, 4 pre-registered arms:** R1-linear, R1-gbdt (descriptive), R2-linear, R2-gbdt (descriptive). No grid beyond the inner-fold penalty.
2. **Per arm** (registered before the run):
   - delta vs its own baseline (R1 vs always-take; R2 vs raw-`ret_24` rank) ≥ +0.010 R/decision;
   - week-clustered t ≥ 2.24 (Šidák, k = 2 graded arms);
   - positive in ≥ 6 of 8 folds and in ≥ 3 of 4 years;
   - net of the full cost stack. R2 also charges both legs' costs.
3. **PBO** over all arms run in the redesign (`pbo_cscv.py`, 16 blocks of ISO weeks) is reported with the verdict. A PBO ≥ 0.5 is stated as "selection likely overfit" next to any PASS. It is not a gate (operator proposal D-C is deferred).
4. **One confirming read** of the passing arm on 2025-10-01..2026-11-20, claimed in the holdout ledger. Its bar is `holdout_lock.bar_for(N)`, where N is the overlapping read count at claim time: 33 or more today. That read decides. A PASS there becomes a data-backed Tier-3 challenger packet against the live incumbent.
5. **Every result carries the `read_ledger` block**, stamped by `script_run.derive_record` (report-only).

## 4. What depends on what (no waiting on data)

| Input | State | Effect on this design |
|---|---|---|
| D3 trend-conditioned side (RQ-20261128-d3e1-01, held #29759) | registered, runs once merged | PASS: R1's rule direction gains the 72 h alignment term (sign of `ret_168` AND `ret_72`). FAIL: R1 keeps `ret_168` alone. Either way R2 is unaffected. |
| First PBO of the f1a0 arm grid (RQ-20261128-b0f1-01, held #29755) | registered | Sets the expected PBO scale the redesign's verdict is read against |
| Harness | **build needed** | `ml_decision_entry.py` gains `meta-arm` (R1: rule side in, take/skip label) and `xs-rank-arm` (R2: per-bar cross-sectional book), each with `--emit-series`. Row `ML-ENTRY-REDESIGN` carries the build. |

## 5. Calls (graded at the next weekly ML review)

- R1-linear PASSES dev (p 0.25). R2-linear PASSES dev (p 0.2). At least one passes (p 0.4).
- PBO over the 4 redesign arms is below 0.5 (p 0.5).
- The harness build lands by 2026-12-05 (p 0.7).
