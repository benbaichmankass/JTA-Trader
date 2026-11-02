# Checklist backfill proposal (2026-11-02) -- PROPOSAL ONLY, nothing dated or dropped

Population: 588 non-terminal rows (state not done/dropped) in docs/claude/work/checklist/ on 2026-11-02. Rules R1-R4 / D1-D3: `scripts/ops/checklist_backfill_propose.py` docstring. File: `proposal.jsonl`.

- propose DATE: 582  |  propose DROP: 6
- owner null today -> `manager` (mechanical): 0
- roadmap needs review (unmapped or id-prefix heuristic): 0
- already overdue under their legacy date (observation.due_by < 2026-11-02): 90
- no date at all today: 245

## By state
| state | rows | date | drop | first due | last due |
|---|---|---|---|---|---|
| blocked | 17 | 17 | 0 | 2026-11-09 | 2026-11-09 |
| in_flight | 35 | 35 | 0 | 2026-11-04 | 2026-11-04 |
| landed_unproven | 279 | 278 | 1 | 2026-11-02 | 2026-11-30 |
| queued | 257 | 252 | 5 | 2026-11-03 | 2026-11-15 |

## By milestone (a row counts once per milestone it resolves to)
| milestone | rows | drop | latest proposed due |
|---|---|---|---|
| L-OPS | 100 | 1 | 2026-11-26 |
| L-ATM | 92 | 2 | 2026-11-22 |
| L-DESK | 74 | 0 | 2026-11-30 |
| L-LADDER | 73 | 0 | 2026-11-15 |
| M25 | 50 | 0 | 2026-11-15 |
| L-ML-LIVE | 46 | 0 | 2026-11-13 |
| L-PROP | 40 | 1 | 2026-11-15 |
| M39 | 33 | 0 | 2026-11-15 |
| L-AM-STANDARD | 27 | 0 | 2026-11-12 |
| L-PROGRAMMES | 15 | 0 | 2026-11-08 |
| M40 | 12 | 0 | 2026-11-14 |
| L-DATA | 11 | 0 | 2026-11-15 |
| M23 | 9 | 0 | 2026-11-22 |
| M6 | 9 | 0 | 2026-11-09 |
| L-REGIME | 8 | 0 | 2026-11-13 |
| M28 | 8 | 0 | 2026-11-12 |
| M20 | 7 | 1 | 2026-11-15 |
| M22 | 7 | 1 | 2026-11-15 |
| M21 | 5 | 0 | 2026-11-12 |
| M14 | 5 | 0 | 2026-11-12 |
| M18 | 4 | 0 | 2026-11-08 |
| L-TIMEFRAMES | 3 | 0 | 2026-11-15 |
| M27 | 2 | 0 | 2026-11-08 |
| L-DESK-V1 | 1 | 0 | 2026-11-04 |
| M29 | 1 | 0 | 2026-11-08 |
| M16 | 1 | 0 | 2026-11-10 |

## Proposed drops (each needs the manager's yes; reason is the evidence)
- **E36** [queued] -- D1 reset-era row (id E<n>) never touched since the reset (no updated_at), queued, no lane -- The pairs sleeve is SINGLE-ACCOUNT by construction, so 'push a passing pair to live money' is a build, not a config flip
- **E9** [queued] -- D1 reset-era row (id E<n>) never touched since the reset (no updated_at), queued, no lane -- Retire what the reset orphaned
- **EXIT-HEAD-PULLBACK-DRIVER** [queued] -- D3 queued, no lane/rank/PR, untouched 15d, only in M20 (milestone status closed) -- Lever: committed driver running backtest_pullback.py through the exit-head replay (sibling of exit_head_prop_swap_feasib
- **LTR-6-APPLY-PATH** [queued] -- D2 note says 'superseded by LTR-6R-APPLY-PATH' (landed_unproven); that row exists -- Live trade review: amend_position_sl.py --mandate/--evidence, provenance live_review_mandate, min_buffer_atr + once-per-
- **LTR-CLOSE-CLASS-TEST** [queued] -- D2 note says 'superseded by LTR-TRIGGER-CLOSE-S0' (landed_unproven); that row exists -- Pre-registered disjoint-window test of the live-review close recommendation class (18 priced, +15.15R counterfactual on 
- **PHONE-POSITIONS-DIV** [landed_unproven] -- D2 note says 'superseded by BREAKOUT-POS-UNPARSED' (landed_unproven); that row exists -- Phone executor: parse Breakout's DIV-grid Positions view (no <table>) by header label, fail-closed

## Daily load of the proposed schedule (rows per due date, first 16 days)
- 2026-11-02: 27
- 2026-11-03: 49
- 2026-11-04: 90
- 2026-11-05: 53
- 2026-11-06: 70
- 2026-11-07: 27
- 2026-11-08: 76
- 2026-11-09: 46
- 2026-11-10: 21
- 2026-11-11: 20
- 2026-11-12: 23
- 2026-11-13: 20
- 2026-11-14: 21
- 2026-11-15: 33
- 2026-11-20: 1
- 2026-11-22: 2
