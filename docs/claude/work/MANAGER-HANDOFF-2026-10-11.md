# Manager handoff — 2026-10-11 ~18:00Z

> **Doc status:** `historical` · category `history` · last verified `2026-10-11` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md)

Outgoing manager: `session_01Uq7MrjPQDRWqbhCjwuMava` ("Manager Session 2026-10-08"). It is retiring because its context is
nearly full (~80% of 1M). The operator chose to hand off after the evening review (popup 2026-10-11 ~12:27Z).
**You** are "Manager Session 2026-10-11". Contract: `.claude/skills/manager/SKILL.md`. Budget row: `PACE-W40`.

## 0. First actions (in order)
1. Invoke the `manager` skill and read this file in full.
2. **Re-bind the routines** to your session. They are listed in § 4 and all point at the outgoing session today.
   Use `update_trigger` only if it can change `persistent_session_id`; otherwise create a new trigger with the same
   name, cron and prompt and `persistent_session_id` = your session, then delete the old one. Verify with `list_triggers`.
3. List the lanes and PRs in § 2 and confirm their state against GitHub and `list_sessions`. Report to the outgoing manager or
   the operator that you are in control.

## 1. Standing operator rules (this session, all binding)
- **Decisions go to the operator as popups** (AskUserQuestion). Missing data is not a popup: file the task that gets the data.
- **Tier-2/3 changes may ship autonomously when data settles the question.** Then notify the operator at once with the
  evidence, whether it is merged / deployed / observed, and the revert.
- **Models:** no Fable lanes. Opus only for order-path, prop or real-money work; Sonnet for everything else.
- **The repo is PUBLIC:** never print secrets, account ids, VM IPs, chat ids, inbox addresses or app passwords.
- **The auto-mode classifier:** if it refuses, never reword or work around it; ask the operator.
- **Orders:** never place real orders from a lane or from the manager. Lanes may never use `send_later` or `create_trigger`.
- **There is no halting.** The only exception is the daily drawdown switch.
- **Retired / on ice:** `breakout_1` is retired. The private-repo move is on ice.
- **Research-ops is never skipped because topic research lanes are running** (operator 10-11 ~07:57Z).
- **Budget:** target about 90% of weekly usage by **Wed 2026-10-14 18:00Z** (21:00 operator local, UTC+3).
  The 12:25Z anchor was 66%, under pace, and the operator chose "UI now + 3 more lanes". Usage credits are on. Do not plan to reach 100%.
- **REGIME-PROGRAM** is normal priority, in the queue (the operator's regime / market-structure voice brief, 10-11).
- **ML / AI frontier** (operator 10-11 ~14:25Z, then 15:30Z, verbatim): *"let's get all of this into the roadmap and into the
  work que, the first couple of sessions should be high priority to get the work flow/infra sorted out, then we need to have
  the same continuous research-test-improve flow we have for the strategies to push the roadmap forward"*. This means:
  - test genuinely different model families, not "100 variations of the same model";
  - run the weekly frontier scan (skill `frontier-research`) and the model-family variety check
    (`python3 scripts/ops/ml_plan_status.py --diversity`; 78% of registered models are GBDT);
  - the same scan, lighter, for strategies.

## 2. Lanes and PRs in flight (state at ~17:58Z)
| item | session / PR | state | your action |
|---|---|---|---|
| ML-RESEARCH-LOOP-1 (HIGH) | `session_01QRNxMhicEy4xbthzaZ9su7`; #17609 + #17610 merged | **#17611** is the ML research runner (ML units → trainer → result → research-ops); draft, hold (trainer runtime), pytest running | Review → merge → verify the first ML unit (`RQ-20261011-9da8-01` TSFM bake-off or `-03` conformal) runs end to end through the new path. Then dispatch infra session 2 if anything is left, then let research-ops drive the units. Archive the lane when done (~$9.1). |
| PERF-FU-REDUCE-PNL (Opus) | `session_012h5mfFx5doTB4cYjaYF7gd` | #17577, #17596 and **#17599 merged** (~17:57Z). Row `landed_unproven`, check due 10-18 | Re-run the `backfill-intent-reduce-pnl` system action as a **DRY RUN** (or ask the lane to). Review the diff (rows per account, pnl delta, unverified count) and only then apply. Notify the operator: real-money P&L restatement. ~$16.7. |
| UI-UPGRADE-1 (Opus) | `session_01McHbeefghxRy9AJPfinTeQ` (idle, close-out merged) | Merged #17573, #17578, #17579, #17585. **#17584** = auth + keys design (items 7/9), green, open | (a) Confirm the web API runs the merged server code (`/api/diag/version`; git-sync restarts ict-web-api). (b) The dashboard SPA patch needs a session with push access to `benbaichmankass/ict-trader-dashboard`; this session has it as a source. Take it or dispatch it. (c) Review #17584 (security design — Google + passkey login, keys admin, per the operator popup answers below) and merge or return it. Remaining items: nav order, merged Roadmap+Work tab, brief in the report roster, signals placeholder, login, keys. ~$12.8 of $40. |
| ML-REVIEW-20261011 | `session_01TJm8DkoUfBts46QxZqzm7j` (blocked / needs input) | #17580 merged (manifests). #17583 merged. **#17582 has a merge conflict.** Trainer pull PR #17581 is unread. The **4 registry `promote-stage` flips were NOT run** | Have the lane merge main into #17582 and push, then merge it. Run the promote-stage block from the #17580 PR body on the trainer (four ids → candidate; these are operator decisions ML-STAGE-DECISIONS, so just run them) and verify `/api/bot/ml/registry`. Read #17581. ~$4.6. |
| TELEGRAM-CHANNELS-3 (not dispatched) | — | The operator said "no need" for now (other work first) | Later: a small Sonnet lane (~$5). (1) Order the manager update **Blocked / In flight / Next before Shipped / Verified**, and cap the last two at ~5 lines — the 4096 trim cut the Blocked item on 14:00Z. (2) Verified lines must state the outcome, not the row title. (3) The "0 queued" headline label is ambiguous. (4) The duplicate "No new decisions" line. Also check that 15:01Z+ updates show real transitions (the cursor started then). |
| #17586 | TELEGRAM-CHANNELS row → `landed_unproven` | guards **failed**; lane archived | Fix or redo: set the row with a SOAKS contract, or `done` + a `check_observation` pipeline item. |
| Stale non-automation PRs | #17206, #17194, #17193 (HELD Tier-3 ada vol_trail), #17182, #16723, #16546, #16302, #16233, #15847, #17556 (ML plan units, hold) | old | Triage: merge, close with a reason, or surface to the operator. |

Archived today, with spend:
| lane | spend |
|---|---|
| TELEGRAM-CHANNELS-2 | $29.7 |
| FIDELITY-CLAUSE | $12.8 |
| ML-ROADMAP-LOOP | $5.4 |
| ROADMAP-LOOP | $5.6 (#17557 merged) |
| ML-PLUMBING-1 | $2.5 (#17576; parity run issue #17595 due 10-18) |
| RQ-PIPELINE-FIX | $1.9 |
| FRONTIER-RESEARCH | $3.5 (#17600) |
| FRONTIER-HARNESS-COSTS | $2.4 (#17608) |
| RESEARCH-OPS-0847 | $1.6 |
| RESEARCH-OPS-1447 | $2.5 (#17601) |

**Record these on PACE-W40** (not done yet).

## 3. Merged / deployed / observed today (selected)
- **Telegram:**
  - 3-channel layout (TRADES = Prop_trade_bot, SYSTEM = Trader Bot, MANAGER = ClaudeBot): deployed; the operator verified it.
  - Oversized-ping split (#17544): deployed and observed.
  - Per-channel content + cadence menu (#17542): deployed 13:26Z and services restarted. The first sectioned update rendered; see the TELEGRAM-CHANNELS-3 notes above.
- **ML:**
  - Stage-decision manifests (#17580): merged; registry flips pending.
  - Replay-parity harness (#17576): merged; not yet run.
  - ML plan loop (#17555): closes when the 10-18 ML review runs it unprompted.
- **Frontier program:**
  - Shortlist and 7 pre-registered units `RQ-20261011-9da8-01..07` (#17600).
  - Roadmap track F and research-loop docs (#17609, #17610).
  - Harness cost stack for vol_target / xsec_momentum (#17608).
- **Reduce-leg P&L sweep** (#17577, #17599): merged. Deploy not verified by me; backfill not applied.
- **Fidelity clause C5** (#17521): scoped to risk-bearing targets.

## 4. Routines bound to the outgoing session (re-bind all)
| trigger | schedule | what |
|---|---|---|
| `trig_018oheLJiUW5UsAHYmGiVZ24` | `52 5,17 * * *` | Manager review (05:52Z / 17:52Z). Its prompt still says "~70%" — the target is now **~90%**. |
| `trig_01D1x8BDiMGaHiZES2miHmwS` | `47 2,8,14,20 * * *` | Research-ops dispatch (Sonnet, $5, never skipped by topic lanes). |
| `trig_01HbgzS8BWABnbtkTxa329fe` | `17 */6 * * *` | Lane check-in (backup wake). |
| `trig_01NDbwo7UviviYj2tYnMVVrk` | `57 6 * * 1` | Weekly research-planning (fresh session each fire; no re-bind needed). |
| `trig_01PVmGQYwUhCSXZ3pwbkgN2s` | one-shot 18:30Z | Outgoing manager's handoff reminder — **delete** once you are in control. |

Weekly routines still owed (add them; the manager skill's Weekly section lists them):
- **Sunday `/ml-review`**, including step 9 (the ML plan loop + frontier scan).
- **Weekly `/performance-review` → `/perf-followup`.**
- **Weekly frontier scan** (skill `frontier-research`), if not folded into ml-review.

## 5. Telegram layout and operator format feedback
- **MANAGER (ClaudeBot), hourly at :01:**
  - Needs-you = real decisions only.
  - Research lines carry findings (unit, leg, net R, n, next step).
  - Work section: done / coming up / blocked / passed / didn't work, with row ids.
- **SYSTEM (Trader Bot):** hourly health check.
- **TRADES (Prop_trade_bot):** hourly performance snapshot.
- **Cadence:** a settings menu sets it per update (hourly / 4h / twice a day / daily), per channel.

## 6. UI-UPGRADE-1 popup answers (operator, 10-11)
- **Sign-in:** "Google + passkey".
- **Access:** "View + edit, passkey each time".
- **Order:** "Roadmap two now, UI after".

The other 9 items are listed in checklist row `UI-UPGRADE-1`.

## 7. Open operator requests
- **Frontier shortlist:** delivered 15:28Z. Next: get the frontier tests actually running through the ML runner (above), and report results as they land.
- **Claude "projects" (outgoing manager's findings):**
  - No tool can create a session in a project, move a session or move a routine. `create_session` has no project field.
  - Routines carry a `folders` field (all `NONE`), so moving them is a UI action for the operator.
  - Recommendation given: keep rotating manager sessions and use the project as a filing shelf. If the operator moves a routine into
    the project, check that you can still see and edit it, and record whether that removes the re-bind step at handoff.
- **Note for the operator if TabPFN ever wins a test:** its weights are non-commercial; live use would need a licence decision.

## 8. Prop state (~13:00Z, for context; re-read before quoting)
| account | state |
|---|---|
| velotrade_1 | ~$4,956, flat |
| tradeify_1 | ETH long open, equity ~$9,913 |
| breakout_2 | $5,000 |

Prop realized over 7 days: −$91.55.
