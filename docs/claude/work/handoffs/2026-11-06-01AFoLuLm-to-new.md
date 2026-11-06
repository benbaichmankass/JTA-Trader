# Manager handoff 2026-11-06: session_01AFoLuLmhUKeUzHC6CHz2uP (Manager Session 2026-11-05b) -> new

> **Doc status:** `live` · category `handoff` · last verified `2026-11-06` · rotation reason: old manager context far past ~650k tokens; operator popup 2026-11-06 ~09:05Z "Hand over now (Recommended)".

## Operator decisions in force (verbatim popup answers, 2026-11-06 ~09:05Z)

- Rest of week until the Wed 2026-11-11 19:59 reset: **"Essentials + one lane"**. Weekly usage 59% at 08:41Z (operator screenshot; app: "at this pace you'll run out tomorrow afternoon"). Keep: live-review dispatch, desk wakes, merges, scheduled observations. Plus ONE Sonnet lane at a time working the backlog handoff (`docs/claude/work/handoffs/2026-11-06-backlog-drain-20261106.md`, money-at-risk first). No other new lanes.
- Alpaca ML `ml_entry_eq` on alpaca_paper: **"Shared ETFs + weights"**: trade the pool ETFs other alpaca_paper legs already trade, with an allocation-weights record in `comms/same_symbol_allocation/` per shared group. The WEIGHTS VALUES are not decided yet: propose them to the operator as a popup (e.g. equal split vs ml_entry_eq-minority), then one cheap lane writes the records and gets #23715 green (its only red check is same-symbol-allocation-guard). Paper first (Stage 1); real money is NOT decided.
- Handover: **"Hand over now (Recommended)"**.
- Standing: free resources only; no new gates; never place/amend/cancel orders; nothing spends Anthropic API credits; never raise the usage-credits toggle; never reword a classifier-refused action; Tier-3 needs operator approval unless data-backed (decide, ship, notify); console link https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g in every operator update.

## Merged + deployed tonight (Tier-2 data-backed; operator to be told in the brief)

| PR | what | evidence | revert |
|---|---|---|---|
| #23690 (860df4ad8) | venue_protection_snapshot: one write transaction per reconciliation sweep | db_lock_diag 3/3 bursts named reconciliation record_read; post-deploy batches 3-8 rows in 3-6 ms; 0 'database is locked' 07:03:45Z-07:43Z | git revert #23690 |
| #23671 (44c8595ad) | ml_entry reference set retried next tick instead of cached short | 04:00Z real-money bar lost to 10006 | git revert #23671 |
| #23736 (7e8c71c68) | ml_entry `reference_set_pending` (bar not consumed while fetches owed) + shared ref frames | 08:00Z ETH real-money bar refused feature_row_unformable inside cooldown; freshness guard stale_skips after 360 s so no late entry | git revert #23736 |

Running sha at 08:55Z: 7e8c71c68 (restart 08:55Z, 17/17 positions with SL+TP at broker).

## Pending observations (with owner)

- **12:05Z** PROD-LEGS lane (session_01AFoLuMJsTnw3XQ5A1BGFHC, trig_013xpUhzxcfQLWmEQv17f6ea) reads the 12:00Z ml_entry bar: per-symbol decisions for 5, pending lines, 10006 count, have=N/60, gave_up list. PASS = no feature_row_unformable / reference_symbols refusal at >=40 refs and no stale_skipped. Its report trigger currently targets the OLD manager id: tell the lane the new id.
- **13:05Z / 13:10Z** MECH lane (session_01AFoLuMw6ZYbSFSqsEQAvLT; trig_01Je8vEtJTC7tZNRruLyK6SC, trig_01PXTq7c2rgzLbaRA6hs3BEd) reads the 6h lock window after #23690 and updates PI-20261106-QSEQAVLT-0001. Tell it the new id.
- **#23710** (Tier 2, HELD, green): exit-pass telemetry batch. MERGE RULE: merge as soon as any 'database is locked' line appears after 07:03:45Z, or at the 13:10Z read if exit-eval max interval > 45 s; else wait for the operator.
- **PI-20261106-5A1BGFHC-0003**: Bybit bar-close IP budget (other builders lose cooldown ticks; 8/60 refs never return). Re-dated 11-07.
- Research-queue: first dispatch run on post-#23704 code (42184244110) was GREEN; e9a1-03 artifacts landed via #23720.

## Open PRs needing the manager

- **#23715** + **#23685** (ml_entry_eq serve, Tier 2, HELD): waiting on the weights popup above. #23715 body states the 10-ETF stage as a temporary tick-cost measure (exit: consecutive 'Tick result:' gaps < TICK_INTERVAL_SECONDS, no skipped ticks, no new Alpaca rate_limited from the trading path, then widen to 173).
- **#23710** see above.
- **#23707** backlog-drain close-out (self-land; check it lands).
- **#23695** (research-queue stamps) must stay open until b621-01's result is on main (it is now: research/results/RQ-20261101-b621-01/42172642285.jsonl landed in 42178811694) -> then let it merge or close.
- ML-FS-RECIPE notes PR (six ML-TIMEFRAME note lines + runner A/B class finding) and runner-fingerprint #23714 (auto-merge armed).

## Live lanes (tell each the new manager id)

| lane | session | state | owes |
|---|---|---|---|
| PROD-LEGS-DSR-DECISION | session_01AFoLuMJsTnw3XQ5A1BGFHC | idle | 12:05Z read; PI-0003 re-date/close |
| MECH-FOLLOWUPS-1105 | session_01AFoLuMw6ZYbSFSqsEQAvLT | idle, well over budget | 13:05/13:10Z lock read; #23710 |
| ML-FS-RECIPE | session_01AFoLuL5SYTWKXeuE1pfqzX | finishing | notes PR; then archive |
| LIVE-REVIEW (warm) | session_01AFoLuLTaooSYu2zcN9CFqx | idle since 08:04Z | archive after >2h idle (~10:05Z) |
| FREE-CAPACITY-RESIZE | session_01AFoLuMU3MxCGTowhCZcA89 | review_ready | Fri 22:00Z CME-break resize (gateway 6->3 GB, trainer 6->9 GB) |
| GUARD-PRUNE | session_01AFoLuLJcKD9rmeq5UfR7ye | review_ready | guard-delete list awaits operator approval |
| COST-BROKER-SOURCED | session_01AFoLuMKSgmBWC5qaX5JGK7 | review_ready | waits on days:30 funding re-pull (#23607) then backfill-broker-truth-costs |
| HF-LAKE-SQUASH | session_01AFoLuNBcS5NT55ncec8xTw | waiting | after 08:30Z trainer pin read (trainer-vm-diag), close-out |

Archived this session (finished): WSD-S6D, ML-ENTRY-ALPACA-A41F (equity), BACKLOG-DRAIN-20261106, desk-wakes 06:00Z/08:00Z, and earlier lanes.

## Triggers to rewire (recreate on new, disable old)

Recurring on the OLD id (2):
- trig_0157VpkhtktymdakZmbnW4Bf "Manager lane check-in (every 3h)" cron `17 */3 * * *`
- trig_012pCRDmuj7GG94uaPqrXRGx "Manager review (once daily: 05:52Z)" cron `52 5 * * *` (step 4b backlog drain must survive)
One-shot on the OLD id: trig_01H7EsvKXW8UsQqtXCWxRWTL (09:05Z lock recurrence + register notes, see "Register notes owed").
Assistant-manager routines resolve the manager by title (no rewire): weekly reset, Thursday walk-through, research-ops, 6h lane check-in.

## Register notes owed (one self-land PR)

- LTR-GRADER-COVERAGE: tighten options invalid_level (atr:1.0/1.5/2.0) not flagged by packet_health (AVAX scalp review 07:51Z).
- PI for venue_sl_diverges STALE-READ race: 08:02Z ADA pkg-78342b61 wake fired on venue SL 0.1875 vs package 0.186646 right after the package SL moved; venue read 0.1866 at 08:02:27Z (0.02 ATR). Fix: re-read the venue (or 2 consecutive reads) before emitting after a package SL change. Also find which path moved the package SL 0.18747->0.186646 between 06:03Z and 08:02Z.

## Operator decisions still open (popups, most important first)

1. Weights for shared-ETF ml_entry_eq groups (above).
2. BRANCH_PROTECTION_TOKEN secret missing since ~03:26Z (branch-protection-sync red; re-create fine-grained PAT, Administration: write, this repo only).
3. GUARD-PRUNE delete list approval.
4. Flatten audit answers #4 TLT, #5 MGC, #11 detectors.
5. settings.json hook shrink (classifier-blocked; operator applies).
6. board-post.yml deletion (human-merged PR).
7. OCI_CLI_* and HF_TOKEN secrets still needed?
8. HF frozen-lake deletion + loader change (Kaggle copy verified, 11 parts, 74.4 GB).
9. sp500-membership-refresh: 0 runs in 90 days.
10. Book concentration (almost all short).
11. Runner backlog.

## Findings this session worth carrying

- LightGBM fits on GitHub runners fall in exactly two deterministic classes by runner (hardware suspected, unverified); exact-reproduction tests must record the runner class (#23714; PI-20261106-UE1PFQZX-0001).
- Trainer ~20 CPU-min load = replay-pregate-nightly (04:46-06:07Z); next step on TRAINER-REPLAY-PREGATE-OFFLOAD: move it off the trainer or out of that window.
- Timeframe re-runs b620-b626 all graded; nothing beats 1h.

## Validation (V1-V5) — filled by the new manager

handoff doc merged (PR #__) · new session created by assistant (shallow, session_011c3qoaBvGBioDWkPVToQSb), Opus, tags manager + predecessor:session_01AFoLuLmhUKeUzHC6CHz2uP, depth __/8 · triggers recreated (n = __ of 2), old disabled · console republished by new manager · new manager subscribed incl. ops-flags #17895 · V1 diff · V2 audit (0 enabled on old id) · V3 sweep with positive control · V4 round-trips · V5 operator told · STAND DOWN.
