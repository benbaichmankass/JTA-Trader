# LTR-CLASS-GRADE — pre-registration (committed BEFORE any result is read)

Lane LTR-CLASS-GRADE, dispatched by Manager Session 2026-11-01a. Registered 2026-11-01 ~13:00Z, before the grader is run
and before `comms/live_review/outcomes.jsonl` or any counterfactual output is read by this lane.

Gates this adds or changes: none. This is a measurement; any execution change it supports is a separate Tier-3 proposal.

## Question
For each live-review action class, is the recorded set of reviewer calls good enough to apply automatically to real money
(and its Stage-2 mirror)?

## Population
Every recorded live-review recommendation row in `comms/live_review/reviews.jsonl` on `origin/main` and on
`origin/live-review/rows` (union, de-duplicated by `review_id`), every account, applied or not, since the first row.
Classes: `close`, `partial_close`, `tighten_sl`, `move_tp`, `widen_sl`, `hold` (plus any other action present, reported).

## Measurement
Counterfactual delta R of the call versus doing nothing (hold the bracket as it stood at the call), priced from the
symbol's candle path after the call, net of the full cost stack the existing harness applies. Harness: the existing
counterfactual grader (`scripts/research/live_review_counterfactual.py` via `scripts/ops/live_review_grade.py`,
and/or `scripts/research/live_review_outcomes.py`), AUDITED by this lane before use; any defect is fixed or stated.
A call that cannot be priced is counted in the denominator and reported with its reason; it never counts as 0.
`hold` is reported as its delta vs the best recorded alternative where the harness defines one; it has no "vs nothing".

## Pass rule (the stricter of the two candidates is used)
Rule used: the **MD-TRADE-DESK review_rule (CLAUDE-GRADE-LOOP, operator "1", 2026-10-26)**, which is stricter than the
dispatch rule because it adds a calibration clause, PLUS the dispatch's regime clause. A class **PASSES** iff all hold:

- P1 — n >= 20 priced calls (applied + recommended-only).
- P2 — mean delta R > 0 net of the full cost stack.
- P3 — bootstrap CI95 of the mean (10,000 resamples, seed 20261101, resampling calls) lies entirely > 0.
- P4 — the class's calibration is not OVERCONFIDENT (as `live_review_grade.py` computes it), where calibration is measurable.
- P5 (regime) — the class's mean delta R stays > 0 after dropping its single best ISO week, AND a majority of ISO weeks
  holding >= 3 priced calls have mean > 0. Per-week and per-month tables are reported regardless.
- P6 (independence) — repeated calls on the same order package are correlated; P3 is ALSO computed with a package-level
  cluster bootstrap, and the class passes only if that CI95 lower bound is > 0 too.

**FAIL** = n >= 20 and the CI95 (either form) lies entirely < 0, or P2 fails. **INDETERMINATE** = anything else
(n < 20, CI straddles 0, or P4/P5/P6 fail with P1-P3 holding).

Reported, never a pass clause: per-account and per-strategy split; share unpriced with reasons; applied vs recommended-only.

RULE-AM-RISK-ADJUSTED-V1 cannot be run here (no book-level simulation exists; row BOOK-SIM-REAL-SIZER); it is not used.
