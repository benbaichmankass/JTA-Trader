# Manager handoff 2026-11-03 (2): session_01AFoLuJCo138TgfjBcbwcLh (Manager Session 2026-11-03a) -> new

> **Doc status:** `unknown` · category `handoff` · last verified `2026-11-03` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

## Operator directives in force (verbatim where quoted)

- QUIET UNTIL RESET (popup ~10:45Z): wake/act only for real-money/prop trade events, red CI on money-path PRs, and the structure-exit enable merge. The 4-hourly sweep trig_017PP87ay9ahBUYLaE2XCRsL is DISABLED (do NOT recreate it); the reset protocol restores cadence. Earlier USAGE CUTS (paper-only reviews paused unless within 0.25R of stop / bracket missing; desk trigger-wakes paused) still hold — they are in the check-in routine prompt.
- Promotions with both tracks green are MANAGER-merged on the data-backed rule, then the operator is notified; no operator merge, NO autoland (popup ~10:06Z "Manager merges (Recommended)"). Recorded in PR #22617.
- Mechanics and edge are independent tracks (operator ~10:00Z). PR #22617.
- Structure exits = the default exit unless something is proven better (operator ~07:05Z; "I'll take your recommendations here on the structured exits. We should set that configuration like you said" ~10:45Z).
- Alpaca ML build deferred: after the reset, weekend build, test Mon 11-09 (rows ML-ENTRY-ALL-ACCOUNTS / ALPACA-LIVE-ACTIVITY-ML, PR #22625). General-vs-account-specific ML variants = Thursday planning.
- Self-hosted runner on the trainer VM approved (popup ~10:07Z "Self-hosted runner (Recommended)"). Operator: "we should have a token that can do that" (BRANCH_PROTECTION_TOKEN is the candidate; the old manager's relay of it to the lane was refused by the auto-mode classifier as credential exploration — the operator was told; do not route around it).
- Model names (dog breeds) final: Foxhound (entry), Labrador (exit/in-trade), Collie (regime), Chihuahua (5m regime), Mutt (baselines), Canaan reserved (prop survival), Beagle/Pointer/Mastiff/Whippet/Basset unassigned. PR #22599.

## Live lanes (report to the OLD id; tell each the new id)

| lane | session | doing | owes |
|---|---|---|---|
| STRUCTURE-EXITS-ENABLE | session_01AFoLuLeZMvgvxCmB3oAwAx | Tier-3 config: `structure_exit: "pivot=5"` on ~21 wired legs (ON/OFF table in its prompt; IAUM/GLD OFF by manager judgement) | PR number -> MANAGER MERGES (rule-backed) -> lane deploys + verifies sha |
| SELF-HOSTED-RUNNER | session_01AFoLuKnYJqnsFfrAM7Eh86 | Tier-2: runner on trainer VM, label jta-infra, PR-trigger guard | token need / held PR (manager merges under operator OK) / verification |
| MODEL-NAMES | session_01AFoLuLzUgA9eDPgE5WQbPv | PR #22599 self-land | nothing; archive when merged |
| SOAK-REGRADE | session_01AFoLuLuqcjQnad6gnsZYUn | closed out; subscribed to #22616 | archive when #22616 merges |
| ML-ENTRY-V2-SILENT | session_01AFoLuKpHUayJPDAWZYLHEB | done; PR #22613 (Tier-3 by filename, logging only, reviewed safe by old manager) | MANAGER MERGES #22613 when CI green |
| ML-PROP-MOVINGTP-GATE | session_01AFoLuK7cV1eLb1xgbhtD32 | done; PR #22598 | archive when merged |
| GH-QUEUE-DEDUPE | session_01AFoLuJd6jyqUwdsszsQ3zt | done; PR #22600 | archive when merged |
| ADMISSION-JOURNAL-LAG-RACE | session_01AFoLuM2FLcRdWk9V9fXTzh | done; deployed+verified; row PR #22603 | archive when merged |
| ETF-HISTORY-PIPELINE | session_01AFoLuMYG7uXtDtpTDvai3R | backfill running; #22571 merged | archive |
| STRUCTURE-EXITS-BUILD (old) | session_01AFoLuN875snqTgX5MmcKyE | parked; 5e01-02/03/04 + 5e03-01 verdicts pending | archive |
| LIVE-REVIEW pkg-b8aef658 | session_01AFoLuJ6DckkMow3MC9Vvb8 | HOLD row written | archive |

## PRs needing the manager

- #22613 merge when green (ml_entry logging; prerequisite for PI-20261103-MLV2-0001 live-vs-shadow v1 scoring gap on REAL MONEY — next step after deploy: dispatch a parity lane, money path, ahead of other builds).
- STRUCTURE-EXITS-ENABLE PR (number pending) — merge, then the lane deploys.
- SELF-HOSTED-RUNNER held PR — merge under the operator OK.
- Self-landing, no action unless red: #22616, #22617, #22599, #22598, #22600, #22603, #22625, #22587 (merged already: verify), #22570.

## Triggers targeting the OLD session (recreate on new, disable old)

Recurring: trig_0114UGw8RsJh2QLV416jnMmB "Manager review (twice daily: ...)" `52 5 * * *`; trig_01Uyt1YCYHj7ufbHfu398KUS "Manager lane check-in (every 6h until reset; 3h after)" `17 */6 * * *`. DISABLED, do not recreate: trig_017PP87ay9ahBUYLaE2XCRsL (4-hourly sweep).
One-shot: trig_01YVgDezUrR8eNYCLAk6NxYx "Tier 3: read ML timeframe + structure-exit results" run_once 2026-11-04T09:07Z.

## State

- Trades: real money bybit_2 ml_entry ADA/XRP/SOL shorts open (HOLD reviews). Prop accounts flat; last prop signal 11-02 04:01Z ETH long (SL hit). No stuck packages (venue vs journal reconciled on all readable accounts 07:44Z).
- Infra: GitHub hosted-runner queue saturated (108 queued 10:05Z) — research and deploys throttled; self-hosted runner is the fix. Live VM mem 15% / disk 64%.
- Findings filed today: PI-20261103-01AFOLUJ-0001..0005 (breakout_2 exits unrecorded + Trades-tab read flow with screenshots; possible wrong-side prop stop; cloud phone twin for next week; live-review record checker red on legacy rows; retired gld_pullback_1h still holding a paper position), PI-20261103-MLV2-0001 (v1 live-vs-shadow scoring gap), PI-20261103-6GNSZYUN-0001..0012 (iterate orphans, ib_paper soak contracts, bybit mechanics path).
- Promotion candidates: slv_trend_1h + scha_trend_long_1d holdout units RQ-20261103-5a03-01/-02 fire after #22616 merges; tlt INDETERMINATE accruing; tqqq C3 forward unit RQ-20261103-5a03-03 (~3y to n=25 — pooled daily-trend test is a Thursday planning item).

## New manager's first actions

1. V1 short diff (list_sessions mine limit 15, list_triggers enabled, get_session depth). Keep the handover < ~60k tokens.
2. Recreate the 2 recurring + 1 one-shot triggers on the new id; disable the old ones; subscribe ops-flags PR #17895 and PRs #22613, #22616, #22617.
3. Tell STRUCTURE-EXITS-ENABLE, SELF-HOSTED-RUNNER and ML-ENTRY-V2-SILENT the new id (one line each); archive the finished lanes listed above as their PRs merge.
4. Stay QUIET until the reset: no new dispatches except money-path (v1 parity after #22613 deploys) and the reset protocol.

## Handover checklist

handoff doc merged (PR #__) · new session by assistant (shallow), Opus, tags manager + predecessor:session_01AFoLuJCo138TgfjBcbwcLh, depth __/8 · triggers recreated (n = __ of 3), old disabled · subscribed incl. ops-flags · V1 · V2 · V3 · V4 · V5 · STAND DOWN (old manager's last message links https://claude.ai/code/<new id>).
