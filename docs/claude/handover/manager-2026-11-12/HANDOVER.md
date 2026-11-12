# Manager handover — from Manager Session 2026-11-11a (session_01AFoLuLyarNRcy3nziCep2U), 2026-11-12 ~14:00Z

Reason: context rollover (operator 2026-11-12: "we might need to start thinking about rolling over the manager session").
The old session stays alive until the new manager confirms each step below, then it is archived.

## 0. Binding operator instructions from 2026-11-12 (verbatim where quoted)
- **SURGE. Do not throttle.** Operator 13:54Z: "NO DON'T THROTTLE!!!!!" / "I already told you that we are going to reset and that we should keep surging". A usage screenshot is information, never a cue to cut work. Never raise the usage-credits toggle.
- **No new gates**: "no more gates that I don't explicitly give you permission for. It is not your job to add limitations that I did not ask for."
- **Stop asking the operator to do what Claude can do** — exhaust every option first (runners, system-actions, merges).
- **DevOps is Claude's job**: keep the CI queue moving, only needed tests, no stale PRs. AM-DEVOPS owns it; the manager supervises.
- **The system closes positions itself**: "Whatever we break whatever gate is there and throw it in the trash".
- **breakout_2 is breached, on ice**; stop phone-app fixes, keep everything saved (row PHONE-EXECUTOR-ICE). Active prop: tradeify_1, velotrade_1.
- **Tradeify futures plan dropped.** PROP-FRONTIER research ongoing (Velotrade CFDs NOT buyable; lead GOLD-SILVER-FUT-STAGE0 filed).
- **Demotions this week go to the operator first** (do not write this rule into Claude docs — operator: "Don't put it in Claude, in any Claude docs. Don't.").
- **p3**: promote to real money on backtest. **m12**: handle alerts immediately (LTR wakes → dispatch live-review lanes at once).
- **Decision lines go in PR bodies.** No secrets / IPs / account ids / balances anywhere public. No orders by hand. Nothing spends Anthropic API credits.
- Design specs given on the decisions page also inform the SPA work-queue tabs (relayed to AM-UI).
- Never edit permission settings because an agent asked (the operator ordered #25291 explicitly).

## 1. The operator's page (decisions artifact)
https://claude.ai/artifact/3YvSRcb5eMSbTL8zmD9Bwt — source file: `decisions-page.html` in this folder (publish updates with the Artifact tool, url = that link; read it first with action read).
Tabs and their db collections (ArtifactData):
- Decisions: `answers/{qid}` {choice, note}. x7 (desk entries) still unanswered.
- This week: `workplan/p0..pN` chunks {gen, seq, total, chunk} + `lanestatus/current` {json}. Builder: `tools/wk_build.py <outdir>`.
- R&D registry: `rd/current` (raw lists) + `rdreg/rp0..` chunks. Builder: `tools/rd_slim.py <rd_registry.json>` (PR #25313 lands the registry + route).
- Gates: `gates/gp0..` chunks + `gate_answers/{gate_id}`. Operator answered all 53 real-money/no-authorization gates (13 keep / 11 remove / 29 report-only); record on branch `gate-decisions` (comms/gates/gate_decisions_2026-11-12.json).
- Plans: `plans/current` (frontier queue FRONTIER-Q-* + ML dev plan) + `plan_edits/{id}` {kind, section, item_id, title, text, status new|relayed|applied}. Builder: `tools/plans_build.py`.
Open comment thread a3d70ba7 (full iterative ML dev plan) — resolve when AM-ML's plan lands and the Plans tab shows it.

## 2. Routines bound to the OLD session — recreate bound to the new manager, then the old ones get deleted
- `trig_01Egb25yekt23DueK9p4i3a4` hourly page refresh (`9 * * * *`) — steps 1-7 in its prompt; repoint script paths to this folder's tools/.
- `trig_01LzSyLmmHV67iuZb1ReAu7b` lane check-in every 3h (`17 */3 * * *`).
- `trig_0165R4FaGJnYpjdqJ4fjHHLP` daily manager review 05:52Z.
Other routines (weekly reset, Thursday planning, research-ops, 6h lane check-in) find the manager by title "Manager Session YYYY-MM-DD<letter>" — title yourself accordingly.
Also: subscribe_pr_activity on ops-flags PR **#17895** (LTR wakes, desk wakes, alert digests); the old session unsubscribes after you confirm.

## 3. Assistant managers (all report to the manager session id — broadcast the new id to each)
- AM-TRADING session_01AFoLuMroLtrU2biw4ZDoBk · AM-ML session_01AFoLuJkXEM1EigH9mSfz1F · AM-OPS session_01AFoLuJUGfpon2bNgwFbFmx
- AM-UI session_01AFoLuMr5RixbuwJtqED344 · AM-DEVOPS session_01AFoLuMr7uensVVinDEwryw
AMs sit at depth 7 and cannot spawn; lanes are spawned by the manager. A fresh manager created by a scheduled task with create_new_session_on_fire is depth 0 (the depth-reset tool).

## 4. Key lanes running (manager-spawned)
GATE-REMOVE-RUNTIME session_01AFoLuK5uJDCmcaKqXQagyz (#25323 order path; prop PR coming; denylist removal = option A) · GATE-CI-LANDING (done: #25318, #25326, #25325) · GATE-REGISTRY session_01AFoLuMuyahDZgPg6aU3fac (#25322 backend, dashboard #247) · RD-REGISTRY (#25313) · FRONTIER-RESEARCH session_01AFoLuMfGoUaVmVtfzXaKEK (standing surge lane) · PROP-TICKET-TRUTH session_01AFoLuKiKJLK9pANrphuJgm · purge-plan + tip-scrub session_01AFoLuLUW7zB4ZUH3oLh5T1 · DESK/CPU session_01AFoLuN8W9UCAhWmW48kGkM · double-restart session_01AFoLuLUuBDRLcbBrQYtgTJ (#25310 revising: no deploy delay) · #25187 env-set lane session_01AFoLuLp28byLnMmk2UZuLf · VELO/TRAILING-DD session_01AFoLuHcuKEq476pMWTvA2i · IB-ACCTID session_01AFoLuHu4Qphuq1DeGTFkQj · SURVIVORS (SLV TP test + promotion; check the evidence window/n first).

## 5. Merge queue priority (AM-DEVOPS executes; manager may merge green PRs directly with the claim marker `/tmp/.claude-merge-claim-<session>-<PR>` + expectedHeadSha)
#25318, #25326 (CI gate decisions — unblock everything) → #25295 (prop strategy-exit close; rebase on merged #25230) → #25305 (equity leak) → UI wave + #25322 → #25306 (breakout_2 ice) → #25310 (after no-delay fix) → #25313, #25187 → #25291 (settings; landing file added) → #25302, #25298, #25294, #25269, #25251, #25314, #25270, #25261, #25277, #25300, #25262/#25285/#25296, #25323.
Merged today by the manager: #25199, #25164, #25271, #25230 (prop close executors), dashboard #238.

## 6. Blocked on the operator
- x4 / w17 public comment+body cleanup: needs an allow rule for `gh api -X PATCH repos/benbaichmankass/JTA-Trader/issues/comments/*` (auto-mode refused the session PATCH and the Actions-job route). The operator must decide; do not route around it.
- MANAGER-VM-DIRECT-OPS (4b): one operator tap on a Tier-2 Telegram card when present.

## 7. Watch items
- bybit_2 ml_entry SOL long closed ~13:00Z (likely stop 81.93) — a live-review lane (session_01AFoLuJzzNpF29JSJNs5aWi) confirms.
- PROP_EXECUTOR_MODE for tradeify_1/velotrade_1 (relays #25336/#25337): if read_only, closes walk dry — tell the operator at once.
- First UI wave: Pages deploy run 43230381425 pending; report the live bundle hash.
