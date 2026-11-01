# Checklist backfill proposal (2026-11-01) -- PROPOSAL ONLY, nothing dated or dropped

Population: 603 non-terminal rows (state not done/dropped) in docs/claude/work/checklist/ on 2026-11-01. Rules R1-R4 / D1-D3: `scripts/ops/checklist_backfill_propose.py` docstring. File: `proposal.jsonl`.

- propose DATE: 598  |  propose DROP: 5
- owner null today -> `manager` (mechanical): 102
- roadmap needs review (unmapped or id-prefix heuristic): 0
- already overdue under their legacy date (observation.due_by < 2026-11-01): 169
- no date at all today: 253

## By state
| state | rows | date | drop | first due | last due |
|---|---|---|---|---|---|
| blocked | 17 | 17 | 0 | 2026-11-08 | 2026-11-08 |
| in_flight | 25 | 25 | 0 | 2026-11-03 | 2026-11-03 |
| landed_unproven | 338 | 337 | 1 | 2026-11-01 | 2026-12-11 |
| queued | 223 | 219 | 4 | 2026-11-02 | 2026-11-12 |

## By milestone (a row counts once per milestone it resolves to)
| milestone | rows | drop | latest proposed due |
|---|---|---|---|
| L-OPS | 98 | 1 | 2026-11-26 |
| L-LADDER | 92 | 0 | 2026-11-15 |
| L-ATM | 88 | 1 | 2026-11-22 |
| L-DESK | 75 | 0 | 2026-11-30 |
| M25 | 56 | 0 | 2026-11-12 |
| L-PROP | 51 | 1 | 2026-12-11 |
| M39 | 36 | 0 | 2026-11-15 |
| L-AM-STANDARD | 25 | 0 | 2026-11-12 |
| L-ML-LIVE | 25 | 0 | 2026-11-09 |
| L-PROGRAMMES | 17 | 0 | 2026-11-08 |
| M40 | 13 | 0 | 2026-11-12 |
| M23 | 11 | 0 | 2026-11-22 |
| M28 | 10 | 0 | 2026-11-10 |
| M6 | 9 | 0 | 2026-11-08 |
| L-REGIME | 9 | 0 | 2026-11-11 |
| M20 | 9 | 1 | 2026-11-08 |
| M22 | 8 | 1 | 2026-11-12 |
| L-DATA | 6 | 0 | 2026-11-12 |
| M21 | 5 | 0 | 2026-11-10 |
| M18 | 4 | 0 | 2026-11-06 |
| M14 | 4 | 0 | 2026-11-10 |
| L-TIMEFRAMES | 4 | 0 | 2026-11-12 |
| M27 | 3 | 0 | 2026-11-05 |
| L-DESK-V1 | 1 | 0 | 2026-11-03 |
| M29 | 1 | 0 | 2026-11-04 |
| M16 | 1 | 0 | 2026-11-08 |

## Proposed drops (each needs the manager's yes; reason is the evidence)
- **E36** [queued] -- D1 never touched since the reset (no updated_at), queued, no lane -- The pairs sleeve is SINGLE-ACCOUNT by construction, so 'push a passing pair to live money' is a build, not a config flip
- **E9** [queued] -- D1 never touched since the reset (no updated_at), queued, no lane -- Retire what the reset orphaned
- **EXIT-HEAD-PULLBACK-DRIVER** [queued] -- D3 queued, no lane/rank/PR, untouched 14d, only in M20 (milestone status closed) -- Lever: committed driver running backtest_pullback.py through the exit-head replay (sibling of exit_head_prop_swap_feasib
- **LTR-6-APPLY-PATH** [queued] -- D2 note says 'superseded by LTR-6R-APPLY-PATH' (landed_unproven); that row exists -- Live trade review: amend_position_sl.py --mandate/--evidence, provenance live_review_mandate, min_buffer_atr + once-per-
- **PHONE-POSITIONS-DIV** [landed_unproven] -- D2 note says 'superseded by BREAKOUT-POS-UNPARSED' (landed_unproven); that row exists -- Phone executor: parse Breakout's DIV-grid Positions view (no <table>) by header label, fail-closed

## Daily load of the proposed schedule (rows per due date, first 16 days)
- 2026-11-01: 20
- 2026-11-02: 76
- 2026-11-03: 77
- 2026-11-04: 53
- 2026-11-05: 57
- 2026-11-06: 96
- 2026-11-07: 53
- 2026-11-08: 58
- 2026-11-09: 29
- 2026-11-10: 21
- 2026-11-11: 21
- 2026-11-12: 22
- 2026-11-14: 1
- 2026-11-15: 6
- 2026-11-20: 1
- 2026-11-22: 3
