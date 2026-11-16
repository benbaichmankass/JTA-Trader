# Cross-model learning MAP, 2026-11-16 (lane CROSS-MODEL-LEARNING, Tier 1)

Operator question 2026-11-16: do our models learn from each other's performance where it is relevant, above all the ML entry model learning
from the LTR (live trade review) desk, without feeding models data that does not improve decisions?

**Short answer (MEASURED in code, `map.json` has every citation).** No model's training reads another layer's outcomes or LTR output today.
Every decision model trains on bars (kline triple-barrier labels) or on closed-trade P&L. The only cross-layer reads are **entry -> in-trade**
(the TP-revision head re-scores the entry recipe's own first-passage target) and **LTR -> data store** (the claude_judgments family can read LTR
rows, but no manifest trains on it). The one built LTR -> model pipe is stalled for a process reason, not a technical one (section 2).

Provenance: MEASURED = counted from a committed file on `main` at ae5f43427 (or the cited branch) by a command in `map.json.commands`;
ESTIMATED = derived or quoted, labelled; CODE = read from the cited file:line.

## 1. The map: what each layer trains on, and what it consumes from other layers

| Layer (breed) | Trains / labels on | Consumes from another layer's outputs or outcomes | Does NOT consume |
|---|---|---|---|
| **ml_entry** (Foxhound-1/2) | kline triple-barrier brackets (SL 2 / TP 3 ATR, 24 h, decision every 4 h) over the 60-perp universe, 20 decision-time features: `scripts/research/ml_decision_entry.py:59-61,267`, retrain `scripts/research/ml_entry_retrain.py` | none | live trades, LTR reviews/outcomes, claude_judgments, regime/overlay outputs (grep of `ml_entry_retrain.py`, `ml_entry.py`, `ml_decision_features.py:19` finds no `live_review`, `outcomes.jsonl`, `claude_judgments`) |
| **TP-revision re-score** (Labrador-1b) | the same bar-level first-passage labels as ml_entry | the **entry recipe's** own features/target, re-scored at each 4 h check-in: `src/units/strategies/ml_entry.py:226 monitor`, `:362 tp_revision`, `src/runtime/tp_revision.py:146 plan_tp_revision` | LTR calls (the LTR packet only RESPECTS the rule: `scripts/ops/live_review_packet.py:808-847`) |
| **Beagle-1 overlay** (D4 meta-label) | TD-family backtest trades, committed artifact `ml/overlay/overlay_td.json`, rule RULE-ML-OVERLAY-NONINFERIOR-V2 | nothing at serve time beyond the leg's own entry features; demotion by `scripts/ops/overlay_cusum.py` on mirror trades (outcome -> alarm, not -> training) | LTR, entry score (`config/overlay_policy.yaml:1-25`) |
| **Regime heads** (Collie, `ml/configs/*regime*.yaml`) | `market_features` bars | none. The D2 gate was tested as a consumer of regime and FAILED (RQ-20261112-bcd2-01: dropped 91/195 SOL trades, -11.69 R, p 0.815; `scripts/ops/run_training_cycle.sh` comment block ~line 165) | entry outcomes, LTR |
| **Conviction-meta** (Mastiff) | `conviction_meta` family: one row per closed, filled, non-backtest order package, label from realised P&L: `ml/datasets/families/conviction_meta.py:1-22`, `ml/configs/conviction-meta-v1.yaml:67` | **realised closed-trade outcomes** (journal `trades` JOIN `order_packages`): the one layer that learns from live results | LTR reviews, LTR counterfactuals, bracket moves |
| **Exit-policy** (Labrador-1) | `exit_candidates`: one row per in-trade bar, synthetic or real trades: `ml/datasets/families/exit_candidates.py:1-22`, `ml/configs/exit-policy-v1.yaml:101` (ETHUSDT 5m only) | its own in-trade state | LTR close/tighten outcomes |
| **Setup metalabel** (Beagle research) | `setup_candidates`: CUSUM events from bars + triple-barrier labels, thousands of hypothetical rows: `ml/datasets/families/setup_candidates.py:1-22`, `ml/configs/setup-candidates-metalabel-p2pool-v2.yaml:76` | none (synthetic by design; exists because ~80 real trades collapse the model) | live outcomes, LTR |
| **LTR reviewer** (Claude, procedure `live-trade-review`) | not a trained model. Decides on a 7-key in-trade state (`open_r, peak_r, giveback_r, atr_now_over_entry, bars_since_peak, r_to_stop, r_to_target`; MEASURED over all 784 `reviews.jsonl` rows) + option pricing from the leg's own Stage-0 history (`scripts/research/live_review_outcomes.py`) | **the leg's backtest history** (priced options). It sees the prior row's `forecast` (`live_review_packet.py:1163-1173`) but `features_at_review` carries no ML score or entry-model output (MEASURED, 784/784 rows have only those 7 keys) | ml_entry's score at entry, regime/overlay heads, conviction |
| **claude_judgments student chain** (CJ-2/3/4/5, DESK-11/19) | the family joins Claude's calls (LTR 784, desk 218, blind 707, revealed 707) to realised net R: `ml/datasets/families/claude_judgments.py:1-60,616-700` | LTR + desk + blind/revealed grades **as labels** | every decision model. **No manifest in `ml/configs/` targets the family** (the only reference is `baseline-post-trade-review.yaml.disabled:2`, "Do not re-enable") |

### Row counts, with populations

| Store | Rows | Population / note | Provenance |
|---|---|---|---|
| `comms/live_review/reviews.jsonl` | 784 | legacy file; 36 distinct non-null `trade_id` (most rows key on `order_package_id`); `applied: false` on all 784 (applied state lives in outcomes). `comms/live_review/rows/` absent on main, 39 more rows sit only on the rows branch (LTR-CLOSE-AUDIT) | MEASURED |
| recommendation mix | hold 584, flag_mechanics 73, no_recommendation 59, close 41, tighten_sl 25, partial_close 2 | all 784 | MEASURED |
| `comms/live_review/outcomes.jsonl` | 668 | 148 distinct trade ids; `cf_method`: no_path_change 630, paired_replay_v1:close 27, replay_v1:stop_first+trail 10, paired_replay_v1:partial_close 1; `applied: true` 5 | MEASURED |
| `comms/claude_judgments/blind_grades.jsonl` | 707 | 707 distinct trades, 1 model (claude-sonnet-5-5), 16 run ids, 14 distinct `prompt_sha`, `pre_cutoff` null on all 707, decision_ts 2026-07-01..2026-11-11 | MEASURED |
| `revealed_grades.jsonl` | 707 | 707 distinct trades (T1, saw the outcome: label-only) | MEASURED |
| blind trades with a committed net R | 51 of 707 | join to `outcomes.jsonl` by trade id; the other 656 need the VM/trainer journal | MEASURED |
| `comms/desk/decisions.jsonl` / `outcomes.jsonl` | 218 / 217 | desk entry-generation rows; 17 emit to the dataset | MEASURED |
| claude_judgments population report (local run, journal ABSENT) | 2416 read, 650 emitted (ltr_review 633, desk_entry_generation 17), 1766 excluded (outcome_unjoined_no_journal 1454, outcome_not_computable 197, no_trade_id 104, t1_outcome_visible 7, never_train 3, outcome_pending 1); **blind_grade emitted 0** | `python3 -m ml.datasets.families.claude_judgments`; the 0 is "could not look" (no journal), NOT evidence about the trainer | MEASURED (local) |
| `scripts/ops/ml_learning_ledger.py` | desk H1 30 / H2 6 / H3 0; live_review H1 189 / H2 180 / H3 `could_not_look` (no consumed-ids ledger exists) | window default; claude_judgments H4 0 manifests; blind_grade is not a ledger source at all | MEASURED |
| LTR realised closes with a priced counterfactual | 13 packages in the 2026-11-05..16 audit (11 priced); 8 real-money rows delta -0.15 R, mixed: resolved holds +1.08 R, still-open -1.22 R (ESTIMATED marks) | `lane/ltr-close-audit-20261116` VERDICT.md | MEASURED / ESTIMATED as labelled there |

## 2. The stalled distillation chain (CJ-3 -> CJ-4 -> CJ-5 / DESK-19)

States now: CJ-2-DATASET `landed_unproven`, CJ-3-BLIND-GRADE-PILOT `landed_unproven`, CJ-7 `landed_unproven` (blocked on CJ-3), CJ-4 `queued`
(blocked_on CJ-3), CJ-5 `queued` (blocked_on CJ-4), DESK-19 `blocked` (CJ-4 + DESK-11), DESK-11 `blocked` (DESK-0-SCHEMA is `done`, CJ-2 is
`landed_unproven`). So **three upstream rows wait on one observation and nobody has read it.**

**Observation that closes CJ-3 (and CJ-2):** a trainer cycle's `claude_judgments` population line, printed by the builder
(`ml/datasets/families/claude_judgments.py:750`, run from `scripts/ops/build_trainer_datasets.sh:481` with the synced journal), showing
`emitted_by_kind.blind_grade > 0`, with `journal` not `absent`. The expected value is about 707 minus T1 refusals, because the journal holds the closed trades. Read it from the trainer
journalctl via the trainer-vm-diag relay. **Not read by this lane**: no trainer log is committed and the local run has no journal.

**Is CJ-4 runnable now? On data yes, as a job no.** Its stated trigger ("runs at n >= 150") is met: 707 distinct blind-graded trades (MEASURED), 4.7x the bar. Its
"blocked on CJ-3" is a *process* dependency: the validation reads `blind_grades.jsonl` plus journal net R, not the trainer dataset. What is missing is an instrument: no script
computes the section 3.3 statistic, and it must run where the journal is (locally only 51 of 707 trades join to a committed net R). The unit is authored as
`research/queue/blocked/RQ-20261116-089f-01` with the instrument filed as row `CML-HARNESS`.

Two defects the unit registers around (both MEASURED, both would have made CJ-4 unreadable):
1. **Source key vs n.** Design 3.3 defines a source as (author_kind, model_id, prompt_sha, rubric). The 707 rows carry 14 `prompt_sha`: 13 single-shard backfill batches of 47-48 and one of 128. Read literally, no source can ever reach n >= 150, so CJ-4 would return INDETERMINATE by construction. The unit pools within (author_kind, model_id, mask_version) and reports per-sha strata (declared deviation, registered before any run).
2. **`pre_cutoff` is null on all 707 rows**, so the design's leakage exclusion never fired. The unit applies one declared date rule and states how many rows it excludes.

Prior for CJ-4: the n=50 pilot read blind expected_r vs net R Spearman -0.12 [-0.38, +0.17]. An honest expectation is a FAIL or INDETERMINATE, which design section 8 treats as a cheap, correct stop.

## 3. What is worth feeding, and what is not

**Worth testing (units authored, all `blocked/` with a named instrument; none run):**
- `RQ-20261116-089f-01` CJ-4 blind-source validation (the teacher -> student gate; n 707; MDE about 0.11 Spearman).
- `RQ-20261116-089f-02` LTR -> entry **selection**: refit ml_entry on the net R it would *realise under management* instead of hold-to-bracket R; pre-registered and waiting on a codified management policy M (LTR-CLOSE-AUDIT units `RQ-20261116-7c1a-01/-02`) that shows a hold gap of at least 0.05 R, otherwise both targets are the same label and the test is worth about 0.
- `RQ-20261116-089f-03` LTR -> entry **structure**: is the best bracket state-dependent (side x ATR tercile) given 4654-03's 4/8 fold split? Everything else on the structure side already exists and FAILED: global bracket (4654-03), wider-TP/grid (b601-01 produced no verdict), dynamic SL (c692-08..14), MANAGE (c692-03), reverse-close (0be0-01, FAIL: -0.0070 R/trade, CI excludes 0 on the wrong side, n 10641). Linked, not duplicated.

**Judged NOT worth feeding (the "no spam" half), with the reason:**
1. **LTR `hold` rows as training rows.** 584 of 784 reviews are hold, and 630 of 668 priced outcomes are `no_path_change` (delta 0 by construction): the row says "nothing happened". Only the 38 priced non-hold actions carry information, far below any usable n (an IC at 150 distinct trades is the repo's coarsest bar).
2. **LTR realised closes as entry training rows or a selection test.** 13 packages / 11 priced (audit), 148 distinct trades with any priced counterfactual. The managed-target unit uses replay (13 monthly refits) because the realised record cannot power the test. Revisit when priced non-hold deltas reach 150 distinct trades.
3. **Claude output (grade, expected_r, review text) as a LIVE entry feature.** Operator Q2 (2026-10-25): teacher use first, live feature only after a model proves net-R edge out of sample. CJ-4 is that first proof and has not run.
4. **Revealed (T1) grades as features.** They saw the outcome; in-sample they always correlate. Control only (design 3.3).
5. **Regime-head outputs into entry or LTR.** The one consumer test (D2 gate, bcd2-01) FAILED; regime heads now train every 3rd day by decision.
6. **ML re-score as an in-trade MANAGE signal for LTR.** c692-03, c692-13/-14 and 0be0-01 all read a FAIL (delta vs hold <= 0 or CI not clearing 0) at their registered rules.
7. **Paper/mirror book P&L as an edge signal for any model.** A live or paper book never establishes edge (CLAUDE.md, promotion ladder).
8. **Prop-account closes.** Not in the journal `trades` table, so no realised R (LTR-CLOSE-AUDIT: `could_not_look`).
9. **Entry model score into Beagle-1 or conviction-meta.** Beagle ranks on its own leg features and was validated non-inferior without it; conviction-meta already learns from realised outcomes. No test hypothesis names a gain, so authoring one is value ~0.

## 4. Gaps filed or flagged
- Row `CML-HARNESS` (queued): the three instruments. A finding is filed only when it is a row, so it is one.
- `ml_learning_ledger.py` lists no `blind_grade` source and has no consumed-ids ledger (H3 `could_not_look`): the learning ledger cannot show whether any label was ever consumed. Not fixed here (Tier 1 tooling, separate row if the manager wants it).
- Report to the manager (not done by this lane): CJ-2 and CJ-3 both close on the one trainer read; CJ-4 is data-runnable (see section 2).
