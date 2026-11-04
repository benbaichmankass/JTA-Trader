# Manager handover 2026-11-04 — session_01AFoLuLMKGkvg6UbCzdxjNR (Manager Session 2026-11-03b) → new

> **Doc status:** `unknown` · category `history` · written 2026-11-04 ~18:05Z by the outgoing manager. Reason: context 669k of 1M (past the
> ~650k rotation point, manager SKILL § Manager handover). Weekly usage reset at 18:00Z and is now 0% (operator screenshot).

## First actions for the new manager (in order)

1. Do V1 (§ checklist below). Read the manager skill and this doc in full. From the canonical doc, read only what Start of session step 2
   names.
2. **Run the post-reset plan.** Its full text is the prompt of the disabled trigger `trig_01QVv8PHQ41W1kntcWZ88LQU` (read it with get_trigger).
   It was fired at 18:00Z into the OLD session, which is handing over, so run it in the NEW session. In summary:
   - **1. Reset protocol.**
   - **1b + 2 IN PARALLEL** (operator 2026-11-04 ~08:30Z: *"we can do the alpaca build in parallel"*):
     - **1b: AUDIT + STRATEGIC PLANNING.** The ML work is top priority next week. Schema: https://claude.ai/artifact/6kUJ5pa8HoQHNvpYXVj59f
       (built from docs; verify it). Rows on main:
       - `ML-ROADMAP-MECE` (rank 1);
       - `SYSTEM-AUDIT-INTEGRATION` (rank 1);
       - `SYSTEM-AUDIT-REPO-FLOWS` (rank 2; includes retiring the 5-min VM auto-sync in favour of manager-driven deploys);
       - `UI-LIVE-STACK-REDESIGN` (rank 3; push not poll, ticks off the VM);
       - `UI-OVERVIEW-HEALTH-CARDS` (rank 4).

       Audits come BEFORE any capacity design. Deep research into investment-grade practice is required.
     - **2: Alpaca ML build** (`ML-ENTRY-ALL-ACCOUNTS`), its own lane.
   - **2b: MONEY-PATH lanes.**
     - `PI-20261103-SPOTCANDLES-0001`.
     - `PI-20261104-MXMXDI3X-0001`: the shared-bracket bug. It is the most important. See § Money path below.
   - **2c: BACKLOG-DRAIN-20261104** (deferred from the 05:52Z review), plus #22570.
   - **3: COMPUTE-ALLOCATION-DESIGN**, after the repo-flows audit. kaggle_cpu was idle 266 min at 17:51Z with 9 runnable units and
     self-heal failed; fold that in.
   - **4: CI-STREAMLINE leftovers.**
   - **5: free moves** B5/B6/B8.
   - **6: open items.** Close #22772 (stale grading PR; the classifier blocked my close via `gh api`, and the MCP close worked on my own #22837).
   - **7: End the until-reset hourly sweep** `trig_017LW5GfXpze2uGjautyx7uA`.
3. The reminders below fire 18:25–18:40Z into the OLD session. Recreate them on the new id first (§ Rewire).

## Live lanes

| Lane | Session | Doing | Owes |
|---|---|---|---|
| LIVE-REVIEW 18:00Z batch | `session_01AFoLuMiqciU1RmHeiPWPEn` | Reset-time review of every open package. Priorities: real-money SOL long on bybit_2; IAUM 0.08R from its stop; ADA; 5 unmeasured packages; per-package bracket checks | A ≤10-line report **to the OLD id**. Re-point it, or read its post_turn_summary |
| CI-STREAMLINE | `session_01AFoLuHkvWi7dqNdMx6Ey51` | idle; 24-h re-measure trig `trig_0145HxfVQtHVjPRNpDboDbcG` at 23:45Z | A report to the manager (names the old id in its brief) |
| STRUCTURE-EXITS-ENABLE | `session_01AFoLuLeZMvgvxCmB3oAwAx` | idle, review_ready | Awaits the 5e04-01 regrade (see Research). On PASS, the unit's on_pass (regenerate `comms/strategy_evidence/ml_entry.json`, drop the bybit_2/ml_entry FIDELITY_BASELINE) needs **operator approval** |
| COMPUTE-ALLOCATION-DESIGN | `session_01AFoLuLNM3ZNUq9iNXXNDKa` | paused until after the reset | Resume at plan step 3 |
| SELF-HOSTED-RUNNER | `session_01AFoLuKnYJqnsFfrAM7Eh86` | idle, review_ready, paused | Fold into compute allocation |

## Money path (read before anything else)

- **Shared-bracket bug, `PI-20261104-MXMXDI3X-0001`.** On `bybit_1`, when a second package opens on the same symbol, its bracket REPLACES the
  first package's full-position SL/TP.
  - Seen on BTC: hedge mode, at 10:37Z (opposite direction) and 14:41Z (same direction).
  - Seen on XRP: one-way book, 14:44Z. XRP pkg-4eed7ec0 then closed `netting_attributed` at 14:50Z, which is a non-TP/SL/strategy close and so a bug.
  - ETH works correctly with two packages (each has its own partial qty-scoped bracket). Diff ETH against BTC/XRP.
  - `bybit_2` (REAL MONEY) at 15:12Z held one package per symbol, each with its own qty-scoped partial bracket, so there is **no current
    exposure**. The fix must land before bybit_2 can hold two packages on one symbol. Tier 2 needs one operator OK in chat.
  - Evidence briefs: triggers 18:25Z / 18:26Z / 18:27Z (below).
- **AVAX ghost:** pkg-4d1e90c9477e464e was OPEN in the journal at +1.21R, but the venue had no position (14:43Z).
- **Prop visibility gap:** `tradeify_1` / `velotrade_1` status has no positions field, and `breakout_2` read 0 open. So prop-leg trades cannot be
  verified. Add it to `SYSTEM-AUDIT-INTEGRATION`; it is in the 18:27Z brief.
- **Lost trades from `slice_budget_exhausted`:** `PI-20261104-BCZDXJNR-0002` (on main via #22844). `symbol_budget_trades: 1.0` starves testing
  legs on bybit_1. A Tier-3 sizing popup is owed once the 14-d refusal counts are in. The operator also proposed an ML position aggregator,
  noted on `ML-ROADMAP-MECE`.

## Research

- **RQ-20261103-5e04-01** (ml_entry SL-only verification, operator-requested) **PASSED on numbers**: arm F +0.0371 vs A +0.0271 R/decision,
  n=907, held-out, full cost stack. The verdict-file fix #22836 merged at about 10:27Z and the unit was re-armed. Confirm the graded verdict row
  landed. If it is PASS, bring the on_pass step to the operator.
- **RQ-20261104-5e05-01** (start-TP pull-in): blocked on the harness build `STRUCTURE-START-TP-ARM`.
- Research-ops gap: the 02:47Z and 08:47Z passes left no record. A producer_failed_rate breach of 0.312 was attributed to missing verdict.json
  in 15 ML units, with the fix on main.

## Routines and reminders targeting the OLD id (recreate on the new id, then disable the old)

Recurring (read each prompt with get_trigger and copy it verbatim):
- `trig_01LCYmDG9Lp7fN9SC1Tgn2vu`: Manager review, 05:52Z / 17:52Z daily. **The 17:52Z run today has not been seen in this session; check its last_run.**
- `trig_01FEPJqmEdSVgbpuPYcLSz2c`: Manager lane check-in. It ran every 6 h until the reset; restore the normal cadence (`17 */3 * * *`) and
  drop the expired USAGE CUTS / PACING text.
- `trig_017LW5GfXpze2uGjautyx7uA`: hourly sweep, until the reset. **Disable; do not recreate** (plan step 7).

One-shot reminders (pending):
- `trig_01Nv9E5EccZ4NkFiWm8zvWhw` (18:25Z): BTC shared-bracket evidence → MXMXDI3X lane.
- `trig_01AkGnrJLsFPQE1KzD6pjNr7` (18:26Z): AVAX ghost + XRP netting_attributed → MXMXDI3X lane.
- `trig_01K5JroKwxMii8LrmGe9Mcbe` (18:27Z): ETH-works clue + the prop visibility gap note.
- `trig_01NkE8MkRKntF4RKFVzwKUD2` (18:40Z): Tier-3 read of the ML timeframe b620–b626 + structure-exit 5e02 + ML-ENTRY-DYNAMIC-SL results
  (operator-approved 11-02). It needs ONE Sonnet lane at about $10, then a short operator summary and popups for any per-leg Tier-3 change.
- `trig_01QVv8PHQ41W1kntcWZ88LQU`: the post-reset plan, DISABLED after firing. Its text is the plan.

The remaining enabled triggers on the old id are fired report triggers with no schedule (LR reports, lane reports). Leave them; delete them
at stand-down.

## PRs needing the manager

- #22772 (close it), #22570 (backlog drain, conflicted → fold into BACKLOG-DRAIN), #22765 (draft, MODEL-NAMES close-out).
- Bot PRs that auto-merge, such as research batches and forecast-grade. Known bug `PI-20261103-DMX6EY51-0001`: a push after arming
  disables auto-merge; re-arm by hand.

## Operator directives from today (all are in rows; quotes)

- "before we get to the capacity usage, I want us to do a fuller audit of the system structure … I want us to have a full picture before we
  start designing" → SYSTEM-AUDIT-* rows.
- "the ML work is top priority for next week" → ML-ROADMAP-MECE.
- "the auto sync is a legacy flow … we can just have managers update/sync/restart the VMs at their own discretion" → note on SYSTEM-AUDIT-REPO-FLOWS.
- "I want to make sure data is being pushed, not the UI polling … tick-level data doesn't necessarily need to run through the VM" → note on UI-LIVE-STACK-REDESIGN.
- "we may want to think about an ML aggregator that takes the different trade packages and manages one unified position" → note on ML-ROADMAP-MECE.
- "we need to make sure that we're clear about how perform these trades so we don't keep losing trades because of technical errors" → PI-20261104-BCZDXJNR-0002 + MXMXDI3X.

## Handover checklist

- [ ] Handoff doc merged (PR #__)
- [ ] New session created by a SHALLOW session (assistant manager `session_011c3qoaBvGBioDWkPVToQSb`); Opus; tags `manager` +
  `predecessor:session_01AFoLuLMKGkvg6UbCzdxjNR`; depth __/8
- [ ] Triggers recreated (n = __ of 7: 2 recurring + 4 reminders + live-review report route), old ones disabled
- [ ] Prompts and checklist refs updated (`last_review.by`)
- [ ] New manager subscribed, including ops-flags PR #17895
- [ ] V1 diff · V2 audit (0 enabled on old id, incl. check-in `17 */3 * * *`) · V3 sweep with positive control · V4 round-trips · V5 operator told
- [ ] STAND DOWN: the old manager's last message links https://claude.ai/code/<new id>
