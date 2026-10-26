# Contract amendment log — live-trade-review SKILL.md + REVIEWER-BRIEF.md

> **Doc status:** `unknown` · category `instruction` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

> CLAUDE-GRADE-LOOP (operator 2026-10-26). Every change to SKILL.md or REVIEWER-BRIEF.md after 2026-10-27 is a versioned
> amendment made by a PR from `/perf-followup` Track 2 (or a lane fixing a mechanical defect), never a
> silent edit. One line per new version. `new_skill_sha` is the changed file's git blob sha AFTER the change
> (`git hash-object <brief>`), which is the `skill_sha` the next reviews/wakes record, so the grader
> splits outcomes on it. `basis` names the graded population the change rests on, with its `n=` (a
> mechanical fix states `basis: mechanical, n=0` and what broke). Checked weekly by
> `scripts/ops/check_claude_grade_loop.py` (weekly-audit C13).

<!-- one line per amendment, newest last:
- YYYY-MM-DD · new_skill_sha: `<8+ hex>` · prior: `<8 hex>` · basis: <grader + window>, n=<k> <stratum> · change: <one line> · PR #<n>
-->
- 2026-10-26 · new_skill_sha: `091da047` · prior: `3db7a2fc` · basis: operator grant, not a graded lesson (MD-TRADE-DESK, popup 2026-10-26 ~18:56-19:00Z), n=0 graded calls of the new classes · change: SKILL.md § 3b, the trade actions close / partial_close / move_tp / widen_sl / change_size / add_entry with reason + confidence + target + § 0.3 paper in scope ("All accounts now") · PR #20412
- 2026-10-26 · new_skill_sha: `92470935` · prior: `4e928c3d` · basis: operator grant, not a graded lesson (MD-TRADE-DESK), n=0 graded calls of the new classes · change: REVIEWER-BRIEF.md steps 5-6 + re-embedded schema for the trade actions · PR #20412
