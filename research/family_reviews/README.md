# research/family_reviews/ — one file per RETIRED research family

A cell or unit FAIL closes the **configuration** it tested. Retiring the **family** (the idea itself) needs
`research/family_reviews/<family>.yaml` here, in the shape `scripts/research/family_retirement_policy.yaml` sets
(the six-item protocol from lane IDEA-REVIEW-1016, PR #18560, plus the v3 lever map: retirement only when every lever family
has been tested at declared power net of the full cost stack -- operator 2026-11-01, "Once we've proven conclusively that we
cannot find an edge on a certain strategy, we can retire it, and until then it needs to be an iteration."). `family-retirement-guard`
(`scripts/research/family_retirement_guard.py`) refuses a retirement without a valid record.

```yaml
family: giveback_stop                 # the idea, named the way the work names it
decided_at: '2026-10-20'
reviewed_by: <lane / session id>
verdict: C                            # A tested wrong -> re-test · B not testable -> a row · only C retires
subject_kind: strategy_leg            # strategy_leg | ml_model | ltr_class | lever_family (policy.lever_families)
lever_map:                            # (v3, 2026-11-01) LEVER EXHAUSTION: every lever family of the kind, each with a
  entry:   {tested: [{id: RQ-..., n: 210, power: 0.8, verdict: fail, cost_basis: full}]}   # counted full-cost test,
  exit:    {tested: [...]}                                                                  # or irrelevant_because.
  session: {irrelevant_because: "24/7 crypto venue; no session structure in the signal"}    # Never an attempt count.
test_design_review:                   # (1) did we test it RIGHT?
  first_skeptic_flaw: "the flaw a skeptic raises first, and why it does not apply"
  checks:                             # every one answered
    window_vs_mechanism: "..."        # did the window contain the effect?
    metric_vs_baseline: "..."         # can the baseline be beaten by chance? (macro-F1 vs a class prior can)
    label_vs_payoff: "..."            # an unweighted label on a skewed payoff?
    gate_vs_size: "..."
    harness_validity: "..."           # lookahead / a known defect at the time of the run?
    reference_distribution: "..."
breadth:                              # (2) every entry carries n + power; indeterminate counts zero
  primary_axis: "trail distance"
  configs: [{id: gb1R_afterMFE1R, n: 210, power: 0.8, verdict: fail}, ...]          # context; no count retires (v3)
  windows: [{id: '2024-01..2025-06', n: 120, power: 0.7, verdict: fail}, ...]       # >= 2 disjoint, or folds: >= 4
  instruments: [{id: xrp_pullback_2h, n: 120, power: 0.7, verdict: fail}, ...]      # >= 2, or instrument_specific_why
positive_control: {test: RQ-..., passed: true}   # or none_exists_because: "..."    # (3)
outside_evidence:                     # (4) >= 3 sources, primary where possible -- or, if none exist, the searches
  sources:
    - {source: "<paper / repo / model card>", url: "<link>", primary: true, finding: "when it works"}
    # names_untested_condition: true on any source makes this verdict A, and the guard refuses the retirement
  # searches: ["query 1", "query 2", "query 3"]
not_tested:                           # (5) each: covered_by <unit/row>, or irrelevant_because <reason>
  horizon: {covered_by: RQ-...}
  instrument: {irrelevant_because: "..."}
  conditioning: {...}
  cost: {...}
  label: {...}
  sizing: {...}
  exit: {...}
  regime: {...}
  holding_period: {...}
reason_idea_dead: >-                  # (6) ONE sentence about the mechanism, not "every cell failed"
  the edge was lookahead and no independent test of the concept exists
```

Cite a valid record on any line that states a family-level closure: `family_review: <family>`.
