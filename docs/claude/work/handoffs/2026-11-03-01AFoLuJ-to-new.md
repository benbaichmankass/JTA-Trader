# Manager handoff 2026-11-03: session_01AFoLuJ1apgy8sfngu4WyNH (Manager Session 2026-11-01a) -> new

> **Doc status:** `unknown` · category `handoff` · last verified `2026-11-03` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md) · rotation reason: operator popup ~06:30Z ("Hand over to a fresh manager now") to cut usage (old manager context ~611k tokens; weekly plan usage 89% at 06:28Z, reset Wed 2026-11-04 18:00Z).

## Operator directives in force (verbatim where quoted)

- USAGE CUTS until the Wed 2026-11-04 18:00Z reset (popup ~06:30Z, all three chosen): "Pause paper-only reviews (Rec.)", "Pause desk event-alert wakes", "Hand over to a fresh manager now". Encoded in the check-in routine prompt (trig_01TXgRdX3quaGdjGV6py4SkR): paper-only live reviews paused unless within 0.25R of stop or bracket missing/diverged; desk-trigger-wake markers get NO session; regular desk-wake scans and short-hold-wake lanes continue; real-money/prop reviews always run. Keep lanes lean; defer drains/builds to after the reset.
- The hourly sweep (trig_01EUaa3vtb14iFcfSuvRM6XW) was moved to every 4 h (`29 */4 * * *`) at 06:29Z; it stops after the reset.
- ETF history store: "Keep it on the trainer (Rec.)" (popup ~05:56Z). Implemented in #22571 (switch ETF_LAKE_PUBLISH=0) + #22572 (comment), both armed.
- ADMISSION-JOURNAL-LAG-RACE: "Yes, build and ship (Rec.)" (popup ~06:01Z, Tier-2 order path). Lane session_01AFoLuM2FLcRdWk9V9fXTzh owns build, merge, deploy, verify (PR #22574).

## Live lanes (id, doing, owes) -- each reports to the OLD manager id; tell each the new id

| lane | session | doing | owes |
|---|---|---|---|
| ADMISSION-JOURNAL-LAG-RACE | session_01AFoLuM2FLcRdWk9V9fXTzh | Tier-2 admit_slice journal re-read (#22574) | merge + pull-and-deploy + version check + 3-line report |
| ETF-HISTORY-PIPELINE | session_01AFoLuMYG7uXtDtpTDvai3R | trainer-store decision (#22571/#22572); backfill ~681 symbols left, ~8 h | 2-line report; archive after |
| RESEARCH-CAPACITY | session_01AFoLuJ6GMS3Mxgdk4o26cZ | refill-on-completion (#22561, armed) | in-flight avg vs 0.82 baseline over 1-2 h; whether RQ-20261102-5e03-01 dispatched |
| STRUCTURE-EXITS-BUILD | session_01AFoLuN875snqTgX5MmcKyE | verdicts read; re-armed 5e01-02/03/04 (#22559 merged) | 5e03-01 verdict + re-run verdicts; checklist note on STRUCTURE-EXITS-DEFAULT |
| RESEARCH-AUTHOR (assistant's) | session_01AFoLuKSx62y7rQkDtwf5SR | 14 new units, PR #22578 (HOLD) | wakes manager when CI green -> manager merges |

## PRs needing the manager

- #22578 research units (HOLD): merge when green (review: units only).
- #22574 admission fix: the lane merges under the operator OK; manager only watches.
- Armed self-land (no action unless red): #22561, #22570, #22571, #22572, #22573, #22575, #22579.

## Triggers targeting the OLD session (recreate on new, then disable old)

Recurring:
- trig_01EUaa3vtb14iFcfSuvRM6XW "Hourly lane + PR sweep (until reset)" cron `29 */4 * * *`
- trig_012rqbKcvC3xD2gUSudCieKE "Manager review (twice daily...)" cron `52 5 * * *`
- trig_01TXgRdX3quaGdjGV6py4SkR "Manager lane check-in (every 6h until reset; 3h after)" cron `17 */6 * * *` (prompt carries the USAGE CUTS block)
One-shot/fire-only lane-report triggers are created by lanes per report; no pending send_later wakes.

## Open items / state

- Trades: all live reviews HOLD. Real money bybit_2: ml_entry ADA short ~+1R (stop still original), SOL short stall (HOLD, 24 h time stop), XRP short ~flat. Book = 7 crypto + 3 metals shorts; concentration filed on BOOK-CORR-VIEW-LTR (#22575). Desk ETH demo short (claude_desk, bybit_1) open past its short-hold cap; owned by later desk wakes.
- Research: landing bugs fixed (#22530/#22542/#22545), Kaggle CPU auth fixed (#22550), caps 6->10; b62x records on main for the Wed 09:07Z Tier-3 ML read (trig_018a6Fyf7C9aAN5B8CBbvnCV). Structure-exit static grid FAILED on XRP 4h / SOL prop / ETH prop; IAUM/GLD indeterminate (n38<39); 5e03-01 pending.
- Filed today: ML-ENTRY-LTR-OUTCOME-TABLE (ml_entry reviews judgement-only), LTR-0 atr_stop_mult note, COST-STACK-RECOST-SWEEP decision (b) (incl. ict_scalp_eth_15m flip -> Tier-3 demotion check), 4 pipeline items from the drain.
- Operator's hands: PROP-SILENCE-ALERTS clause 2 (close breakout_2 phone app, confirm dead-phone ping on Telegram).
- Deferred to after the reset: backlog drain (133 unrouted, ~270 landed_unproven), re-cost sweep, ML-ENTRY-LTR-OUTCOME-TABLE build, concentration research.
- Usage readings recorded: 80/84/85 (11-02), 89% (11-03 06:28Z, #22579).

## New manager's first actions

1. V1 short diff against this doc (list_sessions mine limit 10, list_triggers enabled, get_session depth). No routine work before the diff.
2. Recreate the 3 recurring triggers on the new id (same name/cron/prompt), disable the old ones; subscribe to ops-flags PR #17895.
3. Tell each live lane above the new manager id (create_trigger + fire_trigger), one line each.
4. Point last_review.by at the new id on the next daily review.
5. Keep the USAGE CUTS until the reset; the reset protocol (trig_018F2BmrzKwWTYoSYCCbroqy) restores cadence.

## Handover checklist

handoff doc merged (PR #__) · new session created by assistant (shallow), Opus, tags manager + predecessor:session_01AFoLuJ1apgy8sfngu4WyNH, depth __/8 · triggers recreated (n = __ of 3), old disabled · new manager subscribed incl. ops-flags · V1 diff · V2 audit (0 enabled on old id) · V3 sweep with positive control · V4 round-trips · V5 operator told · STAND DOWN (old manager's last message links https://claude.ai/code/<new id>).
