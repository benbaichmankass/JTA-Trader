# Manager handoff — 2026-11-13 ~08:45Z

> **Doc status:** `historical` · category `history` · last verified `2026-11-13` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md)

Outgoing manager: `session_01AFoLuLyarNRcy3nziCep2U` ("Manager Session 2026-11-11a"). It is retiring because its context is past
the rotation point (~740k of 1M). The operator asked for the rotation on 2026-11-13 ~08:28Z. **You** are the next manager: title
yourself per the manager skill § "Start of session" step 1 (UTC date of your `created_at`, next unused letter).
Contract: `.claude/skills/manager/SKILL.md`. You are a **rotation manager**; read per the skill's step 2.

## 0. First actions, in order

1. Invoke the `manager` skill and read this file in full.
2. **Re-bind the routines** (§ 4) to your session. Each is bound to the outgoing session. Create a new trigger with the same name, cron and
   prompt and `persistent_session_id` = your session, then delete the old one, and verify with `list_triggers`.
3. `subscribe_pr_activity` on the ops-flags PR #17895 (never merge or close it).
4. Send each live lane in § 2 one trigger naming you as its manager.
5. Tell the operator, in one line, that you are in control.

## 1. Standing operator rules (all binding)

- **Throttle (2026-11-13 ~08:28Z): TWO lanes total.** They are the ML FRONTIER lane (under AM-ML) and the GENERAL lane (AM-OPS: ops, trading,
  devops, security, UI observation). Verbatim: *"don't end anything that's working now, but we probably need to throttle down to 2 lanes. We're
  still burning really fast."* Usage at ~08:28Z: weekly 23%, projected to run out Wednesday evening before the Wed 20:00 reset. Spawn nothing
  else except a catch-up LIVE-REVIEW lane (§ 3). The lanes must never idle and must always have a queue (operator 2026-11-12 ~22:50Z).
- **Fable resets are not used this week** (tracked as FABLE-RESETS-PLAN).
- **Operator decisions live in the UI Decisions inbox.** They are on the work store as `decision_requests` on a work item, listed by
  `GET /api/bot/work/decisions`. The operator answers in the SPA or on Telegram. Answers land in transit at
  `/api/diag/log_file?name=work_decision_transit`. The operator, 2026-11-13: *"I answer the questions in the UI. I just want you to read them
  back to me so that I can see if you got them and if you got them correctly."* So for every answer: read it back, commit it onto the item's
  `decision_requests[].answer` (POST `/api/bot/work/items/<id>/set` with `by` and If-Match), then act on it. All decisions belong in that inbox.
- **You fix things yourself**; the operator does not do the work. Wake the operator only for money at risk.
- **Demotions this week go to the operator first.** Do NOT write this rule into Claude docs.
- **No orders by hand. Nothing spends Anthropic API credits. No new gates. Never raise the usage-credits toggle.**
- **No secrets, IPs, account ids, balances or emails in the repo, issues or PR text.** Session writes record `operator-spa` (#25245/#25181).
- **The phone app is retired:** no phone work. **breakout_2 stays on ice. The Tradeify futures plan is dropped.**
- **Grants**, verbatim popup labels: "VM direct channel", "Skill/doc edits", "Merge + deploy on green", "Cancel non-required CI".
  Tier-2 PR bodies carry: `decision: 2026-11-12 operator-popup "Merge + deploy on green"`.
- **Merge discipline** (learned the hard way this session):
  - Read the diff of every Tier-2/3 PR.
  - Merge at the reviewed head sha.
  - For any Tier-2/3 or real-money config PR, wait for the FULL pytest-run, not just `guards`; only failures that reproduce on main are acceptable. (#25671 merged on guards alone and turned main red.)
  - Merge dashboard PRs only on AM-UI's approval message, never on a lane's own "ready" status. (#246 merged with a race.)
  - Batch merges that restart the trader.
  - A Tier-3 `hold` landed under the 2026-09-27 data-backed authorization MUST carry
    `recorded_decision` (`kind: standing_authorization`, `ref` citing 2026-09-27, `evidence` = the record path) in
    its `.github/pr-landing/*.json`, or `pr-landing-hold-merge-alarm` pages the operator (#25780, 2026-11-13). The
    resolver reads only repo files, checklist JSON and pipeline ids, so a row that lives only in the work store
    does not resolve: `ref` names the row AND a repo path (the unit yaml or evidence dir). Check with
    `scripts/ops/pr_landing_hold_alarm.py` before merging (manager 2026-11-13a, option (b)).

## 2. Live sessions

| Role | Session | State / queue |
|---|---|---|
| AM-ML | `session_01AFoLuJkXEM1EigH9mSfz1F` | Owns ML lanes. Report cadence ~3h. |
| ML FRONTIER lane | `session_01AFoLuMfGoUaVmVtfzXaKEK` | Working. Queue: frontier scan, then ML-2's moved items (3 build gaps, producer defects, TREND-ALIGNMENT-FEATURE). |
| ML-2 lane | `session_01AFoLuJZ69XcyrjnD8na8ao` | **Winding down**: finishes its current item, then AM-ML archives it (throttle). |
| AM-OPS (GENERAL) | `session_01AFoLuJUGfpon2bNgwFbFmx` | Working. Reports 3-hourly (~09:45Z next). Queue below. |
| AM-UI | `session_01AFoLuMr5RixbuwJtqED344` | No lane. Owns post-deploy observation (IB drain final, snapshot status) and dashboard reviews. Next report ~09:58Z. |
| Assistant managers parked | AM-TRADING `session_01AFoLuMroLtrU2biw4ZDoBk`, AM-DEVOPS `session_01AFoLuMr7uensVVinDEwryw` | Idle; work handed to AM-OPS. |

**AM-OPS queue, in order:**
1. Author the MGC/MHG time-exit/trail unit and the GDX PPI+CPI unit.
2. `IB-PAPER-MGC-BRACKET-REFERENCE-MISMATCH`: IB futures stops are priced off a different reference than the fill. Paper only, since ib_live is dry_run, but it blocks any IB futures promotion.
3. The eth_4h prop ledger-fidelity re-run (which ledger is faithful decides whether any honest tp_r PR exists).
4. LTR packet defects (1): candle pull for alpaca/ib symbols.
5. The 22 landed_unproven observation sweep.
6. Observations for #25181, #25647 and #25687.

## 3. Open threads you inherit

**Waiting on the operator (in the Decisions inbox):**
- `TQQQ-DECISION-BAR` (work item `TQQQ-D20-PROMOTE`): switch tqqq_trend_long_1d to `decision_bar: closed` to match its evidence (recommended), waive, or build a forming-bar replay.
  - The closed option is already built: **PR #25691** (AM-ML, Tier 3, held).
  - Main is red on `tests/test_roster_promotion_evidence.py::test_fingerprint_agrees_with_every_committed_record` until #25691 merges or the operator waives. Trading is not affected; nothing under src/ reads that fingerprint.
- The routine-ID ask: the live-review routine "⚡ JTA live review (real money + prop)" is not findable via list_triggers. The operator may paste its link or ID. **It is no longer urgent**, since #25687 bootstraps every fired reviewer with add_repo.

**Decided today and acted on** (answers committed on their items):
- #25181 (DD switch day-start + override): MERGED 1a3dcc785 and deployed. AM-OPS observes, including tomorrow's 00:05Z day_start. Dashboard #244 (the button) follows on AM-UI's approval.
- ml_entry v1r: `keep_watch`. Re-grade pre-registered (`RULE-ENTRY-REGRADE-V1R-20261113`), run on or after 2026-11-25, `PI-20261113-AMML-0001`. #25507 (hole_safe default) MERGED.
- #25535: wait for that re-grade.
- Prop-integrity lane: dropped by the operator ("I misspoke").
- OPRA: defer.
- TQQQ donchian 30->20: the operator chose merge (Telegram). #25671 MERGED 7f6fedac5 and deployed. AM-ML observes the first decision.

**Live review:**
- 15.5 h of silent no-rows until ~06:15Z (`LTR-ROUTINE-REVIEWERS-NO-ROWS`). The routine's sessions had no repo.
- Fixes: a catch-up lane reviewed 20 packages (all hold), and #25687 (fire-text bootstrap) is MERGED 1d925844c.
- **Closing observation still owed:** the next routine-started reviewer lands an LR row on `live-review/rows`.
- The check-in routine now checks for review ROWS, not evidence packets.

**Real-money take-profit doctrine gaps:**
- bybit_2 xrp_4h and xrp_adx25 (tp_revision) and sol_prop (unreachable entry TP + tp_revision).
- Every TP lever tested so far has FAILED. The one untested lever is RQ-20261009-900 (the ML TP head), unblocked by #25630 and queued.
- If it fails, this becomes a retirement-or-exception question for the operator.

**Other open items:**
- EXIT-EVAL-IB-OUTAGE-STALL: #25647 (pre-trip on IB 1100) MERGED. Closing observation: the next IBKR nightly reset shows "IB breaker PRE-TRIPPED" and no exit-eval breach.
- TREND-ALIGNMENT-FEATURE (operator ask): framework, then backfill, then forward tagging, then analysis, then ML feature. Queued on the ML side.
- PPI 2026-11-13 13:30Z: pre-read done (#25673). No trade recommended. Watch the paper TLT/MHG/SLV/USO stops around the release.
- Today's desk wakes are dispatched per trading-desk SKILL § 6b on each `desk-wake` marker.

## 4. Routines bound to the outgoing session (re-bind these)

| Name | Trigger | Schedule |
|---|---|---|
| Manager lane check-in (every 3h) | `trig_01LzSyLmmHV67iuZb1ReAu7b` | `17 */3 * * *` (prompt updated 08:36Z for 2 lanes plus the decisions inbox) |
| Manager review (once daily 05:52Z) | `trig_0165R4FaGJnYpjdqJ4fjHHLP` | daily 05:52Z |
| Refresh the decisions page This week workplan status (hourly) | `trig_01Egb25yekt23DueK9p4i3a4` | `10 */3 * * *`. Runs scratchpad builders. In a new container, rebuild them per its prompt, or ask the operator whether it is still wanted now that the SPA work queue is live (the prompt says to delete it then). |

Read each prompt with `get_trigger` before recreating it.

## 5. Where things are

- Modes artifact (throttle toggle): https://claude.ai/artifact/3FiwRndAB38ZwzWUhh65Hh. Set it to the 2-lane state.
- Decisions page (planning artifact): https://claude.ai/artifact/3YvSRcb5eMSbTL8zmD9Bwt.
- Console: https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g.
- The ops channel, diag routes and merge procedure are in the manager skill and `docs/claude/system-actions.md`.
