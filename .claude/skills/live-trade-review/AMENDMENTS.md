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
- 2026-10-26 · new_skill_sha: `7e85d854` · prior: `a404f827` · basis: mechanical, n=0 · change: SKILL.md § 4 `trigger.event`+`trigger.level` must be the due trigger exactly as given (schema level now number|string|null; GLD wedge was re-reviewed 10x because rows recorded a null level) · PR #20468
- 2026-10-26 · new_skill_sha: `6a3b3120` · prior: `92470935` · basis: mechanical, n=0 · change: REVIEWER-BRIEF.md step 3 copy event AND level; re-embedded schema (level may be a string) · PR #20468
- 2026-10-28 · new_skill_sha: `104db11a` · prior: `76044d3f` · basis: mechanical, n=0 (label clarity: a `route: recommended` close on LR-20261028T1018Z-pkg-5277d9b977994968 was executed, as designed, by the rows watcher) · change: SKILL.md Step 5 states `recommended` is DISPATCHED on every account under MD-TRADE-DESK / MD-LIVE-TIGHTEN-SL; advice only = `none` / `operator_ask` · PR #20897
- 2026-10-28 · new_skill_sha: `d8e8e4e7` · prior: `fe47add9` · basis: mechanical, n=0 (same) · change: REVIEWER-BRIEF.md step 6 the same statement · PR #20897
