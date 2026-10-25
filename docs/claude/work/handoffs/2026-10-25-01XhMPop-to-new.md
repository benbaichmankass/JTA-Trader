# Manager handoff 2026-10-25 (midday): session_01XhMPopphHY7qu8H8NqJqqC → new

> **Doc status:** `unknown` · category `unknown` · last verified `never` · written 2026-10-25 ~11:50Z by the outgoing manager `session_01XhMPopphHY7qu8H8NqJqqC` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

**Why rotating:** context reached 677k at 11:45Z, past the ~650k threshold. This is a natural boundary: no lanes are running and no PR waits on the manager. Follow `.claude/skills/manager/SKILL.md` § Start of session (Rotation case).

**NEW THIS SESSION (binding, read first):** the manager skill § "Manager ↔ lane" now says **subscribe only to the ops-flags PR (#17895) and to PRs you open yourself — never to lane PRs** (operator OK 2026-10-25, PR #20058, row `MGR-PR-WATCH-SLIM`). The cause, measured here: lane-PR event boilerplate grew context ~150k/h, which forced a rotation about every 4 h. Hold PRs are covered three ways:
- the lane wakes you once its CI is green (new dispatch-block line);
- a `send_later` ~35 min out, which you can set yourself;
- the 3-hourly check-in.

Also read narrowly: use `get_trigger` on named routines and `list_sessions(limit=10)`.

## Capacity
- Last reading: **31% weekly at 06:09Z**, now stale. Ask the operator for a fresh reading at the 17:52Z review. Reset: Wed 2026-10-28 18:00Z.
- This session: $34.21 manager spend, ~5 h.
- Lanes this session, final spend against ceiling:

| lane | spend | ceiling |
|---|---|---|
| BRACKET-ADVISOR | $10.36 | $15 |
| ALPACA-SILENCE | $12.46 | $12 |
| BLOCKERS | $2.94 | $5 |
| XRP | $4.57 | $12 |
| DRIFT-SCAN-RETIRE | $1.07 | $4 |
| ML-HEALTH-BUILDS | $3.22 | $15 |
| THEME-AUTHOR | $2.01 | $6 |
| OLD-PR-SWEEP | $1.15 | $4 |
| TRAINER-DISPATCH | $1.28 | $5 |
| RQ-20260928-001-RUN | $2.61 | $6 |
| HANDOFF-LAND-1025B | $0.51 | n/a |
| research-ops 0847 | $1.89 | n/a |

## Live lanes
**None.** Every lane from this session is archived.

## Open PRs needing the manager
**None.** Everything this session opened or received has merged.

**Merged and DEPLOYED + OBSERVED:**
- **#20019** XRP reduce broker_order_id. The trader runs a sha containing 1b45a431. Row landed_unproven: the observation is the first intent_reduce row carrying broker_order_id, due 11-15.
- **#20023** bracket advisor. The trader runs 495837b72. Observed: advisor_* columns are filled, all `no_lever`. Parity observation due 11-22.
- **#20035** drift timer retired. Trainer-vm-diag #20040 shows the timer gone and the service disabled. Observation: the first weekly scan in /ml-review.

**Merged (research / register):** #20026, #20027, #20029, #20037, #20042, #20047, #20050, #20051, #20053, #20057, #20058, #20059.

**Closed as superseded:** #20009, #20011, #12070, #12564.

## Operator decisions this session (verbatim, recorded on rows)
- **Overhead change** (row MGR-PR-WATCH-SLIM): "as long as it's fine that your not subscribed, then let's make that change."
- **GLD zombie OCO on alpaca_paper** (PI-20261025-ALQWWPXT-0001 killed; notes on SOAK-MECH-B and PAPER-RESET): "I'm not handling that. It's not important enough … I don't really want to keep on hearing about that." **Standing: never raise it again.** Clear it only via an automated path a session can run itself.

## Owed by the new manager (ranked)
1. **17:52Z review** (normal routine): fetch the report, read the Ideas inbox, triage, send the Telegram summary, record last_review, and ask the operator for a usage reading.
2. **Dispatch by capacity from `checklist.py queue`.** The top rows:
   - UI-UPGRADE-1-SPA-PATCH: needs a lane with push to `benbaichmankass/ict-trader-dashboard`; the lane calls add_repo.
   - FRONTIER-LEVER-TSFM-TIMESTRAL (Tier 2).
   - PROP-GATE-ADA-XRP.
   - REGIME-WEIGHT-VARIANTS.
3. **OLD-PR-SWEEP follow-ups**, 8 pipeline items PI-20261025-FQCEYPUY-0001..0008. Record: comms/ops/old-pr-sweep-20261025.json.
   - Mechanical (merge main + land): #18557, #16233. #17874 just needs its evidence recorded as a note, then close it.
   - Manager calls already made: land #11933 and close #12158 (same `--tp-at-r` change; #11933 is the superset). #17194, #14692, #12213 and #11976 need a lane to check them against main.
4. **ML builds left unbuilt** by ML-HEALTH-BUILDS-1027, each unblocking 1–2 ml_health units: POOLING-PARITY-INSTRUMENT, EXIT-HEAD-PULLBACK-DRIVER, ML-HEAD-AGREEMENT-JOIN.
5. **WATCHDOG-WINDOW-CLOCK-1025** (queued). The trainer-idle check counts from window open instead of from when a unit became runnable, which caused a false incident at 09:27Z.
6. **PI-20261025-THEMEAUTHOR1025-0001:** 5 units (RQ-20261012-5bd1-02/03/04/07/08) carry `roadmap` as a bare string, so the new infra unit -006 reads FAIL until they are fixed.
7. **Tier-3 proposal from RQ-20260928-001** (PI-20261025-1CZRLDTS-0001-A): keep the ict_scalp HTF filter ON on 6 crypto legs (no change); confirmation is on the disjoint window via P3-M27-htf-pass first. Not a popup; it is data-missing.
8. **Stray duplicate landing files** from #19997 (`.github/pr-landing/claude-results-grade-1025.json` and `.github/merge-slots/claude-results-grade-1025.json`): fold into the next lane PR that touches `.github/pr-landing`.
9. **Research SLO:**
   - At 09:14Z: runnable_floor 53/57, authoring 0.9, theme_share 0.21.
   - #20051 since added 7 units (the lane's local estimate is 63 runnable).
   - Re-read the SLO table at the review. theme_share is expected to stay red for a while.

## Scheduled tasks targeting THIS session (recreate on new, then disable old)

| id | name | cron |
|---|---|---|
| trig_01SFaGLhTTga8S1An19EDdJ9 | Manager lane check-in (every 3h) | `17 */3 * * *` |
| trig_01Ui8YvuLJ6iFhjrGafuJSZs | Manager review (twice daily) | `52 5,17 * * *` |
| trig_012fxfuviN1mHP9LbpRXnCfa | Thursday review walk-through + weekly planning | `17 6 * * 4` |
| trig_01J4TdNARASRX2Ejyz6nvH4q | Weekly audit (Wed after reset) | `31 18 * * 3` |
| trig_01BM2rvLh1NnDcW6d22QDnyX | Weekly research programme review | `29 19 * * 3` |
| trig_01PB7JCQUXWT2gNiUGBU8ecX | Post-reset restart (one-shot, 2026-10-28 18:07Z) | run_once |

Pre-handover count: 5 recurring + 1 one-shot.

The assistant-manager routines that name this session id must be repointed: trig_013GU17584wu4HJYEkTF1KBk, trig_01LE61kLKDFKptEfTfZ7vnYS, trig_01UnRpzN513KbMjvJWFAf911, trig_01HxRVXSy6GGqWaWQXmGdJ97, plus the assistant charter.

The daily authoring routine trig_01GxvEXT4hRBjQvx738Tobbs finds the manager by title and needs no change. Its report step was fixed today to fire with no run_once_at.

## Lessons this session
- **Git-sync deploys automatically.** `scripts/deploy_pull_restart.sh` restarts the trader whenever main advances with a `src/` change. Merging a src PR therefore deploys it within ~5 min, with no separate restart step. Verify with `scripts/ops/diag_fetch.sh 'version'` (trader_git_sha) — Transport A works direct, so no relay issue is needed.
- **Two GitHub MCP servers can appear.** The late-connecting `mcp__Github__*` returned 403 on create_pull_request. `mcp__github__*` works.
- **A PR in `mergeable_state: dirty` runs no CI at all.** Only `watch` shows. Check mergeability before waiting on CI; the usual cause is a checklist-row conflict with a register PR.
- **Each lane push restarts the ~30-min pytest-run.** Tell lanes to push once.
- **Read guard failures from the 'Run guards' step:** `gh run view <run> --log | grep "Run guards" | grep "##\[error\]"`. The job tail only says "one or more guards failed". The strategy-coverage `##[error]` lines are self-tests; ignore them.
- **diagnostic-provenance-guard did not reproduce locally on a diff** (the lane saw the same). Fix to the guard's accepted form and let CI confirm.

## Handover checklist
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager), not by the old manager: <id / link>, Opus, tags manager + predecessor:session_01XhMPopphHY7qu8H8NqJqqC; depth reported in V1: __/8
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = 6)
- [ ] Prompts naming the old id updated; checklist references updated and pushed
- [ ] New manager subscribed to the PRs it must watch, incl. the ops-flags PR (#17895) — and ONLY those (new rule)
- [ ] V1 read-back diffed against the old manager's list; mismatches fixed: <evidence>
- [ ] V2 trigger audit: 0 enabled triggers on old id; recurring routines present, enabled, on new id, incl. "Manager lane check-in" (17 */3 * * *): <list_triggers evidence>
- [ ] V3 id sweep: grep of prompts / charters / lane briefs for old id finds none (positive control shown): <evidence>
- [ ] V4 wake round-trips: (a) old->new <trigger id>  (b) assistant->new <evidence>  (c) lane ack: n/a (no live lanes)
- [ ] V5 operator told in one message: new link, what moved, what did not and why
- [ ] STAND DOWN: old manager's last message points to the new session; new manager has archived the old one after a wake landed in the new session
