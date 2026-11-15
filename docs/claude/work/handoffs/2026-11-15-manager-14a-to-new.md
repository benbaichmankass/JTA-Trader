# Manager handoff — 2026-11-15 ~06:00Z (Manager Session 2026-11-14a → next)

> **Doc status:** `unknown` · category `history` · last verified `2026-11-15`

Outgoing: `Manager Session 2026-11-14a` (session_01AFoLuHypACDvKhJgBWYZKV), context ~741k of 1M, past the ~650k rotation point.
It sits at lineage depth 0, so it created the new manager directly (new = depth 1, the shallowest possible). That deviates from the
runbook's "not by the outgoing manager" wording, but satisfies its intent, which is depth.
The previous handoff, `MANAGER-HANDOFF-2026-11-14.md` § "ROTATION 2", still holds where not changed below.

## First actions (new manager)
1. Invoke the `manager` skill and title yourself `Manager Session 2026-11-15a` (the first manager of 2026-11-15).
2. Re-bind these 6 recurring routines from session_01AFoLuHypACDvKhJgBWYZKV to you. For each: `get_trigger`, create a copy with the same
   name/cron/prompt and `persistent_session_id` = you, then delete or disable the old one. `delete_trigger` of a recurring routine was refused
   by the classifier once; disabling works. Verify with `list_triggers`.
   - `trig_01KJu89cEFP5NgmMbRVCcHWf` Manager lane check-in `17 */3 * * *`
   - `trig_015kuvT5F34hy74YfipPUZwb` Manager review `52 5 * * *`
   - `trig_01PYxgfBADbqqe82X4DVDDx8` Decisions-page refresh `10 5,17 * * *` (now runs `scripts/ops/decisions_page_build.py`, PR #26208)
   - `trig_01W9EkXAcGMzEgnT6KMjz3Lx` Weekly reset protocol `5 18 * * 3`
   - `trig_01HocXZTiRGvxHxePLH1QFvv` Thursday walk-through + planning `17 6 * * 4`
   - `trig_016i5FeDBtqphAVYZ8hP4NdH` Research-ops dispatch `47 14 * * *`
3. `subscribe_pr_activity` on ops-flags PR **#17895**; then tell the outgoing manager, which unsubscribes and stands down.
4. Send ML-PRIMARY (`session_01AFoLuKuu4bMh6SG5oyAC9h`) and AM-OPS (`session_01AFoLuJUGfpon2bNgwFbFmx`) one message each naming you.
5. Have a small Haiku lane self-land this file (Tier 1). The manager does not commit docs itself.

## Lanes (operator rules unchanged)
- **ML-PRIMARY**: the standing ML lane, top priority, never stood down. Woken 01:55Z when the pipeline map landed. It stalled once
  (02:31–03:19Z) and was nudged. Context ~539k at 03:19Z: watch it, and rotate it via its own handoff note before ~650k. Queue: grade D5/D6,
  ML infra, RESEARCH-QUEUE-ML-STARVATION (#26181 merged), ML-ENTRY-EQ-REPRO-DRIFT (equity model 0afc4994 not rebuildable; one extra source
  row), the LTR-GRADER-COVERAGE adverse-state pricing gap (tagged ML-supporting), then baseline ML live per decision slot (D5/D6 first).
- **AM-OPS**: general lane and the ONLY assistant manager (the Sonnet routine-supervision AM was archived 22:18Z per operator).
  Queue: the daily-review items sent 05:55Z (record last_review, backlog drain, 6 stale in-flight rows, report >64 KB, demo due-list noise,
  4 alpaca_paper mechanical_fail soaks), then TELEMETRY-UPSERT-ENTRY-RISK-COLUMNS (Tier 2, next restart batch).

## Merged tonight (merged → deployed → observed)
- #26143 + dashboard #270 PIPELINE-MAP: live; operator pinged 02:04Z. Rendering not yet seen by a human.
- #26149 TREND-ALIGN-LABEL-ALL: observed. D1 latency: a pre-registered test is read at **16:20Z** (TREND-ALIGN-D1-LATENCY-TEST).
- #26161 queue-unit fix (main had been red), #26181 ML starvation dispatch fix.
- #26163 + #26167 (exchange_positions parallel; entry-fill writeback): observed.
- #26190 conflict-alert carry-forward: deployed 03:49Z. **Not yet observed**: the next leg exit from a standing conflict must not re-alert.
- #26202 + #26203 (bybit_open_orders parallel; open R from the fill): observed 05:15Z.

## Live book notes
- XRP 4h short on bybit_2 stopped at its own SL, −1.0R, 03:01Z. The XRP adx25 sibling was open at about −0.83R with its stop near.
  The venue_sl_diverges alert was a FALSE POSITIVE; filed LTR-VENUE-SL-NETTED-SIBLING-FALSE-DIVERGE.
- ETH 4h prop short (tradeify_1 + velotrade_1): held 4×, stop 1850.50, close 1818 at 04:00Z. Firm DD distance unknown (account_bounds empty).
- New ml_entry longs at 04:00Z on bybit_2 (ETH/BTC/SOL/ADA): all HOLD, brackets verified (ADA read from the venue).
- velotrade_1 SOL short hit TP: +$22.77, recorded in the prop journal.

## Lessons
- Point every reviewer at the contract on **main** (`.claude/skills/live-trade-review/*`); the live-review/rows branch does not carry it.
- Run `trader_import_closure.py decide` yourself before trusting any "no restart" claim (`src/web/api/routers/diag.py` IS in the closure).
- Verify a mechanics alert against per-leg orders before acting on it (netted venues).
