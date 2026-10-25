# Manager handoff 2026-10-25 (evening): session_01UKBXozpiJicMHHyMp47MnN → new

> **Doc status:** `unknown` · category `unknown` · last verified `never` · written 2026-10-25 ~19:00Z by the outgoing manager `session_01UKBXozpiJicMHHyMp47MnN` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

**Why rotating:** context ~610k at 18:55Z (threshold ~650k). Quiet boundary: no merge or deploy is half-done (see "Owed" item 1 — one deploy is queued, not started). Follow `.claude/skills/manager/SKILL.md` § Start of session (Rotation case). Subscribe ONLY to ops-flags #17895 and your own PRs.

## Operator priority right now (verbatim intent, 2026-10-25)
- **Claude live trade review / trading desk, live-capable by Monday market open.** "Ideally, we would want to have a prototype running in the next few hours and ... at least ready for live trading, up and running for when markets open Monday morning." The desk design ranks above other builds (not replacing them).
- Desk answers (popups, ~17:58Z and ~18:55Z): feeds = **repo feeds + logged exception**; sandbox = **shadow bybit_1**; VM-side model call <15m = **not now, revisit later**; live entry skip = **shadow only until proven**; desk design v0 = **approved, rows filed**; stop-tighten auto-apply scope from Monday = **"All accounts"** (each through its own risk gate; Alpaca refuses no_amend_path until LTR-9).
- Structural directive (~16:12Z): reviews act at the ORDER-PACKAGE level; every action goes through EACH account's own risk manager. Recorded on LTR-6-APPLY-PATH / LTR-6R.
- breakout_2: operator chose "let the system sort it out" (no manual phone action).

## Capacity
- Operator reading **36% weekly at 16:02Z**, reset **Wed 2026-10-28 18:00Z** (USAGE-READINGS). Reserve for live review 15 pp. Many lanes ran since (several Opus) — **ask for a fresh reading first**.
- This session: ~$22 manager (running). Lane spends recorded in rows/PRs; Opus lanes: LTR-3 $13.79, DESK-DESIGN $8.85, PHONE-AMEND ~$9+ (running), LTR-6R running ($18 ceiling).

## Live lanes
| session | row | doing | owes |
|---|---|---|---|
| session_01354wy5zWA5J3AcLp2NbdKo | LTR-6R-APPLY-PATH (Tier 3) | PR #20139 (draft): per-account apply path. Told: 4 design-review changes (could_not_look verdict, account-scoped execution, readback + one ping, DD switch never refuses a tighten — manager decision) + operator scope "All accounts" + prop/phone ready + --dry-run evidence + flip diff in PR body | wake on green → **you take it to the operator**: merge approval + grant MD-LIVE-TIGHTEN-SL (LTR-7) + the apply_mode flip commit |
| session_01E6AQpa6i4TYdGD11corkkG | PHONE-AMEND-REFUSED-1025 | watching breakout_2 fill (check-in ~20:35Z); its row PR #20141 | archive after the fill + checker exit 0 |
| session_017YfAAmprJiMhCa8BrwED6k | LTR-11-PACKET | owns #20128 (open_packages diag route, hold, pytest-run pending) | wake on green → you merge |

## Open PRs needing the manager
- **#20128** (hold): merge on green, then ONE `pull-and-deploy` system-action that ships #20115 (live_review_due, merged d1ee259) + #20128. Then verify on VM: `GET /api/diag/live_review_due` read_state=looked with a real open package (closes LTR-1) and open_packages answers. Open `send-ping` "hold-merge alarm" issues (#20135, #20142, older) stay open and did NOT block #20134's deploy.
- **#20139** LTR-6R (Tier 3) — see above.
- My register PRs (self-land, auto-merge armed): **#20116** (DESK-DESIGN landed_unproven + observation, LTR-6R row, priorities; just re-pushed after soak-guard fix), **#20145** (DESK-0..13 rows + operator answers). If #20116 goes dirty again: lane rows win, keep notes from both sides.
- Merged this session: #20100 #20101 #20103 #20113 #20114 #20115 #20121 (absorbed #20112, closed) #20122 (deployed 17:45Z via #20134) #20127 #20136 #20140 #20111.

## Scheduled tasks
- On THIS session (recreate on new, then disable old): check-in `trig_01RBLKwLAW5Myh3f3CV4pjVX` (17 */3), review `trig_01YSNa9GDA8grjfmT9q5aSvd` (52 5,17), Thursday `trig_011WrjdN9tTkQDhQTFUZvv52`, weekly audit `trig_01TWeQSQa8dB9sANoGzfdDmm`, programme review `trig_01Au5th6TVgoyRbVU4Wt1K2P`, post-reset restart one-shot `trig_01MRXk2nYV7dzxmNn9rMN8tg` (2026-10-28T18:07Z). Pre-handover n = 5 recurring + 1 one-shot.
- On the ASSISTANT manager (prompts name this id → repoint): `trig_01Bchsugftspk4uZhHR1ncK8` **Live trade review hourly prototype (NEW, :07 each hour, recommend mode, ~$2/run)**, `trig_013GU17584wu4HJYEkTF1KBk`, `trig_01LE61kLKDFKptEfTfZ7vnYS`, `trig_01UnRpzN513KbMjvJWFAf911`, `trig_01HxRVXSy6GGqWaWQXmGdJ97` + charter.

## Owed by the new manager (ranked)
1. Merge #20128 on green → one pull-and-deploy → verify live_review_due + open_packages on VM; close LTR-1 (and LTR-10 when `--capacity` reads a real open count).
2. LTR-6R → operator approval bundle before Monday open (dry-run evidence, mandate text, flip diff). Then: apply_mode flip commit; first applies watched.
3. Dispatch Monday-critical desk rows by capacity: DESK-12-SANDBOX (bybit_1 touch splits, after LTR-6R records), DESK-0-SCHEMA → DESK-5-SKILL → DESK-6-SHADOW-PILOT (supersedes the hourly prototype when live).
4. Watch the hourly LIVE-REVIEW prototype runs (first 19:07Z): cost per run vs the weekly bar; cut cadence if needed (operator wants as short as feasible, 15m target).
5. breakout_2: confirm fill / checker exit 0 → close PHONE-AMEND-REFUSED-1025; PI-20261025-11CORKKG-0001 (sheet_not_open) still open.
6. Carried from the earlier handoff: CJ-2 now waits on DESK-0; PROP-EXIT-READ, LIVE-BT-STAGE-B, SECRETS-SED-ESCAPE (oldest unrouted, 25d), FRONTIER-LEVER-TSFM-TIMESTRAL (licence approved — never re-ask); config/economic_calendar.yaml stale (newest event 2026-07-30) — file a fix row; LTR-10B follow-ups; alpaca_live near-idle decision (PI-20261025-ALQWWPXT-0003) → popup.

## Lessons this session
- Pushing repeatedly to an open register PR restarts its CI each time; batch register edits, open a new PR rather than re-pushing an armed one.
- `gh api` works for PR/check reads; `mcp__github__*` for writes. Merge-slot hook: touch the marker after checking open PRs.
- A lane's first live run (LTR-3) found a real live-money exposure (breakout_2) — keep the review running.

## Handover checklist
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager): <id>, Opus, tags manager + predecessor:session_01UKBXozpiJicMHHyMp47MnN; depth __/8
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = 6)
- [ ] Prompts naming the old id updated (incl. the new hourly LIVE-REVIEW trigger); live lanes told
- [ ] New manager subscribed to ops-flags #17895 only (+ own PRs)
- [ ] V1 read-back diffed; mismatches fixed
- [ ] V2 trigger audit: 0 enabled on old id; check-in routine present on new
- [ ] V3 id sweep with positive control
- [ ] V4 wake round-trips (old→new, assistant→new, lane ack)
- [ ] V5 operator told
- [ ] STAND DOWN
