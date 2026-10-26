# Manager handoff 2026-10-26 (session_01HAysMLfF9dYpi92YMqYxEq -> new)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Reason: context 636k at 18:29Z (threshold ~650k, operator 2026-10-24). Old manager stays responsible until V1-V5 pass.

## Live lanes (session, row, doing, owes)
- CJ-3 `session_01FPWQvqvHnMBxAaa7w7Zyw1` | CJ-3-BLIND-GRADE-PILOT | blind-then-reveal grades, 50-trade pilot (Opus, $8) | draft PR #20390 (guards red at 18:18Z, lane mid-work). Owes the measured cost per grade, the backfill projection and the weekly cap proposal, which go to the operator as a popup.
- DESK-18 `session_014Wuw5ZTBbMDhhYNnn9wGJx` | DESK-18-GEN-REPLAY-S0 | entry-generation replay units vs random-entry and strategy baselines (Sonnet, $30) | owes a held units PR (manager merges) plus a tooling self-land PR.
- CLAUDE-GRADE-LOOP `session_01Nbc9c8aLjvDKHhc3ShDThA` | CLAUDE-GRADE-LOOP | grade Claude's LTR and desk calls vs the system; desk section in /performance-review; calibration; lessons into briefs; use rules (Opus, $15) | PR #20386. Owes the PROPOSED mandate and ML-weighting rules. These are operator popups: a session never grants a mandate.
- DESK-WAKE-VM `session_015CN5DWiRyr8w2y1TSR5ALz` | DESK-6B-VM-WAKE | PR #20377, Tier 2. The VM builds, lands and posts the desk-wake per packet. Reviewed and marked ready by the old manager; guards green, pytest pending at 18:29Z. MERGE WHEN GREEN.
- LTR-MECHANICS-VENUE-SNAPSHOT `session_01JA1tezUEqwFYzMVXkmouTK` | LTR-MECHANICS-VENUE-SNAPSHOT | venue SL/TP snapshot so the due check fires venue_sl_diverges | Tier-2 hold; the manager merges.
- SIZING-6731 `session_01JXx5RS4bLWGxuB9ay71uwh` | pipeline PI-20261026-C1PVMNFJ-0002 | root-cause the bybit_1 trade 6731 11.95->4.41 clamp and check the real-money sizer | any fix is Tier 3: bring it to the operator as an exact proposal.

## Open PRs needing the manager
- #20377: merge when green. Then read diag log_file `desk_wake_post_receipt` (expect `posted`; `could_not_commit` means the VM credential cannot write desk/decisions; `could_not_build` names a cause). When the first marker-started wake writes its DD row: ping the operator (operator ask, verbatim: "ping me when the desk VM trigger is live"), then delete the bridge `trig_01K3T82FnBBSfpnird93qnw6` and the disabled `trig_01NMCJ5LHARkp6vWgTmQ8BC9`.
- #20369: a stale automation research-slo PR (dirty, no checks). The research watchdog reads could_not_look on it. The old manager's close was refused by the classifier; the operator was told to close it.
- Held PRs from the lanes above, as they arrive.

## Operator asks and decisions in flight (verbatim)
- "ping me when the desk VM trigger is live"
- LTR: "ping me ... for each proven stage in the entire stack". src/runtime/ltr_first_proof.py pings S1 and S3-S7 automatically. S2 (call) is proven (review LR-20261026T1328Z-pkg-465a5d7d27644027). Still unproven: a reviewer spawned ON live-review/rows writing its row; the first real due wake proves it.
- Desk design: "the system landing the packet to be what triggers the session ... the session shouldn't be starting before the packet lands" (in #20377). "crypto 24/7: wakes every hour; centralized through the system, not a Claude routine."
- Claude-grading ask (~17:35Z): grade Claude's calls vs what the system would have done, in the performance review, and feed the lessons into how Claude decisions are used, how the MLs weight them, and training. That is lane CLAUDE-GRADE-LOOP.
- Operator: "as long as we have headroom, lanes should be running" (the hourly refill).

## Triggers targeting the old session (recreate on the new one, then disable the old)
Recurring (7):
- trig_01R37NmiiLVpxNDTemZ33JRY "Manager hourly refill" `28 * * * *`
- trig_01K3T82FnBBSfpnird93qnw6 "Desk wake bridge" `39 * * * *` (temporary; retire after #20377 is proven)
- trig_01EsHLNNWVoaq5821fZMpCtG "Manager lane check-in (every 3h)" `17 */3 * * *`
- trig_018AbjkAZei77za9KfADXsq2 "Manager review (twice daily)" `52 5,17 * * *`
- trig_01UYmnGdz5t7EFJW1Ago2obo "Weekly audit (Wed after reset)" `31 18 * * 3`
- trig_01XUcgYDpdYdc5bekm3DeAEa "Weekly research programme review" `29 19 * * 3`
- trig_019yt496YJPZz3N6kuwYFhWx "Thursday review walk-through + weekly planning" `17 6 * * 4`
One-shot: trig_017Vtn5C22wukPVvQBybP5VE "#20255 readback observation" at 2026-10-26T21:05Z.
Assistant-manager routines whose prompts name the old id (update them): trig_01PHFNiKyeRUMLJj1DgYzmuy (daily research authoring), trig_01Bchsugftspk4uZhHR1ncK8 (LTR hourly), trig_013GU17584wu4HJYEkTF1KBk (health review), trig_01LE61kLKDFKptEfTfZ7vnYS (review prep), trig_01UnRpzN513KbMjvJWFAf911 (research-ops), trig_01HxRVXSy6GGqWaWQXmGdJ97 (assistant lane check-in). Assistant manager: session_011c3qoaBvGBioDWkPVToQSb.

## Watched PRs and subscriptions
- ops-flags #17895 (must move to the new session)
- #20377

## Capacity
- Operator reading 2026-10-26 18:29Z: weekly 56%, session 10%, reset Wed 2026-10-28 17:59Z. NOT yet recorded with spend_meter.py --record: record it first.
- 50% -> 56% over 13:27-18:29Z with ~6 lanes is about 0.2 pp per lane-hour (INFERRED). There is headroom for ~5-6 lanes.

## State at handover (MEASURED)
- LTR stack merged and deployed on the VM (#20298 ... #20357).
- CI fix merged (#20373, #20374); the 4,653-test subset now runs in ~12 min, down from ~18 (n=3).
- Desk: 3 no_trade decisions (13:39, 16:31, 17:43).
- desk-scan-packet cron never fired on schedule; the bridge dispatches it by hand.
- Disk: the scratchpad filled once; worktrees cleared.

## New manager first actions
1. V1 short diff.
2. Merge #20377 when green; verify the receipt; ping the operator.
3. Record the capacity reading.
4. Keep the hourly refill going.
5. Watch for #20390, #20386 and the LTR-MECHANICS and DESK-18 PRs.

## Handover checklist
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager): <id>, Opus, tags manager + predecessor:session_01HAysMLfF9dYpi92YMqYxEq; depth __/8
- [ ] Triggers recreated on the new session; old ones disabled (n recreated = __, pre-handover n = 7 recurring + 1 one-shot)
- [ ] Prompts naming the old id updated; checklist references updated and pushed
- [ ] New manager subscribed to ops-flags #17895 and #20377
- [ ] V1 read-back diffed; mismatches fixed
- [ ] V2 trigger audit: 0 enabled triggers on the old id; recurring routines present on the new id, incl. "Manager lane check-in" (17 */3 * * *)
- [ ] V3 id sweep (with a positive control)
- [ ] V4 wake round-trips: old->new, assistant->new, one lane ack
- [ ] V5 operator told in one message
- [ ] STAND DOWN
