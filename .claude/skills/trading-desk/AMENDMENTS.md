# Brief amendment log — DESK-BRIEF.md

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
