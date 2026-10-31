# Brief amendment log — DESK-BRIEF.md

> **Doc status:** `unknown` · category `instruction` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

> CLAUDE-GRADE-LOOP (operator 2026-10-26). Every change to the brief after 2026-10-27 is a versioned
> amendment made by a PR from `/perf-followup` Track 2 (or a lane fixing a mechanical defect), never a
> silent edit. One line per new version. `new_skill_sha` is the brief's git blob sha AFTER the change
> (`git hash-object <brief>`), which is the `skill_sha` the next reviews/wakes record, so the grader
> splits outcomes on it. `basis` names the graded population the change rests on, with its `n=` (a
> mechanical fix states `basis: mechanical, n=0` and what broke). Checked weekly by
> `scripts/ops/check_claude_grade_loop.py` (weekly-audit C13).

<!-- one line per amendment, newest last:
- YYYY-MM-DD · new_skill_sha: `<8+ hex>` · prior: `<8 hex>` · basis: <grader + window>, n=<k> <stratum> · change: <one line> · PR #<n>
-->
- 2026-10-28 · new_skill_sha: `0a28d1c9` · prior: `e7652732` · basis: operator re-authorization, not a graded lesson (popup to ask A2 "Yes, one probe on bybit_1" ~21:07Z; both 10-27 probes risk-rejected unfilled), n=0 · change: DESK-BRIEF.md § 3a, mechanics probes capped at three (desk_write.PROBE_MAX 2 -> 3) · PR #21028
- 2026-10-28 · new_skill_sha: `77140315` · prior: `637bc3f0` · basis: operator decision on research evidence, not a graded lesson (popup to ask A1 "Advice-only until tested" ~21:07Z; DESK-LIFECYCLE-S0 #20967 whole-trade mgmt -0.159/-0.124 R vs hold), n=0 graded live calls of the extended classes · change: SKILL.md (not the brief) § 2, desk/LTR in-trade classes are advice only until each passes its own test; graduation rule (one class per PR, code list + mandate list, cites the passed test) · PR #21026
- 2026-10-30 · new_skill_sha: `6bb0e661` · prior: `1933a5c1` · basis: DESK-AM-REFOCUS diagnosis, n=136 desk rows (0 in-trade) + n=240 live reviews · change: SKILL.md § 2 states the in-trade role is the desk's discretionary judgement on every open trade, run as the live review with context_v3 + forecast · PR (this lane)
- 2026-10-31 · new_skill_sha: `ee7e37cb` · prior: `0a28d1c9` · basis: operator decision, not a graded lesson (popup 2026-10-30 ~22:30Z, verbatim "We can lift it completely if we have a protocol for trade desk hand-offs"; DESK-AM-REFOCUS § 1.5: 126 of 136 desk rows no_trade under the 60-min cap), n=0 graded multi-hour desk trades · change: DESK-BRIEF.md, the live max_hold_min <= 60 cap is removed (optional time stop); price on the row of the hold the thesis needs; § 3a′ the hand-off record (invalidation_px + exit_plan -> compiled forecast) · PR (DESK-HANDOFF-PROTOCOL)
- 2026-10-31 · new_skill_sha: `efc27cfd` · prior: `6bb0e661` · basis: operator decision, not a graded lesson (popup 2026-10-30 ~22:30Z, verbatim "We can lift it completely if we have a protocol for trade desk hand-offs"; DESK-AM-REFOCUS § 1.5: 126 of 136 desk rows no_trade under the 60-min cap), n=0 graded multi-hour desk trades · change: SKILL.md § 0 rule 1, no max-hold cap; the hand-off protocol (desk_handoff, judgement_cadence coverage, desk_orphan flag) · PR (DESK-HANDOFF-PROTOCOL)
- 2026-10-31 · new_skill_sha: `b30f4575` · prior: `f13c3a38` · basis: operator decision, not a graded lesson (popup 2026-10-30 ~22:30Z, verbatim "We can lift it completely if we have a protocol for trade desk hand-offs"; DESK-AM-REFOCUS § 1.5: 126 of 136 desk rows no_trade under the 60-min cap), n=0 graded multi-hour desk trades; plus mechanical n=3 (step 0: could_not_look) · change: SHORT-HOLD-BRIEF.md step 1 could_not_look is judged (operator_ask), step 1b handoff_verdict confirm/revise/exit on a desk trade, step 4 hold for the thesis · PR (DESK-HANDOFF-PROTOCOL)
