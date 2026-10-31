# E4-PROP-SIM — plan, committed BEFORE any cell is run

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane DESK-18G-EVENT-ENTRIES

Rule: RULE-P5-GATE-BRK-PER-LEG-V2 (unit RQ-20261029-9a2c-01), applied unchanged (thresholds, ceilings c = 1 - 2F/W, n >= 88, 5 seeds x 1000 lives,
dd switch 0.8, `--sizing start`, the account's configured risk_pct, ruleset leverage caps, CONTESTED handling). Harness = docs/research/prop-replacement-2026-10-30
(`run_cells.sh`, `aggregate.py`, `scripts/research/prop_ev_sim.py`), copied here with the leg name and paths changed only.

Choices made before running (not tuned to a result):
* Leg = **E4 as ONE leg** (all six symbols, one position at a time, the simulator's `leg busy` skip, as live suppresses re-entry on a leg); the rule prices "each leg ALONE".
  A six-leg per-symbol book is an unregistered diagnostic, run only on the primary cell and not graded.
* Ledger = the frozen E4 trades scored in PR #21720: DEV 2025-11-01..2026-09-15 (763 events) + held-out 2024-11-01..2025-10-25 (856), 1,619 filled brackets, gross R before cost
  (`scripts/research/e4_prop_ledger.py`; mean driver net R ties to the scored S1: DEV -0.0061, held-out +0.0220). The week 2025-10-25..11-01 is in neither window and is not in the ledger.
* Windows: **full** ledger (1.87 years, the analogue of the rule's "3y" primary) and **trailing 365d** (entries >= 2025-09-14; 847 trades, 763 DEV + 84 held-out).
* Arms: current stack (primary: 11.0 bps fee + 3.0 slippage + 1 bp / 8h funding as swap 0.0003/day) and venue stack (each firm's commission/swap), exactly as run_cells.sh in the prior lane.
* Accounts: breakout_2 (0.35%, c 0.889), tradeify_1 (0.5%, c 0.750), velotrade_1 (0.5%, c 0.730). Lev cap 5 on all three.
* Ledger window caveat: 1.87 years, not 3 years; E4 has no earlier ledger under this exact definition. Stated in the verdict.
Nothing here changes a roster, config, order or mode.
