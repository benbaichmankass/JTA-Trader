# LTR-CLASS-GRADE — per-class verdict on the live-review record (2026-11-01)

Lane LTR-CLASS-GRADE (dispatched by Manager Session 2026-11-01a). Rule registered before the run:
[`PREREGISTRATION.md`](PREREGISTRATION.md) (commit `1a340bc70`, pushed 12:57Z). Machine record: [`verdict.json`](verdict.json),
per-call rows: [`calls.jsonl`](calls.jsonl). Harness: `scripts/research/ltr_class_grade.py` over
`scripts/research/live_review_counterfactual.py::price_all`. Every delta is computed and net of the harness cost stack.

Gates this adds or changes: none.

## Population
- **318 unique review rows**: `reviews.jsonl` on origin/main (313) ∪ origin/live-review/rows (87), de-duplicated by
  review_id. Window 2026-10-25T16:30Z → 2026-11-01T11:46Z, every account.
- By action: hold 170 · flag_mechanics 58 · no_recommendation 56 · **close 22** · **tighten_sl 11** · **partial_close 1** ·
  **move_tp 0** · **widen_sl 0**.
- Journal: 1,000 order packages and 6,817 trades read live from `/api/diag/journal`. Candles came from `/api/bot/candles`,
  which serves the last 1,000 bars.

## Verdicts (rule: MD-TRADE-DESK review_rule + the dispatch's regime and cluster clauses; see the pre-registration)

| class | calls | priced | packages priced | mean ΔR vs doing nothing | CI95 (calls) | CI95 (package cluster) | weeks | verdict |
|---|---|---|---|---|---|---|---|---|
| close | 22 | 21 | **4** | +0.823 | [+0.702, +0.944] | [+0.579, +0.950] | 1 (W44) | **INDETERMINATE**: P5 fails (one week carries all of it) |
| hold (vs close at the review-bar open) | 170 | 65 | 19 | **−0.595** | [−0.707, −0.479] | [−0.741, −0.379] | W43 1 · W44 64 | **FAIL** |
| tighten_sl | 11 | 4 | 2 | +0.594 | [+0.096, +0.871] | [−0.144, +0.840] | 1 | INDETERMINATE (P1: n=4) |
| partial_close | 1 | 0 | 0 | — | — | — | — | INDETERMINATE (n=0; trade open) |
| move_tp | 0 | 0 | 0 | — | — | — | — | INDETERMINATE (never called) |
| widen_sl | 0 | 0 | 0 | — | — | — | — | INDETERMINATE (never called) |

**No class passes, so no class goes to the operator as a real-money auto-apply yes today.** That is the verdict from the
record, not a wait: the shortfalls are below, and each has a dated fix row that needs no paper trade.

### close: why the +0.82 R does not pass
- Effective n is **4 packages, not 21 calls**. The reviewer re-issued `close` on the same open package every cycle: 12 calls
  on `pkg-5d74ca7451d64ebe` and 7 on `pkg-f07b659a7db94e8a`. A package can be closed only once, so **summing R across
  repeated calls double-counts**. The audit's "+15.15 R over 18 priced closes" is that sum. Re-measured here: call-level sum
  +17.29 R over 21 calls; **package-level (first close call per package) +3.16 R over 4 packages, mean +0.79 R**.
- The sample is narrow: 20 of 21 calls are `ict_scalp_xrp_15m` (the other is `ict_scalp_eth_15m`), all on `bybit_1`, all in ISO week 2026-W44.
- Calibration (`live_review_grade.py`): UNDERCONFIDENT, which does not block P4.
- Sensitivity, anchored on the realised exit (no hold replay, so the `replay_mismatch` refusals are not excluded):
  n=20 calls, 3 packages, mean +0.733 R, call CI95 [+0.53, +0.91], **package-cluster CI95 [−0.72, +0.94]**, which
  straddles 0.

### hold: FAIL, and what it means
A hold is the decision "do not close now", so it is priced against closing at the review-bar open, by the same paired replay
and net of the same costs. **On 17 of 19 packages, closing at the first held review beat holding** (package-level mean
−0.575 R; −10.9 R in total across 19 packages). The realised-anchored sensitivity agrees: n=104, 23 packages, mean
−0.326 R, package-cluster CI95 [−0.557, −0.094]. The accounts include real money (bybit_2 n=12, bybit_portfolio n=11) and
prop accounts.

Read this with a control, because it changes how the close result reads. **Closing at ANY review would have earned about
+0.6 R per held call.** The close calls' +0.8 R is therefore mostly a property of *the trades being reviewed*: they lose from
the trigger point on. The reviewer's ability to tell close from hold adds only about +0.2 R on 4 packages. Two readings fit
this record, and the record cannot separate them:
- **(a)** The trigger events (giveback, short_hold, …) select trades whose post-trigger drift is negative, so a mechanical
  close-at-trigger rule is the real candidate. It can be tested OFFLINE on the full backtest trade history.
- **(b)** It is one week (W44) of one regime.

This conflicts with DESK-LIFECYCLE-S0 (#20967), where Claude's replayed management cost −0.16 R vs hold. The fix rows below
reconcile the two.

### Unpriced share, with reasons (holds: 105 of 170 = 62%)
| reason | n | what it is | fix |
|---|---|---|---|
| trade_open | 46 | the package is still open | resolves on re-run; nothing to wait for as a step |
| replay_mismatch | 41 | the hold replay misses the realised exit by > 0.15 R (the leg's `monitor()` exits are not modelled) | LTR-GRADER-COVERAGE |
| no_candles | 11 | the candle API returned nothing for the symbol/timeframe | LTR-GRADER-COVERAGE |
| hold_replay_unresolved_before_close | 5 | the replay never exits before the data ends | LTR-GRADER-COVERAGE |
| candles_start_after_review | 2 | the last-1,000-bar window opens after the review (**harness defect fixed by this lane**: the replay used to start silently at the later bar) | landed here; a dated candle source is LTR-GRADER-COVERAGE |

close: 1 of 22 unpriced (replay_mismatch). tighten_sl: 7 of 11 (trade_open).

## Mechanics on real money (dispatch item 3): NOT confirmed. The premise does not hold on the record.
- `MD-LTR-ADA-AUTO` applied **nothing**. Its own row (`docs/claude/work/checklist/MD-LTR-ADA-AUTO.json`, state done) says
  *"closed 10:47:53Z with no auto action applied (n=2 auto reviews, both hold)"*. The package's 10 reviews after the grant are
  all `hold` / `flag_mechanics`. bybit_2 trade 6735 and mirror 6736 closed `sl`.
- **Executed live-review applies in the journal: 2, both `close`, both on `bybit_1` (paper)**: trade 6741
  (`ict_scalp_eth_15m`, 2026-10-27) and trade 6759 (`ict_scalp_xrp_15m`, 2026-10-28), `exit_reason=live_review_close`.
  Measured over 6,817 journal trades.
- The rows watcher (`/api/diag/log_file?name=live_review_rows_watch`; its tail holds 100 lines from 2026-10-30T02:08Z on)
  logged every altering call `advice_only` (8 close, 2 partial_close, 7 tighten_sl). That is correct under MD-TRADE-DESK
  `advice_only`.
- `runtime_logs/live_review/applied.jsonl` is **not served by any `/api/diag` route**, so the per-action applied counts the
  dispatch asked for cannot be read from here. The journal is the substitute used above. Every `reviews.jsonl` row carries
  `applied: false`, because applies are never stamped back. This is filed under LTR-GRADER-COVERAGE.
- So the real-money live-review apply path (`live_review_apply.py` on bybit_2 / bybit_portfolio) has **zero** recorded
  executions. It is not registered in `config/mechanics_paths.yaml` (that file holds only `alpaca_equity_bracket_v1`).
  Under OPERATING-PLAN § 2 this is new mechanics, proven on ONE small trade at the first granted apply. It is not a soak and
  not a sample.

## Refinement rows (dated; none waits on paper trades)
- **LTR-TRIGGER-CLOSE-S0** (due 2026-11-04): offline Stage-0 test, net of the full cost stack, on the backtest trade history.
  It asks whether "close at trigger event E" beats hold, per trigger type, against a matched random-time-close control and
  under folds. A pass gives a MECHANICAL close rule, the real-money candidate. It also reconciles this result with
  DESK-LIFECYCLE-S0.
- **LTR-HOLD-BIAS-BRIEF** (due 2026-11-03): put the close-now vs hold price into the reviewer's packet (REVIEWER-BRIEF), with
  this record's −0.58 R/package hold result as the prior, and stop re-issuing an identical call on the same package every
  cycle.
- **LTR-GRADER-COVERAGE** (due 2026-11-05): a dated candle source (start/end, not the last 1,000 bars), `monitor()`-exit
  modelling or a realised-anchored default, `no_candles` symbols, a `/api/diag` read of `applied.jsonl`, and an applied
  stamp-back. Schedule `ltr_class_grade.py` under GRADE-EVERYTHING-CONTINUOUSLY.
- **LTR-CLASS-RULE-PACKAGE-N** (proposal to the manager): count the n of the MD-TRADE-DESK review_rule in PACKAGES (first call
  per package), not calls. Repeated calls on one package are one decision.
