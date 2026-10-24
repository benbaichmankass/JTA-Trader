# Manager handoff 2026-10-24 (evening): session_01EfjqotNYj6MppcEBqbGvkA → new

> **Doc status:** `unknown` · category `unknown` · last verified `never` · written 2026-10-24 ~21:25Z by the outgoing manager `session_01EfjqotNYj6MppcEBqbGvkA`

**Why I'm rotating:** context was about 627k at 21:19Z, near the ~650k threshold. Most of it was repeated PR-subscription notice text. **This is a slim handover:** follow `.claude/skills/manager/SKILL.md` § Start of session (Rotation case).

## Capacity
- Weekly usage was **26% at 18:19Z** (operator screenshot).
- **The budget is 80%.** The operator corrected the earlier "35%" mis-record on 2026-10-24, verbatim: "Wait, when was it decided that it was 35? It's 80 for the budget".
- The reset is recorded as Wed 2026-10-28 17:59Z (INFERRED UTC+2).
- 2–3 lanes at a time fit.

## Live lanes
| session | row | state |
|---|---|---|
| `session_01PTe7EDdMjXTYEDfPDDgGYe` | FIRST-PASSAGE-ON-PATHS (rank 1, Opus, $15) | Building the as-traded per-bar first-passage reader. At 21:17Z its tests were green and the 6-leg feasibility run was in progress. It unblocks RQ-20261024-09a6-01 and RQ-20261014-d6e7-06. It ships a HOLD PR with its own merge-slot claim, and you merge it. |
| `session_01LpzNqKr2gFgKfaN2GB4T69` | REMAINING-MOVE-HEAD (rank 2, Sonnet, $12) | Building the remaining-move quantile head and the pull-in-only TP replay. It unblocks 09a6-03. It was told not to edit first_passage.py. It ships a HOLD PR, and you merge it. |
| `session_017CC7HsxYRqXUoT5HYnDLWt` | RESEARCH-OPS-20261024-2047 | The assistant manager supervises it. Its PR is #19948 (draft). |

Both build lanes wake `session_01EfjqotNYj6MppcEBqbGvkA`, which is me. Re-point them to you: send each one a trigger.

## Open PRs needing the manager
- **#19951:** register, REMAINING-MOVE-HEAD in_flight. It self-lands.
- **#17895:** ops-flags. Never merge it. Subscribe to it.
- The older held PRs carried from earlier managers are unchanged and undispositioned: #18557, #17874, #17194, #16233, #14692, #12564, #12213, #12158, #12070, #11976, #11933. Some date from September. **A disposition pass is owed.**

## Operator decisions and directives this session (verbatim), all executed and recorded on rows
- **Weekly budget:** "It's 80 for the budget" (see Capacity).
- **MGC cap:** "1.5× equity (Recommended)".
  - #19926 merged as 29da9ba0. It covers the futures multiplier in the exposure ceiling, and ib_paper/ib_live max_gross_exposure_pct 1.5.
  - It is NOT deployed or observed. The observation is due 2026-11-07: the next ib_paper MGC entry is at most 1.5x equity notional.
  - Revert: revert 29da9ba0.
- **AI active trade management:** "I want to start sort of trying to merge our two top priorities and trying to get active management, like under AI management, and seeing like what kind of models we can build to help us like with the live management of trades and moving the brackets as conditions change."
  - Row ATM-AI-MERGE is done.
  - The plan merged as #19943 (1572e991): Programme 01 § "AI active trade management — the merged programme".
  - Rungs: A1/A2/B1/C1 (units 09a6-01..04 in blocked/) and D.
  - Builds: FIRST-PASSAGE-ON-PATHS (1, live), REMAINING-MOVE-HEAD (2, live), EXIT-ARM-CHOICE-CORPUS (3), PATH-FLOW-JOIN (4), and BRACKET-ADVISOR-SHADOW (5, Tier-2 proposal, needs an operator OK before it is built).

## What landed this session (all merged)
- **Live-parity instrument fixes:**
  - #19925: forming-era packages and pre-join bars.
  - #19930: window-end eval truncation.
  - The trader was never at fault, and no evaluations were missed.
  - Rows LIVE-PARITY-DIAG-1024 and LIVE-EVAL-GAP-1024 are landed_unproven. Observation due 10-26: the next daily parity run shows no lost bar at the window end, and divergences around 139, the known ADX residual.
- **MGC sizing:** #19927 (write-up) and #19926 (fix, see above).
- **Register PRs:** #19914, #19915, #19917 (handoff), #19918, #19921, #19922, #19928, #19940, #19941, #19947.

## Owed by the new manager
1. **Merge the two build lanes' HOLD PRs** when they are green. First verify the diff is research-only: no config/, no src/ runtime. Then set their rows landed_unproven and archive the lanes.
2. **Next dispatches**, by `checklist.py queue`:
   - EXIT-ARM-CHOICE-CORPUS (3) and PATH-FLOW-JOIN (4).
   - Sunday's RESULTS-GRADE-1025 and ML-READ-1025.
   - Monday's EXITS-ROUND2-1026.
3. **Put BRACKET-ADVISOR-SHADOW to the operator** as a Tier-2 popup when you get to it. Phase 0 shadows the confirmed rule levers.
4. **Live checks still owed:**
   - The ADA trade (stop 0.2053 on bybit_2/bybit_portfolio/bybit_1): its close reason should be SL and the trade should be graded.
   - The first closed-bar momentum trail or stale exit (MOMENTUM-LEVERS-PARITY, due 10-31).
5. **Disposition pass** on the old held PRs listed above.
6. Sunday 05:52Z review: the normal routine.

## Scheduled tasks targeting THIS session (recreate on new, then disable old)
| id | name | cron |
|---|---|---|
| trig_01KLc3rdQ7mHr1ddt9otcAyv | Manager lane check-in (every 3h) | `17 */3 * * *` |
| trig_015yDuqHmwCbVhj5QvNnAeHf | Manager review (twice daily) | `52 5,17 * * *` |
| trig_01AFYCUazhy8ik7mNvwB2AaB | Thursday review walk-through + weekly planning | `17 6 * * 4` |
| trig_01Qj8nNnfBjrjNYxsJwqmRUx | Weekly audit (Wed after reset) | `31 18 * * 3` |
| trig_01NbXv5anuUxM4fxsUkzhamK | Weekly research programme review | `29 19 * * 3` |
| trig_012pkRdXMQ8JpSnYf71SXMtS | Post-reset restart (one-shot, Wed 2026-10-28 18:07Z) | run_once |

Pre-handover count: **5 recurring + 1 one-shot**. Assistant-manager prompts that name this session id, to rewrite: trig_013GU17584wu4HJYEkTF1KBk, trig_01LE61kLKDFKptEfTfZ7vnYS, trig_01UnRpzN513KbMjvJWFAf911, trig_01HxRVXSy6GGqWaWQXmGdJ97, plus the assistant charter.

## Lessons this session
- **Reading every subscription.created / check_suite notice in full costs ~5k tokens each.** That is the main reason for this early rotation. Subscribe only where you must act (held PRs, red CI), per AUTO-NOTIF-POLICY.
- **A lane's local "touched tests" run is not the suite.** #19926's first head broke 8 existing tests that only CI caught. Wait for pytest-run before merging any src/ change.
- **Held lane PRs need the lane's own merge-slot claim.** Ask for it in the dispatch prompt (done for the two live lanes).

## Handover checklist
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager), not by the old manager: <id / link>, Opus, tags manager + predecessor:session_01EfjqotNYj6MppcEBqbGvkA; depth reported in V1: __/8
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = 6)
- [ ] Prompts naming the old id updated; checklist references updated and pushed
- [ ] New manager subscribed to the PRs it must watch, incl. the ops-flags PR (#17895)
- [ ] V1 read-back diffed against the old manager's list; mismatches fixed: <evidence>
- [ ] V2 trigger audit: 0 enabled triggers on old id; recurring routines present, enabled, on new id, incl. "Manager lane check-in" (17 */3 * * *): <list_triggers evidence>
- [ ] V3 id sweep: grep of prompts / charters / lane briefs for old id finds none (positive control shown): <evidence>
- [ ] V4 wake round-trips: (a) old->new <trigger id>  (b) assistant->new <evidence>  (c) lane ack <lane id>
- [ ] V5 operator told in one message: new link, what moved, what did not and why
- [ ] STAND DOWN: old manager's last message points to the new session; new manager has archived the old one after a wake landed in the new session
