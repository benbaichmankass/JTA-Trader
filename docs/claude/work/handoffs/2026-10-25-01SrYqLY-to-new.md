# Manager handoff 2026-10-25 (afternoon): session_01SrYqLY4Ui9RKns12r2zthj → new

> **Doc status:** `unknown` · category `unknown` · last verified `never` · written 2026-10-25 ~15:25Z by the outgoing manager `session_01SrYqLY4Ui9RKns12r2zthj` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

**Why rotating:** context 671k at 15:17Z, past the ~650k threshold. Quiet boundary: no merge or deploy half-done. Follow `.claude/skills/manager/SKILL.md` § Start of session (Rotation case). Subscribe ONLY to ops-flags #17895 and your own PRs.

## Capacity
- Operator reading **34% weekly at 12:30Z** (recorded, #20077), reset **Wed 2026-10-28 18:00Z**; sustainable 20.4 pp/day; observed burn ~11 pp/day 06:09→12:30Z. Running 2–3 lanes is inside pace.
- This session: ~$31 manager spend (running). Lanes (final, archived): UI-UPGRADE-1-SPA-PATCH $1.44, LIVE-TRADE-REVIEW-DESIGN $5.96, ML-CLAUDE-DISTILL-DESIGN $4.50, OLD-PR-FOLLOWUPS-1025 $6.65, LTR-0 $2.54, HANDOFF-LAND-1025C $0.32.

## Live lanes
| session | row | doing | owes |
|---|---|---|---|
| session_01Qd8ZiVhVd6w91CUCmZbxhs | CJ-0-FIXES | PR #20100 (HOLD, ml/** paths), reviewed OK by me; merging main for the row conflict after #20099 | wake with green sha → **you merge #20100**, then archive |
| session_01F56Jfoq7sgEeNKpR42WWX5 | RESEARCH-AUTHOR-1025PM | authoring to close floor gap (runnable 43 vs floor 65) + NKGUCEDN re-run unit | hold PR → **you merge**, archive |

## Open PRs needing the manager
- **#20100** CJ-0-FIXES (hold): diff reviewed, fine (reviewer field only passes through routers/order_packages.py). Merge when green + conflict resolved.
- **#20101** research-ops 14:47Z (hold, unvouchable_paths): merge on green (pytest-run was in progress at 15:18Z).
- Merged this session: #20067 #20069(closed) #20074 #20076 #20077 #20083 #20084 #20087 #20088 #20090 #20091 #20093 #20094 #20097 #20099 #20102 #11933 #18557 #14692 #11976; dashboard #230. Closed: #12158 #17874 #12213. (#16233, #17194 auto-merged before I acted.)

## Operator decisions this session (verbatim on rows)
- Headroom → "Week priorities, in order (Recommended)" (WEEKLY-PLANNING).
- Timestral licence: "I already said yes, make sure it's recorded correctly so that I don't have to keep answering this" — **standing, never re-ask** (FRONTIER-LEVER-TSFM-TIMESTRAL, ML-READ-1025).
- Live trade review design approved: Q1 "1, but let's keep track of 3 as well…" (apply ≤0.25R, shadow 0.5R), Q2 real money + prop, paper logged; Q3 applies and asks only; Q4 **"Auto from day one"**; Q5 routine counts as always-one-lane; capacity-reserve requirement added (LIVE-TRADE-REVIEW-DESIGN, LTR-7-MANDATE).
- Claude→ML design approved: Q1 "Pilot first, then set"; Q2 "Allow as a feature later"; approval "1, plus scoping on backfilling Claude analyses for all past trades" (CJ-7-BACKFILL-SCOPE).
- Stale operator blockers removed (UI-UPGRADE-1-AUTH, BREAKOUT-UNTRACKED-1014, ARMED-GATE): **nothing owed by the operator there**; phone verified on app 1b.311 = newest build.
- Tier-2 under data-backed authority: merged #14692 (login-check message only); operator notified.

## Owed by the new manager (ranked)
1. Merge #20100 and #20101 on green; merge the authoring lane's hold PR; archive those lanes.
2. **17:52Z review** (routine): report, Ideas inbox, Telegram summary, last_review.
3. Dispatch by capacity, in this order: **LTR-2-RECORDS** (fold CJ-1 § 4.4 ML fields), LTR-1-DUE-WATCH, LTR-10-CAPACITY-RESERVE, LTR-3-SKILL (after LTR-0); **CJ-2-DATASET** (Opus, after CJ-0); PROP-EXIT-READ and LIVE-BT-STAGE-B (operator's exits/giveback priority, live money); SECRETS-SED-ESCAPE (Tier 2, small); FRONTIER-LEVER-TSFM-TIMESTRAL.
4. PI-20261025-XHRNL1IB-0001: commit the eba2-03 402-trade fixture so LTR-0 ADA parity can be proven (due 11-01).
5. Stale fired one-shot triggers from earlier rotations are still enabled (no schedule); disable at leisure.
6. Leftover from the earlier handoff: ML builds POOLING-PARITY-INSTRUMENT / EXIT-HEAD-PULLBACK-DRIVER / ML-HEAD-AGREEMENT-JOIN; WATCHDOG-WINDOW-CLOCK-1025; PI-20261025-THEMEAUTHOR1025-0001.

## Scheduled tasks targeting THIS session (recreate on new, then disable old)
| id | name | cron |
|---|---|---|
| trig_01JviuNkg2rsr88CFs2hkmBi | Manager lane check-in (every 3h) | `17 */3 * * *` |
| trig_017nbrBCmbG4txhxCSTKDvBx | Manager review (twice daily) | `52 5,17 * * *` |
| trig_01CUPDAx16jx8pT5Wnf23mNS | Thursday review walk-through + weekly planning | `17 6 * * 4` |
| trig_01WbDS1S6H4wt1dRswovbzrg | Weekly audit (Wed after reset) | `31 18 * * 3` |
| trig_0172nWTmboCMytGn1ibedB2m | Weekly research programme review | `29 19 * * 3` |
| trig_01YH8Fkqty18RRb2o1Azncdm | Post-reset restart (one-shot 2026-10-28 18:07Z) | run_once |
| trig_011TkukyQBAKZoARqQJaBJtS | send_later: merge CJ-0 #20100 if green (15:31Z) | run_once |

Pre-handover count: 5 recurring + 1 one-shot (+1 send_later that may already have fired). Assistant-manager routines naming this id to repoint: trig_013GU17584wu4HJYEkTF1KBk, trig_01LE61kLKDFKptEfTfZ7vnYS, trig_01UnRpzN513KbMjvJWFAf911, trig_01HxRVXSy6GGqWaWQXmGdJ97 + the assistant charter. Live lanes above must be told the new wake id.

## Lessons this session
- **Read the row before asking the operator.** I re-asked the Timestral licence (answered at 06:02Z) and relayed 3 stale `blocked_on` operator actions without verifying. Both cost operator trust; fixed on the rows.
- `mgr/register-1025*` slugs collide with earlier managers' landing files on main — use a session-unique slug (I used `mgr/reg-01srylqy-N`).
- `mcp__Github__create_pull_request` 403s; `mcp__github__*` works.
- Merge-slot hook: for the dashboard repo there is no claim file convention; touch the marker after checking open PRs.
- Self-land register PRs need undraft + the automerge file; a lane's green self-land PR may still need a manual merge (#20090 sat green, unarmed).

## Handover checklist
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager): <id>, Opus, tags manager + predecessor:session_01SrYqLY4Ui9RKns12r2zthj; depth __/8
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = 6)
- [ ] Prompts naming the old id updated; live lanes told
- [ ] New manager subscribed to ops-flags #17895 only (+ own PRs)
- [ ] V1 read-back diffed; mismatches fixed
- [ ] V2 trigger audit: 0 enabled on old id; check-in routine present on new
- [ ] V3 id sweep with positive control
- [ ] V4 wake round-trips (old→new, assistant→new, lane ack)
- [ ] V5 operator told
- [ ] STAND DOWN
