---
name: drift-remediation
description: The standing process for FIXING a drifted / degrading ML model instead of reflexively demoting it. Use when the daily promotion-readiness report proposes a DEMOTE for a live (advisory) model, when shadow-drift or gate-check flags drift, or when the operator asks "how do we fix this model / get it back to where it needs to be" rather than just turning it off. Distinguishes transient drift (self-corrects on the daily retrain → no action) from persistent capability failure (needs a feature/label fix shipped as a new version → the validated replacement is promoted on its offline evidence, no shadow step). Demote is interim safety only, never the endpoint; a demoted head soaks in shadow to keep generating data while it is iterated on. Composes with model-training, ml-review, diag-data. NOT for routine training (model-training).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-09-07` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /drift-remediation — fix a drifted model, don't just demote it

Full runbook: [`docs/runbooks/model-drift-remediation.md`](../../docs/runbooks/model-drift-remediation.md).
This skill is the invokable entry; the runbook carries the detail + the worked
example. **Promotion/demotion of a live head is Tier-3**, data-backed per canonical
§ "Data-backed Tier-2/3 decisions" when a committed evidence record settles it
(ship, then notify the operator). There is **no shadow step** before real money
(operator, chat 2026-11-12, verbatim: *"Everything goes through the new flow, back
testing, live money, and then if it gets demoted, it soaks to still generate data
while we iterate on it. That is the only acceptable flow. There is nothing in between
proving edge on back testing and real money. Absolutely no steps."*).

## The one rule

A demote proposal from the daily report is a **trigger to diagnose, not an
instruction to demote.** Trainable manifests are retrained daily, so drift often
self-heals; and a capability gap never heals from a retrain. So:

1. **Triage on the CURRENT gates, not yesterday's snapshot.**
   ```
   python -m ml gate-check <model_id>
   python -m ml shadow-drift --model-id <model_id>
   ```
   - Drift-only **and** `drift_clean` now PASSES (KS ≤ 0.2, PSI ≤ 0.25) →
     **transient, NO ACTION** (the daily retrain handled it; do not demote on the
     stale report snapshot).
   - A required capability gate stays FAILED (`live_regime_discrimination`,
     `non_degenerate`, `oos_edge`, `cross_run_stability`, `sample_sufficiency`) →
     **persistent → diagnose.**

2. **Diagnose the persistent failure** (usually `live_regime_discrimination`
   AUC ≈ 0.5): dataset audit for dead features / degenerate label
   (`manifest_audit_flagged` in `training_cycle.jsonl`) → the label base rate →
   regime-mix shift. (`oos_edge` needs `gate-check --datasets-root` run in the
   cycle/backgrounded — heavy, drops an inline relay.)

3. **Remediate as a NEW version** — data / feature / label fix trained under a
   new `model_id`, so the **live advisory artifact is never touched**; it lands
   `candidate`/`shadow`.

4. **Verify + promote** — the new version must clear the required OFFLINE gates
   (`gate-check <new_id> --datasets-root ...` → `ready: true`; live gates are reported,
   not required — there is no soak window); then `promote-stage <new_id> --new-stage
   advisory` under the data-backed Tier-3 rule (notify the operator), and retire the
   old one.

5. **Interim demote — only if the live head is actively harmful now and no
   replacement is ready.** `promote-stage <id> --new-stage shadow` is
   fail-permissive (reverts to the frozen label, strands nothing). A stopgap
   while the fix trains, never the endpoint. Still Tier-3.

## A replay or retrain grade says "negative" while the live book is positive (operator, 2026-11-08, binding)

Case that set it: the daily `ml_entry` grade replayed the served model at **-0.13 R net** (25 Oct–7 Nov, 48 symbols, both sides,
fixed 2/3 ATR bracket, n=317; longs -0.90 R, shorts +0.02 R) while bybit_2's live `ml_entry` record was positive (5 shorts, +$4.93).
Operator: *"we're not going to take it off because it failed the back test after its live record shows that it's doing well ... it's
not demotion, so what do we do with it? ... it should feed into iterating and improving."*

**Three different numbers, three different jobs. Never quote one as another; always name the population.**

| Number | What it measures | What it may decide |
|---|---|---|
| Retrain-candidate grade (`comms/research/ml_entry_grade/<run>`) | does a NEW candidate beat the served model on the same replay | only whether to SWAP models; a fail keeps the served model |
| Served-model replay on the recent window | the model's signal over the WHOLE table, both sides, the replay's exits | nothing by itself; it is a FLAG and a diagnosis input |
| The live book + its mirror, net of cost | what the account actually earns | the DEMOTION signal (OPERATING-PLAN § 2), never a replay |

**Protocol when the replay is negative and the live book is not:**

1. **Flag, don't act.** It goes in the brief under "what moved" with both numbers and their populations. No demotion, no roster change,
   no popup.
2. **Decompose the gap within a day** (one runner job, no session needed): re-cut the same replay by (a) side, (b) symbol, (c) the live
   book's own population (the symbols and sides the account actually trades), (d) the live exit (structure exit, not the fixed bracket),
   (e) time (is it the last days only?), and put the live record's CI next to it. Each cut gets a one-line verdict:
   *population* (the account trades a better slice), *exit* (the live exit rescues it), *side* (one side carries the loss),
   *decay* (it is getting worse everywhere), or *noise* (live n too small to say).
3. **Every confirmed driver becomes an iteration unit** in `research/queue/`, its rule registered before the run, feeding the NEXT
   candidate: e.g. a side lever (gate the losing side), a label lever (structure-exit labels), a population lever. The served model is
   untouched until a candidate PASSES its registered rule.
4. **Demotion only from the live mirror's net-of-cost window** (or active harm per step 5 above), never from the replay.
5. **Weekly:** the `/ml-review` reads the decomposition and the units it spawned, and grades whether the live book and the replay are
   converging or diverging.

## Report

Record the triage verdict (transient vs persistent), the diagnosed root cause,
and the remediation version + its gate status in the ml-review backlog. Never
silently demote or silently promote — both are Tier-3, data-backed on a committed
record, and the operator is notified at once.
