# Programme 04 Macro Sleeve: audit as of 2026-10-16

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../../../DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md) · manager programme audit 2026-10-16 (input to the backlog lanes and the 2026-10-20 programme review) · **Tier-1: nothing here changes a config, a roster or an order path.**

## 1. Intent
These come from `docs/research/programmes/04-MACRO-SLEEVE.md` (§1–2). The programme serves milestone M28 (active), M29 (dormant) and M36 (a dormant umbrella that is due to be retired).
- **Goal:** build a macro sleeve on a weeks horizon, trading debit verticals on `alpaca_options_paper`. Each conviction axis has to earn net return offline against the naive floor (all-long on the same dates at the same cost).
- **Q1:** what does the valuation axis earn at a cost the sleeve would really pay?
- **Q2/Q3:** which release surprises carry a drift after the release that survives a split into sub-periods, a placebo test, a second instrument and costs? Does a confirmed drift make a conviction axis?
- **Q4/Q5:** do prediction-market surprises (WEPE gate G2/G3) or news (NEWS-ALPHA) add an axis?
- **Q6/Q7:** should M29 wake, and can an executor plus a mechanical soak on `alpaca_options_paper` express a passed axis?

## 2. What has been done
**Q2 (release drift): ANSWERED.** The drift is statistically real, but the trade fails the net-of-cost rule.
- **Base study:** `RQ-20261014-de02-04` (10-14) passed. PPI m/m against ES=F, n=139, h3 IC −0.281, t_eff −3.43.
- **Stability (both halves pass):**
  - `4a4c-01` (2021 onward, 10-15) passed: n=68, h3 t_eff −2.05. That is just over its 2.0 bar, and h5 failed at −1.44.
  - `4a4c-02` (before 2021) passed: n=71, h3 −2.79, h5 −2.59.
- **Placebos (both clean):**
  - `4a4c-03` (base bar shifted −10 trading days) failed: n=140, h3 −0.20. It was run twice, in runs 38805638615 and 38843467501.
  - `77dc-02` (+10 days) failed: n=139, h3 −0.72.
- **Second instruments:**
  - `4a4c-04` NQ=F passed: n=139, h3 −2.93.
  - `4a4c-05` ZN=F failed: n=139, wrong sign (+0.86 / +1.24). There is no rates channel.
- **Net of cost:** `4a4c-06` (10-16) **failed**. It traded a sign book on ES with a 3-day hold at 12.5 bps round trip, n=118.
  - Net mean +0.221% per trade, t 1.53, below the 2.0 bar.
  - Book minus the all-long floor: −0.120%, t −0.59.
  - The all-long floor itself returned +0.341%, t 2.41.
  - Going short on hot prints gives back the equity drift.
- **Family breadth:** `4a4c-07` core CPI (n=139, best t −1.41) and `4a4c-08` core PCE (n=136, wrong sign) both failed.
- **Family total:** 1 of 15 kinds passes (the 13 earlier kinds are `1414-10/11/12`, `65cc-01..05`, `de02-02..06`). With 45 tests, PPI's p≈0.0006 still clears the Benjamini-Hochberg (BH) multiple-testing threshold of ≈0.0011.

**Q1 (valuation at real cost): OPEN.**
- The only evidence is at zero cost: n=1,104, calibration_rank −0.0037, edge vs baseline −0.0047.
- `RQ-20260929-001` (09-29) returned NOT_YET: no conviction band with n≥88 reached +0.02. The 0.50–0.75 band (n=308) was −0.0087 against baseline.
- `RQ-20260928-010` is blocked.

**Q3 (event-scored axis): never run.** `4a4c-09` is blocked, and so is `RQ-20260928-009`.

**Q4: ANSWERED for now.**
- `RQ-20261009-903` failed at paired n=68.
- `RQ-20261012-904` passed as an instrument (830 questions).

**Q5: never had a unit run.** All 14 units are blocked.

**Q6/Q7:** no unit, by design.

## 3. Queue state
I attributed units by theme `macro` or a roadmap reference to M28/M29, and checked titles for valuation and thesis units.
- **Done:** 18 theme-macro units, plus `RQ-20260929-001`.
- **Queued:** 7. Six of those already have results in `research/results/` but were never graded: `4a4c-03/05/06/07/08` and `77dc-02`. The seventh, `RQ-20260928-023`, is the oldest queued item (last dispatched 09-29). It runs the monthly valuation backfill but has no research_unit input, so no attributed result ever lands and it cannot be graded.
- **Blocked: 16 with theme macro**, plus `RQ-20260928-009` (no theme):
  - **14 are NEWS-ALPHA units `5bd1-01..14`.** All 14 need the row `NEWS-ALPHA-HARNESS`. Units 02–08 and 10 also need `-CORPUS` and `-FEATURES`; 01 and 09 need `-FEATURES`. Units 11, 12 and 13 need `-SRC-FOMC`, `-SRC-EDGAR` and `-SRC-WIKI`. Unit 14 also needs unit 02 to pass. Every one of those lever rows is `queued` with no lane, and the last update was 2026-10-12.
  - **`RQ-20260928-010`** is blocked because `macro-valuation-backfill.yml` takes no `research_unit` input and lands no E5 research record. The row `MACRO-BACKFILL-E5` is `queued` with no lane (10-14).
  - **`4a4c-09`** is blocked until `4a4c-06` passes. It **can no longer clear**, because `-06` failed.

## 4. Misalignments and problems
- **The verdicts have not been read.** `4a4c-06` decides the programme, but the unit still reads `queued`. As a result, `4a4c-09`, the row `MACRO-EVENT-AXIS-HARNESS` (queued) and M28's `next` still describe a branch the plan says to retire.
- **`4a4c-03` was dispatched twice.** That is a wasted run and points to a dispatcher or stamping gap.
- **The plan's W1 build did not move.** `MACRO-BACKFILL-E5` has had no lane since it was planned. Q1 and `RQ-20260928-023` are stuck on the same defect.
- **The news programme will miss its own date.** None of its 14 units can run until the harness, corpus and features rows are built, and none of those is staffed. The readout due 11-09 (`NEWS-ALPHA-PROGRAM`, `blocked`) is not reachable on the current path.
- **The plan and milestone text are out of date:**
  - The 04 doc §1 says "1 of 13" and the confirmation set is "runnable now".
  - M28 `where` says "4a4c-01..06 queued".
  - `MACRO-RESHAPE` (queued, owned by a lane from September, last touched 10-11) has been superseded by P4 and was never closed.
  - M36 `next` says "Retire the umbrella" and that has not happened.
- **`alpaca_options_paper` cannot measure the sleeve's live number.** Its roster is three technical legs (`slv_trend_1h`, `slv_pullback_1d`, `gdx_pullback_1d`). The sleeve is `execution: shadow` and has no options executor.
- **The PI-CAA05-0003 cleanup item may not need a build.** It is `queued`, waiting on a rescore expected to come back KILLED. The zero-cost run, which the plan calls the most favourable case, is already negative. This is an inference: I did not check the harness to confirm cost cannot raise calibration_rank.

## 5. Recommended next 5 days (to Tue 2026-10-20)
1. **[build row] Grade the six units that have landed but are ungraded, and retire Q3.**
   - First step: run research-ops grading on `4a4c-03/05/06/07/08` and `77dc-02`.
   - Then move `blocked/RQ-20261014-4a4c-09` to `retired` with the reason "-06 FAIL: book −0.12% vs floor, t −0.59, n=118".
   - **STOP** the row `MACRO-EVENT-AXIS-HARNESS` (mark it killed).
   - Record the M29 wake read as FAIL, so M29 stays dormant (Q6).
2. **[decision for operator] Decide where the PPI lead goes.**
   - Option (a): close Q2 as "a real drift in equities that a long/short book cannot monetise".
   - Option (b): pre-register one new unit, an all-long book on ES that skips hot prints, scored against the floor. This idea came after seeing the data, so its prior is low and it needs its own rule.
   - First step: put both options in the brief, using the `-06` numbers above.
3. **[build row] Staff `NEWS-ALPHA-HARNESS`, then `-CORPUS` and `-FEATURES`.** These rows unblock 13 of the 14 news units (unit 14 also needs unit 02 to pass). This is the only remaining source of new M28 axes, so it has the highest option value.
   - First step: dispatch one lane on `NEWS-ALPHA-HARNESS` (`scripts/research/news_alpha_ic.py`).
   - Alternatively, ask the operator to move the 11-09 readout date.
4. **[decision for operator] Q1: build `MACRO-BACKFILL-E5`, or close PI-CAA05-0003 as killed on the zero-cost record?**
   - First step: confirm in `thesis_backtest.net_return` that cost is never negative, then propose the close.
   - If the close is chosen, **STOP** `RQ-20260928-023`, since it can never be graded.
5. **[build row] Bring the docs up to date.**
   - Update 04 §1–4 and M28 `where`/`next` to the new state.
   - Close `MACRO-RESHAPE` as superseded.
   - Retire M36.
   - File the double dispatch of `4a4c-03` in the pipeline.
6. **No action on Q7 or `alpaca_options_paper`** until an axis passes Gate 1.

CONFIDENCE: Checked directly: every result record listed (verdicts, n, IC/t, sign-book numbers), unit statuses and blockers, checklist row states, the M28/M29/M36 text, the account roster and the sleeve's execution mode. Inferred: the claim that cost cannot raise calibration_rank, the low prior on the skip-hot-prints idea, and the cause of the double dispatch.