# Manager handoff 2026-11-05: session_01AFoLuJnejB97CXXc8yn9oA (Manager Session 2026-11-05a) -> new

> **Doc status:** `unknown` · category `handoff` · last verified `2026-11-05` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md) · rotation reason: old manager context ~772k tokens (> ~650k threshold); weekly plan usage 31% at 11:32Z (reset Wed 2026-11-11 18:00Z; app warned "at this pace you'll run out tomorrow night").

## Operator directives in force (verbatim where quoted)

- Pace: popup 11:3xZ, operator chose **"Keep pushing to Friday"**. Near 90% weekly usage, run the close-up protocol (lanes write resume notes; one PIPELINE paused-work item due at weekly_reset; arm auto-merge; pick-up reminder after the reset). Regroup Fri 2026-11-07 morning.
- Priorities this week: redesign + real money first, then the ML roadmap. Operator: "we need to make sure the ML priorities are getting the attention they need too".
- **Tradeify is TOP PRIORITY: "Go live when tests pass".** Prop ML across all prop accounts; a breakout_2 breach is not a blocker ("small test account, we'll just buy another one").
- The repo is not a database. Decisions go to the operator as popups (AskUserQuestion). No recurring Telegram updates.
- Opus for live-trader/core work, Sonnet for the rest.
- "there's no reason not to pull data for testing from the broker connections as long as it doesn't interfere with trading".
- Console: **every update to the operator includes the link https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g.** Operator: "Can we make sure the current manager is always the owner so that it's always available in the manager's artifacts tab?" So the NEW manager republishes the console from its own session (see first actions). The operator wants it openable side by side with the manager chat.
- Operator popup answers today: "Deploy when green (Recommended)" (WSD-S2 #23225); "Open 443 + Google OAuth (Recommended)" (console connector, #23234 merged, #23237); "Merge, breakout_2 on report (Rec.)" (#23252, Tier 3).
- Console tabs ask (verbatim ~11:11Z): "We also need to add some tabs to the console: 1. Weekly workplan tracker 2. ML Roadmap tracker 3. Performance tracker for MLs and live strategies 4. Systems/resource health and allocation 5. Data viewer - trade journal and other databases".

## Live lanes (id, row, doing, owes) -- tell each the new manager id

| lane | session | doing | owes |
|---|---|---|---|
| UI-CONSOLE-V1 | session_01AFoLuHwLaAoMwMgXVxwfvV | #23237 OAuth (conflict fixed, head 3136f3ae, CI rerunning); ~$29/$30 | green sha -> manager merges -> auth-on restart + verify -> manager asks operator to add "JTA Trader" at https://158-178-209-121.sslip.io/mcp; then archive |
| UI-CONSOLE-ITEM-FEEDBACK | session_01AFoLuKPFatiYC8ciYMxABr | console page v7 published (5 tab shells); $20 ceiling | fill tabs (v8+) once docs/reference/console-connector-tools.md lands -- manager relays it |
| UI-CONSOLE-TABS-DATA | session_01AFoLuNATEbvRrjqtCRiCk2 | connector tools workplan/ml_roadmap/performance/system_health/data_query | PR + schema doc -> relay to ITEM-FEEDBACK |
| WSD-S2-S3 | session_01AFoLuLxKwXrxDXYuPZvffX | #23225 S2 (pytest-run in progress on 7b80d7ff), #23267 S3 row (roadmap-map-guard fix) | green sha for #23225 -> manager merges -> lane deploys timer |
| WSD-S1-STORE-API | session_01AFoLuJFu3NEJt21ZKxx7N1 | #23273 X-Diag-Token (Tier 2 hold, CI running) | green sha -> manager merges -> verify diag_fetch.sh 200 -> close WSD-S1-PROXY-AUTH-COLLISION |
| BREAKOUT2-POSITION-DIVERGENCE | session_01AFoLuKeQu3QVQ3hxYKt2vn | #23252 (Tier 3, operator-approved) has NO CI on head 2583cb21 (push event dropped; ready_for_review did not trigger it); APPLY #23277 run 42017095693 | merge origin/main into #23252 to fire CI -> green sha -> manager merges; verify ticket prop-manual-8468ab1f682f reads skipped |
| TRADEIFY-OWN-LEG | session_01AFoLuHhdpKjKRGBRqBWZaR | runs 42018823856 (Tradeify RQ-20261105-fd68-01) + 42018828772 (Breakout/Velotrade -02), queued ~11:25Z, 1-3 h | verdicts vs pre-registered rule net of full cost + prop EV/survival gate; on PASS the held Tier-3 roster PR straight to the manager -> operator "Go live when tests pass" |
| RESTART-GAP-EXIT-FIRST | session_01AFoLuJnVnfwvC5273r4RN5 | Opus, $18: exit loop before heavy init + deploy/trainer/ in the 3 lockstep non-runtime patterns | held Tier-2 PR -> manager merges -> next deploy restart-gap line < 45000 ms |
| ML-ENTRY-ALPACA-A41F | session_01AFoLuLh6ui8yrCXu3ES5Cp | #23257 a41f-01 part 1 (pytest-run in progress) | green -> merge |
| ML-MANAGE-HARNESS | session_01AFoLuLmUqZNSKgUcpLWwNW | ML-DECISION-MODELS c692-03 + dynamic-SL arms | PR |
| ML-DATA-WIRING | session_01AFoLuNLZwgzom32C3hBXFE | train every ML on the data lake; coverage audit | PR |
| ML-ENTRY-SERVE-FIXES | session_01AFoLuK7HeWiq4wwSKqN47K | Alpaca 1h lookback + refused SHORTs + ml_entry LTR outcome table | PR |
| OPERATOR-NOTES-DRAIN-20261105 | session_01AFoLuKMSCYK8SPEYVeekJn | acting on the operator's 11 console notes | report: OPRA agreement link + popup-ready questions -> relay to operator as popups |
| LTR-GRADER-COVERAGE | session_01AFoLuJmWFqZdNS97nL9Htr | #23220 non-crypto candles (pytest-run in progress); #23173 conflict | green sha -> merge; then invalid_level fix |
| GATEWAY-DISK-CLEANUP | session_01AFoLuKEvHHsY3TiJBsYh41 | step-D swap after #23212; #23261 draft | merged/deployed/observed evidence |

Archive when they own no open PR: OPERATOR-ANSWERS-0505B (session_01AFoLuJT8TkysBjWHmKTqyJ), desk-wake 10:00Z (session_01AFoLuLJWr6VBDhCzYibyYe), TICK-STAGE2 (session_01AFoLuLzq1snbogF2qX97Pi; #23248 and #23274 both MERGED -> archive now), other review_ready LIVE-REVIEW/desk lanes in list_sessions.

## PRs needing the manager (held PRs do NOT auto-merge -- merge by hand with the full 40-char expectedHeadSha; touch the merge-claim marker first)

- #23237 OAuth -- merge on green (head 3136f3ae...).
- #23225 WSD-S2 -- merge on green (operator "Deploy when green").
- #23273 X-Diag-Token -- merge on green (data-settled Tier 2).
- #23252 breakout_2 report mode -- needs CI to start first (see lane row).
- #23257, #23220 -- lane PRs, merge on green.
- #23267 WSD-S3 row -- lane fixing roadmap-map-guard.
- Manager self-land register PRs: #23279, #23281 (carries the 31% usage reading) -- confirm they land.

## Triggers targeting the OLD session (recreate on new, then disable old)

Recurring (2):
- trig_01UgWLZNzFa6NHMteFp6QBQi "Manager lane check-in (every 3h)" cron `17 */3 * * *`
- trig_01NH8TE6FyFZCZQkguLphYVB "Manager review (once daily: 05:52Z after the 05:30Z report)" cron `52 5 * * *` (its step 4b backlog drain must survive every handover)
One-shot (2, due 11:52Z -- if they fire on the old session the old manager handles them; else recreate on new):
- trig_011eho5h2ga8UC7E9zFrC4Y6 "Read tick_cost relay #23278; archive TICK-STAGE2" (also: dispatch PI-20261105-F2QX97PI-0001 journal write-lock holder when capacity allows)
- trig_01XAEc4EKEdor3AGUDj2CpHd "Check #23252 CI started; #23277 apply"
Routines on the assistant manager (session_011c3qoaBvGBioDWkPVToQSb) resolve the current manager by title at fire time -- no rewire needed: Weekly reset protocol (trig_01HmhkB9Suw5KF97hDPjK47c), Thursday walk-through (trig_01QhYHMBFSnMB5CYYAyy7MH6), Research-ops (trig_01UnRpzN513KbMjvJWFAf911), Lane check-in 6h (trig_01HxRVXSy6GGqWaWQXmGdJ97).
Fire-only lane-report triggers (no cron, no run_once_at) are not recurring and need no recreation.
Still to schedule: TICK-STAGE2-RECONCILE-OFFTICK 24 h close check at 2026-11-06T10:30Z (send_later on the new manager).

## Watched surfaces

- Ops-flags PR #17895 (subscribe the new session).
- Console artifact https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g (pinned; page db `inbox/*` = operator feedback; drain with ArtifactData list collection=inbox, mark docs filed). Probe artifact https://claude.ai/artifact/9rodWzoqc6xq6z1UP8WUBm.

## Capacity

Weekly 31% at 11:32Z (USAGE-READINGS.jsonl via spend_meter.py --record; on #23281). Sustainable ~11.0 pp/day gross, 7.4 net. Operator: keep pushing to Friday; close-up protocol near 90%.

## Undispatched rows

ETF-HISTORY-PIPELINE verify fix (4 stale renamed/delisted tickers; rank 2), PURGE-ARTIFACTS-TRUNCATED-PAGE (rank 3), ALERT-NOISE-SUPERSEDED-CANCEL (rank 5; work-digest "RUN cancelled" alerts are benign concurrency supersession), TICK-STAGE3-REGIME-SCORING (regime_bar_scoring ~45% of tick), PI-20261105-F2QX97PI-0001.

## New manager's first actions

1. V1 short diff against this doc (list_sessions mine limit 10, list_triggers enabled, get_session on self for depth). No routine work before the diff.
2. Recreate the 2 recurring triggers on the new id (same name/cron/prompt), disable the old; subscribe to ops-flags #17895.
3. **Republish the console from the new session** so the new manager owns it (operator ask): Artifact read url=https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g, then publish the saved file to the same url; then ArtifactComments watch it. Tell UI-CONSOLE-ITEM-FEEDBACK to keep publishing to the same URL.
4. Tell each live lane above the new id (create_trigger + fire_trigger, one line each).
5. Merge the green held PRs above; send_later for the 11-06 10:30Z TICK check.
6. Message the operator with the new session link and the console link (V5).

## Handover checklist

handoff doc merged (PR #__) · new session created by assistant (shallow, session_011c3qoaBvGBioDWkPVToQSb), Opus, tags manager + predecessor:session_01AFoLuJnejB97CXXc8yn9oA, depth __/8 · triggers recreated (n = __ of 2), old disabled · console republished by new manager · new manager subscribed incl. ops-flags · V1 diff · V2 audit (0 enabled on old id, incl. check-in `17 */3 * * *`) · V3 sweep with positive control · V4 round-trips · V5 operator told · STAND DOWN (old manager's last message links https://claude.ai/code/<new id>).
