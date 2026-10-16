# research/family_reviews/ — one file per RETIRED research family

A cell or unit FAIL closes the **configuration** it tested. Retiring the **family** (the idea itself) needs
`research/family_reviews/<family>.yaml` here, in the shape `scripts/research/family_retirement_policy.yaml` sets
(thresholds there; PROVISIONAL until lane IDEA-REVIEW-1016's protocol lands). `family-retirement-guard`
(`scripts/research/family_retirement_guard.py`) refuses a retirement without a valid record.

```yaml
family: giveback_stop                 # the idea, named the way the work names it
decided_at: '2026-10-20'
reviewed_by: <lane / session id>
test_design_check:                    # did we test it RIGHT? `flawed` => fix the test, do not retire
  verdict: sound
  notes: "labels, horizon, cost stack, leakage and power re-checked: ..."
breadth:                              # what FAILED, across what
  configs: [gb1R_afterMFE1R, gb1R_afterMFE2R, census_keyed_q80]
  windows: ['2024-01..2025-06', '2025-07..2026-09 (not chosen on)']
  instruments: [xrp_pullback_2h, ada_pullback_2h]
  # single_instrument_why: "..."      # only when one instrument is all there is
outside_evidence:                     # if the idea were viable, someone outside would say how to do it better
  - {source: "<paper / repo / write-up>", url: "<link>", finding: "what it says about doing this better"}
  - {source: "...", url: "...", finding: "..."}
reason_idea_dead: >-
  Why the IDEA is dead, not just why these configs failed.
```

Cite a valid record on any line that states a family-level closure: `family_review: <family>`.
