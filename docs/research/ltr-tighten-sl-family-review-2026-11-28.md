# ltr-tighten-sl family review: verdict A (tested wrong), not retired

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PRIMARY (Tier 1 evidence; no config, roster, order or mode)

**Gates this adds or changes:** none.

**Asked by:** manager 28a, 2026-11-28 ("The ltr-tighten-sl family_review record: write it properly; there's no rush").
**Protocol:** `scripts/research/family_retirement_policy.yaml` (v3), the six items plus the lever map.
**Outcome:** the review started as a C (retire) draft and **did not survive its own protocol**. Item 4 (outside evidence) and an
in-repo measurement both name conditions none of the graded units tested. That is **verdict A**, which the policy handles with a
pre-registered re-test, not a retirement record. The re-test is **[`RQ-20261128-f1a5-01`](../../research/queue/RQ-20261128-f1a5-01.yaml)**
(iteration 5). No file is written under `research/family_reviews/`, because `family-retirement-guard` refuses any record whose
verdict is not C.

## What was graded (population: 8 committed Stage-0 corpora, 3,921 of 4,076 trades priced, 370 weeks)

The harness is `scripts/research/ltr_action_trigger_s0.py`, net of the full cost stack (fee, slippage, funding pro-rata). All units
were graded under RULE-AM-RISK-ADJUSTED-V1 with 200 matched random-time controls. The baseline book's maxDD is 70.43 R.

| unit | lever family | arm | n fired | mean dT vs hold (R) | 95% CI | dd cut | folds held | verdict |
|---|---|---|---|---|---|---|---|---|
| #21003 (`comms/research/ltr_tighten_optimize/verdict.json`) | timing | early cell | — | -0.041 | -0.087..-0.005 | — | — | fail |
| RQ-20261117-43b6-05 | timing | BE+0.25 R @ r_milestone (late) | 1,403 | -0.0777 | -0.119..-0.037 | -4.7% | 0/6 | fail |
| RQ-20261122-c8e1-01 | trigger | BE+0.25 R @ giveback | 380 | -0.1027 | -0.177..-0.032 | -5.5% | 0/6 | fail |
| RQ-20261122-c8e1-01 | trigger | BE+0.25 R @ momentum_flip | 169 | -0.075 | -0.181..+0.011 | -0.3% | 0/6 | fail |
| RQ-20261122-c8e1-01 | trigger | BE+0.25 R @ near_target | 388 | -0.0011 | -0.049..+0.049 | -0.1% | 0/6 | fail |
| RQ-20261122-c8e1-01 | trigger | BE+0.25 R @ structure_break | 20 | -0.3129 | -0.687..-0.065 | 0% | 0/6 | fail (n 20, under V1's 39 floor; graded fail by the harness) |
| RQ-20261122-d4a9-01 | action_bounds | -0.75 R @ r_milestone | 1,426 | -0.0111 | -0.025..+0.001 | -3.6% | 0/6 | fail |
| RQ-20261122-d4a9-02 | action_bounds | -0.5 R @ r_milestone | 1,426 | -0.0131 | -0.032..+0.004 | -2.7% | 0/6 | fail |
| RQ-20261122-d4a9-03 | action_bounds | 0.0 R @ r_milestone | 1,424 | -0.0473 | -0.081..-0.016 | -1.1% | 0/6 | fail |

The numbers come from the committed result rows under `research/results/<unit>/` (dd cut is negative where the drawdown grew). Across
the three d4a9 levels, the loss shrinks as the stop is moved less far in. The d4a9-01 arm beat the random tighten on mean per-trade R (edge CI +0.013..+0.036). It still failed R2
and R4, which are judged on the risk cut.

## The six items

1. **Test-design review.**
   - *The first flaw a skeptic raises:* every trigger was a **price event** that fires only on trades that already moved
     (r_milestone needs +1 R; giveback, near_target and the rest need a favourable excursion first).
   - *Why it matters:* the book's drawdown is made of full -1 R losers that never reach those triggers, so R2 (≥ 15% DD or CVaR cut)
     could not pass by construction on the trades the tests touched.
   - *Does it apply?* **Yes.** It is a test-design flaw for the family-level question: "can a stop tighten cut this book's risk?" was
     tested only on the subset of trades least able to answer it.
   - window_vs_mechanism: the window is the full Stage-0 span (370 weeks, 6 calendar folds) and contains the mechanism.
   - metric_vs_baseline: the random-time control on the same trades is the baseline, and chance cannot beat it at 200 draws.
   - label_vs_payoff: graded in R, net, as traded.
   - gate_vs_size: fixed size, no gate.
   - harness_validity: no known defect at run time (self-test includes a planted positive and a planted negative).
   - reference_distribution: trade bootstrap plus 200 matched random books.
2. **Breadth.** 6 calendar folds (≥ 4 needed) and 8 legs over 4 symbols. Every result row carries `power_state: accruing`. The units
   declared an *inferred* 0.8 power at a 0.05 R MDE, and the per-trade CIs (half-width ≈ 0.013 R at n ≈ 1,400) are consistent with
   it. No measured power exists, and I did not write one.
3. **Positive control.** The same harness has graded PASSes on the same corpus for sibling actions: sl_to_structure (RQ-20261113-ed2b-03,
   RQ-20261119-018/-019) and tp_pull_in (RQ-20261117-43b6-04). It can therefore detect a beneficial in-trade action on this data.
4. **Outside evidence.** Three sources, two of them primary:
   - [Kaminski & Lo (2014), *When do stop-loss rules stop losses?*, J. Financial Markets 18:234-254](https://dspace.mit.edu/handle/1721.1/114876)
     (primary). Under a random walk, stops always lower expected return. They add value only when returns are serially correlated
     (momentum). **Names a condition:** serial correlation or regime.
   - [Lo & Remorov (2017), *Stop-loss strategies with serial correlation, regime switching, and transaction costs*, J. Financial Markets 34:1-15](https://dspace.mit.edu/handle/1721.1/107017)
     (primary). Tight stops lose to trading costs. Wider stops pay in regime-switching markets where volatility rises in the adverse
     regime and switches are infrequent. **Names an untested condition:** an adverse volatility-regime switch.
   - [Clare, Seaton, Smith & Thomas, *Breaking into the blackbox: trend following, stop losses and the frequency of trading* (S&P 500)](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf).
     Stop-losses aimed at limiting drawdown by time or magnitude were not advantageous on the S&P 500. This is consistent with our
     FAILs, and the authors caution that the result is universe-specific.
   - In-repo, the queued `RQ-20261125-c7e3-05` (ml-brackets) measured on 108,922 dev trades that a **uniformly placed** tighten beat
     HOLD (+7,180 R vs -10,282 R). First-bar fires cost -16,376 R there. The value sits after the trade develops, so trade age is an
     untested condition. That is a different corpus and action (AM counterfactual, tighten_half): it motivates the condition and is
     not evidence for the arm.
   - Two sources name untested conditions, so the verdict is **A**.
5. **Not-tested dimensions.**
   - Covered by f1a5-01:
     - conditioning (regime): `vol_expansion`.
     - holding_period and horizon (trade age): `age`.
   - Already tested: cost (full stack on every unit), sizing (fixed R, BOOK-SIM-REAL-SIZER owns USD sizing), exit (the recorded exit is
     the hold arm; tp/partial siblings are their own classes) and label (R, net).
   - Instrument: 8 legs over crypto (ADA, ETH, SOL, XRP, and ml_entry's pool) plus IAUM; equities beyond IAUM are untested and stay open after f1a5-01.
6. **Reason the idea would be dead.** Not stated: the mechanism is not shown dead. The best-supported reading is narrower. A tighten
   keyed to favourable price events cannot cut this book's risk, because the risk is in trades that never reach those events.

## Lever map after this review

| family (policy `ltr_class`) | state |
|---|---|
| trigger | price-event triggers tested (5 units). Age and regime triggers untested → f1a5-01 |
| timing | early and late cells tested |
| action_bounds | -0.75 / -0.5 / 0.0 / +0.25 R tested at r_milestone; -0.5 R carried into f1a5-01 |

**Next:** f1a5-01 grades under its registered rule. If it FAILs, the two conditions count as tested, and a C record can be drafted
again, citing this document and the f1a5-01 result. If it PASSes, a confirming out-of-time unit follows before any Tier-3 proposal.
