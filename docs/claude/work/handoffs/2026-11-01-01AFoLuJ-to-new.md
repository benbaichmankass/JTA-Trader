# Manager handoff — Manager Session 2026-10-31a → next

> **Doc status:** `unknown` · category `handoff` · last verified `2026-11-01` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

Old manager: `session_01AFoLuJwBvR58WBtD4qc5Gp` (Manager Session 2026-10-31a, Opus, lineage depth 6/8, ~520k tokens at 2026-11-01T06:30Z).
Assistant manager (shallow, creates the new manager): `session_011c3qoaBvGBioDWkPVToQSb`.
Written 2026-11-01 ~06:35Z. Weekend mode is ON until Mon 2026-11-02 13:30Z.

## 1. Live lanes (at writing)

| Lane | Session | Row | Doing | Owes |
|---|---|---|---|---|
| CF-B1-BULK-BACKTEST | session_01AFoLuKZduX4XRZ5pFQ1HBE | CF-B1-BULK-BACKTEST | full counterfactual run `cfb-20261101` on GitHub runners (tooling #22026 merged) | read the run result, update the row, report; archive when done |
| Daily research authoring (assistant routine) | (assistant's lane) | — | PR #22046 (18 units RQ-20261101-e5b1-01..18), held for manager merge | wakes manager when CI green → merge #22046 |

No other lanes running. Everything else from 10-31/11-01 is archived.

## 2. PRs needing the manager

- **#22046** research authoring (hand-authored units; manager merge when CI green; it will wake you).
- **#21876** WEEKEND-TRIGGER-ONLY revert (draft): **merge Mon 2026-11-02 13:25-13:30Z** after re-checking CI green + mergeable; restores `judgement_cadence.hours_by_timeframe` {30m:4,1h:4,2h:4,4h:4,1d:4} and `scan_wake_every_h: 2`. Then close row WEEKEND-TRIGGER-ONLY. A send_later reminder exists on the OLD session (`trig_01VM3CGFfV5ErNSk3yhzK1Mz`) — recreate it on the new session.
- **#17895** ops-flags (never merge; subscribe).

## 3. Operator decisions this session (verbatim; all recorded in rows/pipeline)

- eth_prop (2026-10-31 morning): "Keep, and get more evidence"; then after RQ-20261031-422a-01 FAILED: **"2 until we have a replacement"** = keep trend_donchian_eth_prop on prop until a replacement passes → PI-20261031-TD4QC5GP-0005.
- V3 prop gate: "Merge V3 (Recommended)" (#21851, done).
- Weekend switch: "Yes, until Mon 13:30Z (Recommended)"; permanent trigger-first design: "Yes, build it (Recommended)" (#21883 merged).
- Trail fix Tier 3 #21898: "Yes, merge #21898 (Recommended)" — merged 29ecbc22; Tier-2 #21897 merged 2603e963. Row TRAIL-RATCHET-AUDIT landed_unproven, observation due 2026-11-07 (a 'held at its sl_floor' log line or a strategy_close from a trail cross).
- 2026-10-31 ~21:05Z: **"We need to keep research work running as well, not just builds"** → refill routine `trig_01FtjWbWTCt3JBiZv9weKxa8` prompt now keeps ONE research lane running outside the build-lane count (dispatch when none running and none landed in ~6h; ask operator only at >= 85% weekly).

## 4. Open threads / where things were left

- **sol_4h prop replacement**: RQ-20261031-a4e7-04 PASSED (1 of 4 candidates, ci_lo +0.011R; trailing-365d n=34 negative median). Confirmation unit **RQ-20261101-2df8-01** (disjoint 2020-10..2023-10, same V3 rule) merged #22025. On PASS → bring ONE Tier-3 swap PR (pull eth_prop, add sol_4h, mirror rules) to the operator as a popup. On FAIL → keep eth_prop. 7 more prop candidates in #22046 (a4e7 twins + ada_4h, avax_4h, sol_pullback_2h, eth_pullback_2h).
- **VOL-WINDOW-RESEARCH** (operator ask 10-31): stage A FAILED (0/8128 shortlisted; windows real but untradeable net of cost at 15-60m); A2 longer-hold unit RQ-20261031-a4e7-15 queued.
- **PI-20261031-TD4QC5GP-0004** resolved: venue/journal bracket "mismatch" was a live-review READER false positive (#21991 matches Bybit legs by order id; bybit_1 is position_model slices). Deployed-not-observed.
- **PI-20261101-TD4QC5GP-0001** (low): attention_watch `live_review_due_stale` counts the KILLED row LR-20261031T1529Z (killed_rows.json, #21933) as "mirror stuck".
- **PI-20261031-TD4QC5GP-0002** (E4 bars_held stuck at 0), **-0003** (ltr-wake marker lists only primary account) — queued.
- ML-LINE-S1-CORPUS merged #21966 (weekly corpus producer, weight 1); coverage station metric unmeasured until first runs. CF-C1-HARNESS-HOOK merged #22003 (observation due 2026-11-08).
- E4 XRP short pkg-a819d2ab2f254b74 on bybit_1 was open at -0.77R (16:31Z hold, p_target 0.12); no events since.
- Lesson (keep): never point a lane at a manager register branch; land the register PR first. Lanes' trailers must carry their OWN session id (manager-scope-guard; #21960 → #21966).
- Reviewer prompts: "packet_sha = canonical JSON sha (sort_keys, compact), full 64 hex".

## 5. Capacity

Weekly 55% at 2026-10-31T22:52Z (reset Wed 2026-11-04 18:00Z); spend_meter --capacity → KEEP 1 build lane + the research lane. App warned "run out Tuesday afternoon" at weekday pace. Ask the operator for a fresh reading Monday morning before the cadence restore.

## 6. Triggers targeting the OLD session — recreate on the new one, disable old (delete at step 5)

Recurring (by name; ids from list_triggers):
- trig_018P5sM5mA3UB4NBpfRggByb — Manager lane check-in (every 3h) `17 */3 * * *` — **NEVER DROP**
- trig_01FtjWbWTCt3JBiZv9weKxa8 — Manager hourly refill `28 */3 * * *` (prompt includes the RESEARCH LANE rule)
- trig_01CieayPRLsudMPnSPaLnTay — Manager review `52 5,17 * * *`
- trig_01Fo8Xe85fZ5USkNw8L7Ai8u — Thursday planning
- trig_01JcTvvZkHyeoEVtyomTBGMD — Weekly audit
- trig_01WUeBdxafWHoZTR3kBreS4p — Weekly review prep
- trig_01A38BSjYhr99BUJ6LoEFsuq — Programme review
- trig_01VrjkMNzRC2Z7Kds3DKn69N — CJ-7 grading
One-shot: trig_01VM3CGFfV5ErNSk3yhzK1Mz — Mon 2026-11-02 13:25Z #21876 re-check + merge.
Many fired one-shot lane-report triggers (no cron) also bind to the old id; they never fire again — disable them, no recreate.

Before archiving: run `python3 scripts/ops/routine_prompt_check.py <list_triggers JSON, all pages>` and repoint any enabled routine naming the old id.

## 7. New manager's first actions

1. V1 short diff (list_sessions mine=true limit 10, list_triggers enabled=true, get_session depth) against §1/§6.
2. subscribe_pr_activity on ops-flags #17895.
3. Merge #22046 when green; let CF-B1 finish.
4. Mon 13:25Z: #21876.

## 8. Handover checklist

- [ ] handoff doc merged (PR #__)
- [ ] new session created by the assistant (shallow), Opus, tags `manager` + `predecessor:session_01AFoLuJwBvR58WBtD4qc5Gp`, depth __/8
- [ ] triggers recreated (n = 9 of 9), old disabled
- [ ] prompts and checklist refs updated
- [ ] new manager subscribed incl. ops-flags
- [ ] V1 diff · V2 audit (0 on old id, incl. check-in `17 */3 * * *`) · V3 sweep with positive control · V4 round-trips · V5 operator told
- [ ] STAND DOWN (old manager's last message links https://claude.ai/code/<new id>)
