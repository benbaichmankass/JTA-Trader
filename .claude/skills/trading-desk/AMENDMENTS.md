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
- 2026-10-28 · new_skill_sha: `5ddff669` · prior: `b46cd76d` · basis: operator decision on research evidence, not a graded lesson (popup to ask A1 "Advice-only until tested" ~21:07Z; DESK-LIFECYCLE-S0 #20967 whole-trade mgmt -0.159/-0.124 R vs hold), n=0 graded live calls of the extended classes · change: SKILL.md (not the brief) § 2, desk/LTR in-trade classes are advice only until each passes its own test; graduation rule (one class per PR, code list + mandate list, cites the passed test) · PR #21026
