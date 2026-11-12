# Thursday planning 2026-11-12: the operator's 21 answers and where each landed

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes: none.** This is a record. The one rule that changes an automatic path (p2, demotions wait for the operator)
> lands on its own Tier-3 HOLD PR (row `DEMOTE-OPERATOR-LOOKS`), and the operator asked for it in their own words.

**Source of truth:** the decisions page https://claude.ai/artifact/3YvSRcb5eMSbTL8zmD9Bwt, database collection `answers`, documents p1–p9 and
m1–m13 (there is no m8). The operator saved them on 2026-11-12 between 07:45:24Z (p1) and 07:51:18Z (m13). This lane, OPDEC-20261112
(session_01AFoLuMpRDMZ3GfqaMUnCk5, dispatched by Manager Session 2026-11-11a), read them itself with `ArtifactData list` and read the card
text with the Artifact read action. The a*, b*, c*, d*, e*, n* and u* documents in the same collection are the 11-11 answers, already
recorded, and are ignored here. **Population: 21 answers (p1–p9, m1–m7, m9–m13).** Choices and notes are quoted verbatim, including typos and
trailing spaces.

Rows live in the work store (WSD-S4 freeze; `scripts/ops/checklist.py` writes there). Each row named below carries a note with the same
`decision:` line.

## The answers

| id | card | choice (verbatim) | note (verbatim) | owner of the follow-through |
|---|---|---|---|---|
| p1 | Capacity: this week's Usage reading | "I'll give the reading in chat" | "We have a reset so the plan is to surge until we reset again, hopefully on Saturday or Sunday, then reset and keep surging until we have to throttle ahead of the Wednesday reset. Don't worry about capacity for now, just keep the surge going" | **manager** (already handling) |
| p2 | Surge slot 1: a working demotion signal for the 6 real-money legs, before new ML research? | "Both in parallel (needs capacity)" | "And don't let anything get demoted without me looking at it first " | this lane: rule → `DEMOTE-OPERATOR-LOOKS` (Tier 3 HOLD PR); F1 → `PERF-F1-DEMOTION-SIGNAL` (lane) |
| p3 | Volume-composition feature: keep the shadow-first path? | "Also test it in the exit head now" | "We already said that things get promoted to real money based on backtesting, shadow on paper is only for something that is demoted and in iteration, not a step on the way to real money " | **manager** (ML lane part 5); doctrine check by this lane, see § p3 |
| p4 | Backlog drain: the plan | "Accept: start after the export fix" | — | `HEALTH-20261111-EXPORT-READS-STALE` then `BACKLOG-DRAIN-20261112` (lane) |
| p5 | Draft workplan (15 items): accept as the week's list? | "Accept the list; size it to my Usage reading" | "I don't see the signals catalog and features heat map here" | list accepted; heat map → `FEATURE-IMPACT-MAP`, catalog → `FEATURES-CATALOG-UI-VERIFY`, both to lane UI-SPA |
| p6 | Desk: turn the scan wake on? | "Turn it on (I'll flip it in the console)" | — | **operator** flips `desk_wake`; PR #25131 stays as the alarm fix (**manager**) |
| p7 | Carried twice: schedule, date or kill | "Take the ML lane's proposals: kill 2 lever rows, run HARNESS-COSTS, schedule the ledger, one research-SLO lane" | "In general, all killed items need to have a reason and supporting data attach" | doc rule (this lane, § p7); kills/levers/SLO lane (lane) |
| p8 | Survivor promotions (tlt/qqq/slv/uso 1h): check the evidence this week? | "Yes: evidence check, then a proposal per leg" | — | `PR1111-SURVIVOR-PROMOTIONS` (lane) |
| p9 | Two small merges waiting on you | "Merge both" | — | **manager** merges #25141 + #25135 (#25141 merged 5c3ec90c7, #25135 merged 8692fce3f, both on `origin/main` as fetched by this lane on 2026-11-12) |
| m1 | Force-cancel the ~410 frozen GitHub Actions runs? | "Yes: force-cancel exactly that listed set" | — | `ACTIONS-FROZEN-RUNS-CANCEL` (lane) |
| m2 | Dashboard (SPA) halves of the UI work: give a lane access to the dashboard repo? | "Add the dashboard repo to the environment so I can dispatch a dashboard lane" | "You should already have all 3 repos on the env" | **manager** (lane UI-SPA exists with all 3 repos) |
| m3 | Security: the web API (8001) is reachable from the internet over plain HTTP. Lock it down? | "Lock it down: move those three clients to HTTPS, then bind 8001 to localhost and drop its firewall rule (one Tier-2 change, one web-API restart, live-money path unaffected)" | — | `SEC-8001-LOCKDOWN` (lane; Tier 2 approved by this answer) |
| m4 | Security: four host changes (all Tier 2; none done) | "Do all four now" | — | `SEC-HOST-CHANGES-1112` (lane; Tier 2 approved by this answer) |
| m5 | Direct action path: the remaining design calls | "Accept the defaults (15 min; all classes; advice rows get a button; yes to Tier-1 on the credential); I'll create the routine and token" | — | `MANAGER-VM-DIRECT-OPS`, `TRADE-ACTION-DIRECT-PATH`; operator creates the routine + token (§ m5); #25052 may merge on green |
| m6 | Confirm or revert #24926 (feature-impact read routes)? | "Confirm (I add your decision to the record)" | — | recorded here (§ m6) |
| m7 | Drawdown switch: add a one-time override button? And the day-start equity reading | "Build the one-time override button and fix the day-start reading first" | — | `DD-SWITCH-OVERRIDE` (lane) |
| m9 | TLT to real money (b1 follow-up) | "Rebuild the evidence record, then promote when it passes" | — | `PROMOTE-TLT-1H-REAL-MONEY` (lane; data-backed Tier 3) |
| m10 | Four held PRs from the general lane | "Refresh and merge all four on green" | — | #24881, #24952, #24961, #24962 (lane) |
| m11 | Fix the phone cancel that marks a filled trade 'skipped'? | "Build it now (a server-side fix, no app install)" | — | `PHONE-CANCEL-FILLED-AS-SKIPPED` (lane) |
| m12 | Two new CI checks from the UI lane: insight-link-guard and topic-map-guard | "No; report gaps as a number instead" | "The manager needs to get these alerts and handle immediately " | doc rule (this lane, § m12); build → `WORK-GAP-ALERTS` (lane) |
| m13 | Close class: test automatic execution? | "Register the net-of-cost test for the close class now" | — | `CLOSE-CLASS-NOC-TEST` (lane) |

The dispatch table (row → lane session → PR) is in the lane's report to the manager and is appended to § Dispatch below as lanes report.

## Binding rules from these answers, and their canonical homes

### p2 — no demotion without the operator looking first

Operator, verbatim (p2 note): *"And don't let anything get demoted without me looking at it first "*.

This narrows the 2026-09-27 data-backed Tier-2/3 authorization for one class: a **demotion** (Stage 2 → floor, a roster cut, an ML overlay
stepped down, an exit head moved from `close` to `annotate`, an ML model's stage lowered) is **proposed with its evidence and waits for the
operator**; it is not shipped first and reported after. It touches `config/mandates.yaml` (`MD-DEMOTE-S2-S1` carries `autoland: true`;
`MD-DEMOTE-S1-OFF`, `MD-S1-CUT-ON-STAGE0-FAIL`, `MD-ML-OVERLAY-CANARY` grant demotions) and `docs/CLAUDE-RULES-CANONICAL.md` § "Data-backed
Tier-2/3 decisions" ("De-risking decisions (demote, shrink, cut, add protection) carry no such block"). That is Tier 3: row
`DEMOTE-OPERATOR-LOOKS`, one HOLD PR the manager merges. **Until it merges, every session applies the rule as stated by the operator.**
INFERRED consequence to watch: last night's ETH exit-head `close` → `annotate` (#25120) was shipped under the old rule; it predates this answer
and is not reverted by it. The operator can say so if they want it reviewed.

### p3 — shadow is not a step to real money

Operator, verbatim (p3 note): *"We already said that things get promoted to real money based on backtesting, shadow on paper is only for
something that is demoted and in iteration, not a step on the way to real money "*.

Checked against `docs/plans/OPERATING-PLAN-2026-09-21.md` § 2 "Stage 1 is the DEMO FLOOR" (read 2026-11-12): it already says
*"`execution: shadow` is not a holding stage"*, *"Real money is promotion only"* (Gate 2 on the Stage-0 record) and, in § "The soak is
MECHANICAL", that a leg with proven mechanics goes Stage 0 → real money. It did **not** say it for ML heads and features, where the
candidate → shadow → advisory ladder and "a pass authorizes only a shadow head" still read as a step toward live. The operator's sentence is
added verbatim to § 2 on this lane's doc PR, scoped to strategies, ML heads and features. The ML part-5 work itself is the manager's.

### p7 — every kill carries a reason AND supporting data

Operator, verbatim (p7 note): *"In general, all killed items need to have a reason and supporting data attach"*.

Doc rule, no guard (a refusing guard would be a new gate; none is built). Homes: `.claude/skills/manager/SKILL.md` (weekly-planning
disposition (c) and a short paragraph under it). It applies to checklist rows (`dropped`), pipeline items (`killed`, `terminal_reason`),
research units (`MD-KILL-QUESTION`) and backlog-drain decisions. **Supporting data** means a pointer a later session can open: the measurement,
result file, PR, or row the reason rests on, with its population. A decision quote alone is a reason, not data.
Finding: `FRONTIER-LEVER-TABULAR` and `FRONTIER-LEVER-TSFM-TIMESTRAL` were **already** `dropped` at 2026-11-11 22:02Z with the reason
*"Killed by operator decision 2026-11-11 (Thursday-planning a6 …)"* and no supporting data (read from the work store, 2026-11-12). The p7 lane
attaches the data to both terminal records; it does not re-kill them.

### m12 — work-map gaps are alerts the manager handles at once

Operator, verbatim (m12 choice and note): *"No; report gaps as a number instead"* · *"The manager needs to get these alerts and handle
immediately "*.

No CI check (`insight-link-guard` and `topic-map-guard` are not built). Insight-link gaps (an insight with no link) and topic-map gaps (a
roadmap milestone with no topic) are published as **numbers** and routed to the manager's alert path (the alert ledger behind
`ALERT-LEDGER-TO-MANAGER`, which wakes the manager); a non-zero count is handled the same day, like an ops-flags comment. Home:
`.claude/skills/manager/SKILL.md` § "The insights ledger". Build: row `WORK-GAP-ALERTS`.

## Item notes

### m1 — the frozen Actions runs
Approved set only: the runs listed on the card (412 created before 2026-11-11 20:53:30Z that never started and return 409 on a plain cancel;
372 from three send-ping issues plus 38 older zombies). If the safety classifier refuses the force-cancel again, the lane reports the refusal
and stops; it does not route around it. The research queued-runs cap is not changed (option 2 was not chosen).

### m5 — what the operator must create
The defaults are accepted: buttons stay valid 15 min; all executor classes get one; advice-only recommendations get one; the one environment
credential may run **Tier-1** VM actions directly (Tier 2 still needs the operator's quote or an Approve tap). The operator creates, in
claude.ai: **one scheduled task** (the instant review wake, which starts a review lane when the VM posts a review trigger) and **one API token
for it** that the VM uses to fire it. The exact names, prompt and where the token is stored come from the `TRADE-ACTION-DIRECT-PATH` lane's
design and are relayed by the manager; this record does not invent them. #25052 (direct VM ops channel, Tier 2) may merge on green.

### m6 — #24926 confirmed
#24926 (`FEATURE-IMPACT-MAP (UI backend): heatmap / detail / invest routes`) merged 2026-11-12 01:04:30Z (GitHub, read 2026-11-12). The
operator confirmed it: `decision: 2026-11-12 operator decisions page m6 "Confirm (I add your decision to the record)"`. No revert.

### p5 — the two items the operator did not see
- **Features heat map:** row `FEATURE-IMPACT-MAP` (landed_unproven, ML standing lane). Backend routes are merged and live (#24926). The SPA view
  is not built. Handed to lane UI-SPA.
- **Signals catalog:** rows `SIGNAL-CATALOG` (the catalog file, `docs/reference/signal-catalog.yaml`, 335 inputs / 76 models, generated
  2026-10-08) and `FEATURES-CATALOG-UI-VERIFY` (the UI). No API route serves the catalog today (`docs/design/ui-workplan-2026-11.md` § 14).
  Handed to lane UI-SPA.

## Dispatch (2026-11-12 08:13Z)

All lanes were created by this lane with `create_session` on JTA-Trader and report to the manager. PRs are filled in as lanes report.

| item | row(s) | lane | session | model |
|---|---|---|---|---|
| m1 | `ACTIONS-FROZEN-RUNS-CANCEL` | **not started**: `create_session` refused by the auto-mode classifier ("Interfere With Workloads"); no workaround | — | — |
| m3 | `SEC-8001-LOCKDOWN` | **not started**: `create_session` refused by the auto-mode classifier ("Production Deploy"); no workaround | — | — |
| m4 | `SEC-HOST-CHANGES-1112` | OPDEC-M4-HOSTS | session_01AFoLuN6jjQHLuQvRkmroCe | Opus |
| m7 | `DD-SWITCH-OVERRIDE` | OPDEC-M7-DD (button → UI-SPA) | session_01AFoLuJD1uLtmKbpHNi6gX5 | Opus |
| m9 + p8 | `PROMOTE-TLT-1H-REAL-MONEY`, `PR1111-SURVIVOR-PROMOTIONS` | OPDEC-SURVIVORS | session_01AFoLuLWn3eMSsJGMn4UYXX | Opus |
| m10 | #24881, #24952, #24961, #24962 | OPDEC-M10 | session_01AFoLuJU4X573xpt2K2gKkv | Sonnet |
| m11 | `PHONE-CANCEL-FILLED-AS-SKIPPED` | OPDEC-M11 | session_01AFoLuK7LNskMkynxgJmJ5s | Opus |
| m12 | `WORK-GAP-ALERTS` | OPDEC-M12 | session_01AFoLuLZUmLfdYeDbi7nMEF | Sonnet |
| m13 | `CLOSE-CLASS-NOC-TEST` | OPDEC-M13 | session_01AFoLuMsaUDHEBnFNj8WppB | Sonnet |
| p2 rule | `DEMOTE-OPERATOR-LOOKS` | OPDEC-P2-DEMOTE-RULE (Tier 3 HOLD PR) | session_01AFoLuN1M3mPZin4zDKrmH9 | Opus |
| p2 F1 | `PERF-F1-DEMOTION-SIGNAL` | OPDEC-P2-F1 (/perf-followup) | session_01AFoLuKGivxba8N7Mss11en | Opus |
| p4 | `HEALTH-20261111-EXPORT-READS-STALE` → `BACKLOG-DRAIN-20261112` | OPDEC-P4 | session_01AFoLuHsrjCGGba7eop8Qev | Opus |
| p7 | TABULAR/TSFM kill data, `FRONTIER-LEVER-HARNESS-COSTS` | OPDEC-P7-LEVERS | session_01AFoLuMaNct18F1jYBq2Ry4 | Sonnet |
| p7 | `AUD-20261019-RESEARCH-SLO-RED` | OPDEC-P7-RESEARCH-SLO | session_01AFoLuKDJYVZsxPtE74wG5z | Opus |
| p7 | `ML-LEARNING-LEDGER` | scheduled, due 2026-11-16, ML standing lane (owner on the row) | — | — |
| p5 | `FEATURE-IMPACT-MAP`, `FEATURES-CATALOG-UI-VERIFY` | UI-SPA (create_trigger + fire_trigger) | session_01AFoLuK7JPLuVHFGNKbcoqt | — |
| m5 | `MANAGER-VM-DIRECT-OPS`, `TRADE-ACTION-DIRECT-PATH` | the manager merges #25052 on green; the operator creates the routine + token | — | — |
| m6 | — | recorded here | — | — |
