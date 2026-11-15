# RQ-20261101-a24c-01 graded: FAIL (2026-11-12, lane ML-ENTRY-UNIVERSE-LEVER)

Window 2025-10-01..2026-10-31 (amended before the run), frozen ml_decision_entry_v1 (tau 0.10), 49 costed Bybit-listed 60-perp symbols,
spread = Bybit quoted floored at one tick, sqrt impact Q=5000, fee+funding as c692-01. Ledger claim: read 13 of the ENTRY family, point hurdle t >= 1.70.

- Dev rule (dev folds only): every C negative (C10 admits none; 15: -0.098; 20: -0.062; 30: -0.048; 50: -0.070; inf: -0.104). C* = 30 bps, U = 19 symbols.
- Arm A forward: mean net R **-0.0492** per decision, n=4272, se 0.0169 (t about -2.9), 19 symbols. FAIL by the registered rule (needs >= 0 and t >= 1.70).
- Reported only: 5 bybit_2 coins +0.0156 (n=971, se 0.036); flat 3 bps on U -0.0103; impact sensitivity Q x0.25 -0.0265, Q x4 -0.0944.
- Arm B did not evaluate: the harness labelled its cost basis "net_of_cost", which cost_gate rejects (needs net/realized). Fixed in this PR (label "net").
  The verdict does not depend on it (arm A fails on its own); arm B was not re-run so the ledger gets no extra read.
- Meaning: widening ml_entry to the passed population does not add edge once each symbol pays its own spread and impact; the
  liquid majors alone are not enough either. No Tier-3 widening packet. bybit_2 keeps its 5 coins.
