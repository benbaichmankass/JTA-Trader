# Manager handover 2026-11-04 — session_01AFoLuHgZaSYnm9avjeZE33 (Manager Session 2026-11-04a) → new

> **Doc status:** `live` · category `handoff` · last verified `2026-11-04`

Old manager context: 756k of 1M tokens at 22:23Z (MEASURED, get_session), with auto-compaction at 784k. The operator asked for a rollover at a good cutoff ("you're already past the context limit"). Cutoff: weekly planning is closed, the combined deploy is finished and observed, and no merge or deploy is half-done.

## Live lanes (id · row · doing · owes)
| Lane | Session | Doing | Owes the manager |
|---|---|---|---|
| PLANNING-CLOSE-20261104 | session_01AFoLuJnp9dqcFgSg8zYP38 | landing every weekly-planning disposition in ONE self-land PR, plus the WEEKLY-PLANNING outcome | PR number + head sha; merge |
| TP-REALMONEY-UNITS (Opus) | session_01AFoLuMRyM6AERSLy3HFeHR | one real-TP unit for each non-compliant real-money leg; close TP-DOCTRINE | PR (likely held); per-leg results; any Tier-3 proposal goes to the operator |
| PULLBACK-2H-WF | session_01AFoLuKZMnjLY7PRzmP72NE | re-open the pullback-2h walk-forward | PR (held); result or due date |
| PROMOTE-1H-SURVIVORS-20261104 | session_01AFoLuKxcXKrTDHkZJUwzxA | wake at 22:40Z writes the per-leg note once #22971 is on main | landing PR |
| AUD-PROP-VENUE-POSITIONS | session_01AFoLuJ9jTgPYuzyuTxA21Z | #22982 (operator OK "Merge when green") + #22986 records | head sha when green; post-merge observation |
| PLANNING-PREREAD | session_01AFoLuMqvFfUd8mRSRBNiuy | #22992 pre-read | merge, then archive |
| ML-ENTRY-RETRAIN-CADENCE | session_01AFoLuKxLAGHCQUGQ43ognm | #22942 (Tier 2, operator OK 20:08Z "Merge when green") | green sha |
| PR-REHOME | session_01AFoLuLWyTHmc9hQNccVuJQ | #22959 gateway-disk-report (held) | green sha |
| PROJECT-PITCH-DECK | session_01AFoLuLr3fpRCuMnfGbGGoK | #22946 deck (hold; manager review) | — |
| ML-ENTRY-ALL-ACCOUNTS | session_01AFoLuHssTryUyRELsfP54s | #22928 Tier 3 HOLD (stacked on #22900, which is merged) | operator decision |
| SYSTEM-AUDIT-INTEGRATION | session_01AFoLuLCbQTSU5jK9dbmcvU | #22954 design draft | builds to dispatch (below) |
| TIER3-RESULTS-READ | session_01AFoLuMj321NrKXRdGCnycN | blocked; 5e04-01 landed via #22925 | 5e01-02/03/04, 5e03-01 and RQ-20261104-7a3e-01 still need runs |
| ROADMAP-REBASELINE | session_01AFoLuLRptjztVwnrGU9JMR | #22974 (auto-merge armed) | archive once merged |

Finished but not yet archived: SPOTCANDLES-AUDIT, SHARED-BRACKET-FIX, PAPER-MECHANICS, BACKLOG-DRAIN-20261104, DEEP-AUDIT and the CJ7 children. Archive each once it owns no open PR.

## PRs needing the manager (22:23Z)
- I merged main into these at 22:22Z after #22991 cleared the repo-wide operator-owed-guard: #22971, #22990, #22974, #22981, #22986, #22982, #22959, #22942, #22946, #22992.
  - Auto-merge is armed on #22971, #22990, #22974 and #22986.
- **Held; the manager merges when green:**
  - #22942 (Tier 2, operator OK). After it merges, do a SECOND RESTART in this order: pause-autoheal → pull-and-deploy → resume-autoheal. Open ONE system-action issue at a time.
  - #22982 (operator OK).
  - #22959. Then run the gateway-disk-report system-action. If the ib-gateway container log is the writer, apply the cap and truncate it (operator pre-approved 21:31Z, Tier 2) and report before/after. Pipeline item PI-20261104-GWDISK-0001 is due 11-05.
  - #22981 (queue units qqq 7fdb-01 / slv 7fdb-02).
  - #22992 (pre-read).
  - #22946 (deck; review it first).
- #22928: Tier 3 HOLD, operator decision.
- #22966 (manager record of the group-level ML universe decision) is CONFLICTED. Check whether the note is already on ML-UNIVERSE-RULE / ML-ENTRY-ALL-ACCOUNTS; if so, close it with that reason. Otherwise route it to a lane.
- Automation PRs #22993, #22994, #22969, #22968, #22967: normal hygiene.

## Operator decisions tonight (exact wording; all being landed by PLANNING-CLOSE)
- 21:31-21:33Z:
  - Promotions "Check, then promote (Recommended)"
  - Gateway disk "Pre-approve, fix if confirmed (Recommended)"
  - Foxhound-1 widening "Test, widen on pass (Recommended)"
  - Symbol-set check "No check"
  - Netting "Research offline only (Recommended)"
  - Milestones "Adopt both"
  - DATA-DERIV-ARCHIVE "Schedule it (Recommended)"
  - Refill "Prop fix now, rest as lanes finish (Recommended)"
- ~22:05Z:
  - USO "No, USO stays off real money (Recommended)"
  - SLV "Reopen, promote if it clears (Recommended)"
  - #22982 "Merge when green (Recommended)"
- Planning ~22:12-22:25Z:
  - carry-over "TP-DOCTRINE,REVIEW-FOLLOWTHROUGH,Research SLOs" (LTR pricing moved to next week)
  - GLD "Keep it, stop re-raising (Recommended)"
  - real-money TP "Yes, test all 6 (Recommended)"
  - pullback WF "Re-open it (Recommended)"
  - survivor definition "Registered-rule PASS on held-out data (Recommended)"
  - triage "research-ops owns it, daily (Recommended)"
  - exit head "Register + gate now"
  - queued rows "LIVE-DECAY-MONITOR,PASS-TO-DECISION-SLO,ML-LEARNING-LEDGER"
  - roadmap "Apply the diff as proposed (Recommended)"
  - lapsed targets "Record outcome, re-target +1 week (Recommended)"
  - regime "Author regime units this week (Recommended)"
  - order "Agree with the order (Recommended)"
  - pacing "2-3 lanes, stop new work at 85% (Recommended)"
  - schedule "No changes, just those fixes (Recommended)"
- Standing: manager review ONCE daily, "we switched the twice daily to once daily leave it like that".

## Workplan order (agreed) and pacing
Run 2-3 concurrent work lanes and stop new work at 85% of weekly usage (0% at the 18:00Z reset).
1. Money-path items tonight: deploy follow-ups, #22942 restart, gateway disk.
2. Real-money TP x6 + close TP-DOCTRINE (running).
3. Pullback-2h WF (running).
4. **NEXT SLOT:** EXIT-HEAD-ETH-REGISTER: register and gate the trend_donchian_eth exit head. Opus, Tier 3: proposal to the operator.
5. Research SLO fixes.
6. Backlog drain + research-ops triage.
7. LIVE-DECAY-MONITOR / PASS-TO-DECISION-SLO / ML-LEARNING-LEDGER.
8. Roadmap diff + regime units.
9. Audit-design builds (ALERT-LEDGER-TO-MANAGER, CHECKLIST-STATE-TRUTH, TICK-DURATION-115S), CI-demand lane (COMPUTE-ALLOCATION B5/B6/B8; kill PI-20261103-RAM7EH86-0002..0005 after verifying), DATA-DERIV-ARCHIVE, a24c-01 unblock (PI-20261104-ELSFP54S-0002, Foxhound-1 widening), register consolidation.
10. /perf-followup (Opus).

## ⚠️ RE-PRIORITIZATION (operator, 2026-11-04 ~22:27Z, verbatim; supersedes the order above)
"The work from the redesign and like strategic changes that we want to make, that should take priority alongside real money, even if it means burning a little faster at first. But part of the point of putting that off until the reset was that we could start with that and then do the rest of the work within the updated system. Especially like as far as streamlining the workflow, not using the repo as a database, like we need to see where that's taking us and make sure that our weekly work plan is in line with the system that we're building this week and not what we have now."

What the new manager must do with it:
1. **Tier A (now, together):** real-money items AND the redesign / strategic builds. The redesign covers:
   - SYSTEM-AUDIT-INTEGRATION design #22954 and its builds;
   - REGISTER-CONSOLIDATION;
   - moving work state off the repo-as-database;
   - workflow streamlining and CI load (COMPUTE-ALLOCATION B5/B6/B8);
   - UI-LIVE-STACK-REDESIGN / UI-OVERVIEW-HEALTH-CARDS;
   - ML-ROADMAP-MECE.
   A faster burn at first is accepted, still within the 85% stop.
2. **Real-money lanes keep running:** TP-REALMONEY-UNITS, the #22942 restart, gateway disk, and EXIT-HEAD-ETH (trend_donchian_eth trades real money on bybit_2).
3. **Everything else is RE-SCOPED to the system being built this week, not today's:**
   - LIVE-DECAY-MONITOR, PASS-TO-DECISION-SLO, ML-LEARNING-LEDGER, research-SLO fixes, the backlog drain's register writes, and new registers or ledgers;
   - for each, check whether it should be built on the new store or flow; if so, sequence it after that piece exists.
   - Do not build new repo-JSON registers this week.
4. **First action:** read #22954 and the REGISTER-CONSOLIDATION / COMPUTE-ALLOCATION rows. Write the redesign build sequence (what replaces repo-as-DB, in what order, what each later item depends on). Bring the operator ONE revised weekly workplan for confirmation (popup), then dispatch the first redesign lanes.

## Observations owed (deploy 21:46Z, sha d8a34e41b)
- Trade 6860 should show exit_reason tp at 1.3177 and pkg-4eed7ec08f5845c1 close_reason tp, after the :20 fills pull. Then note SHARED-BRACKET-FIX.
- Journal grep for "Error fetching OHLCV|BadSymbol|Traceback" since 21:44Z should be 0. Then close PI-20261103-SPOTCANDLES-0001.
- position_telemetry should have a row for every open structure_exit package. Then note PAPER-MECHANICS.
- ETH 4h on bybit_2 (pkg-430a556e, real money): breakeven tighten to SL 2378.43, recommended under MD-TRADE-DESK. Confirm it was applied.

## Register items not yet filed (route to a lane or the backlog drain)
- (a) check_live_review_records.py fails on reviews.jsonl rows 85/102/103.
- (b) e4_oi_shock_1h trades on bybit_1 with no Stage-0 evidence record.
- (c) live_review_outcomes returns no_candles for the 4h atr cells.
- (d) bybit_2 funding settlement absent for 24h, with no read route.
- (e) telemetry_absent on open paper packages.
- (f) system-actions concurrency: a label-skipped run from any issue opened just after a system-action displaces its pending run. Resume-autoheal #22985 never ran because of this. Fix with a skip-job concurrency group or a label filter before concurrency.
- (g) The reset-protocol routine trig_018F2BmrzKwWTYoSYCCbroqy (assistant session) still says '52 5,17'. The assistant's edit was refused by auto mode, so it needs the operator to approve the edit in the assistant session. Until then, treat step (1) as once daily.

## Triggers on the old session (rewire per manager SKILL step 3)
Recurring:
- trig_01BW3J2HZcTHXEsY5jjiGWS5 "Manager review (once daily…)" `52 5 * * *`
- trig_01GCuhhWthEpauptAcgyq1Af "Manager lane check-in (every 3h)" `17 */3 * * *`

One-shot, still pending:
- trig_01L5t122HnH8FrixegDjhoZ1 "Post-deploy observations 22:30Z" (the old manager runs it if it fires before stand-down)
- trig_019wCcXnHB24ntirNGeHv7Z8 "Re-enable Thursday planning task" 2026-11-05T07:00Z (re-enables trig_01QhYHMBFSnMB5CYYAyy7MH6 for 11-12)

Lane-report triggers (no schedule) are spent; ignore them. Watched: ops-flags PR #17895.

## New manager's first actions
1. V1 short diff against this doc.
2. Recreate both recurring triggers and the 07:00Z re-enable on the new session; disable the old ones.
3. Subscribe to #17895.
4. Tell every live lane above the new id (fired trigger).
5. Merge the held PRs as they go green; run the #22942 restart and the gateway-disk action.
6. Dispatch EXIT-HEAD-ETH-REGISTER.

## Handover checklist
handoff doc merged (PR #__) · new session created by a shallow session, Opus, tags `manager` + `predecessor:session_01AFoLuHgZaSYnm9avjeZE33`, depth __/8 · triggers recreated (n = __ of 3), old disabled · prompts and checklist refs updated · new manager subscribed incl. ops-flags · V1 diff · V2 audit (0 on old id, incl. check-in `17 */3 * * *`) · V3 sweep with positive control · V4 round-trips · V5 operator told · STAND DOWN done (old manager's last message links the new session).
