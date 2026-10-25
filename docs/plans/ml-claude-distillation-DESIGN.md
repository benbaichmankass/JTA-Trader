# Claude → ML: how Claude's judgments become training data (design, 2026-10-25)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**State: DESIGN ONLY.** Nothing below is built. No checklist row, queue unit or `ml/` change exists for it yet.
The operator reviews this first. § 7 lists the rows to file once it is approved.
Checklist row: `ML-CLAUDE-DISTILL-DESIGN` · roadmap `M25` · Tier 1 (a doc).

## 0. The request, and the short answer

Operator, 2026-10-25, verbatim (on the checklist row):

> *"Ok, I also just want to make sure that we have a clear and robust mechanism in place for using Claude's realtime analyses and decisions, as well as the post trade grading and reviews, to train our models that we're building, so that they also learn from Claude's wider context and broader knowledge - let me know how we plan to migrate Claude's outputs into the ml frameworks"*

**The short answer, in five lines:**

1. **Today nothing under `ml/` reads any Claude output.** That is MEASURED (§ 1.3). And most of what is labelled "Claude's grades" is not Claude's judgment. **4,127 of 4,347 rows (94.9%) are a deterministic Python rubric.** Only **220 rows** are LLM-written, and only **6** of those carry a P&L.
2. So the plan is not just to "pipe the existing file into training". Training a model on a Python rubric teaches it the rubric, which we can compute directly for free. **The plan first starts *recording* Claude's judgment in a form that can teach.** That means two new records. One is the live-trade-review rows (LTR-2), which exist before the outcome. The other is a **blind-then-reveal** post-trade grade: Claude grades a trade *before* it sees the outcome, then again after.
3. Those records go into **one dataset family, `claude_judgments`**. It is built point-in-time on the trainer from the jsonl stores plus the journal. Every label carries its author, model, prompt and rubric version, and a **judgment** provenance class that is never `MEASURED`.
4. **No label source trains a model until it passes a pre-registered validation:** does this source's judgment predict realized **net** R out of sample? If it does not, we do not distill it.
5. The first models are **teacher → student distillations** that run with no Claude in the loop. One is a cheap local head that imitates Claude's blind grade. The other is an exit "tighten" head learned from the LTR counterfactuals. Both enter the existing `candidate → shadow → advisory` ladder **unchanged**. They are promoted only on outcome evidence net of cost, never on agreement with Claude.

Population and commit for every number in this doc: `origin/main` at `05b4e72e`, read 2026-10-25, unless a row says otherwise.

---

## 1. Inventory: every Claude output that could teach a model

### 1.1 The table

"Author" says who actually produced the content. The `reviewer` field is not a reliable guide: it says `claude` on all 4,347 grade rows.

| # | Output | Where | Volume (MEASURED unless marked) | Author | Join key | Sees outcome? | Teaching value today |
|---|---|---|---|---|---|---|---|
| 1 | Per-order-package / per-trade grades, rubric rows | `comms/claude_strategy_scores.jsonl` | **4,127** rows. Their rationale is the rubric template (`…; entry=…; risk=…`). Sources: `health-review-retroactive` 2,304, `grade-closed-trades-*` 1,146, others | **`scripts/ops/score_order_packages.py::_grade_package`**, a deterministic Python rubric | `order_package_id`; `linked_trade_id` on 747 rows keyed per trade (JC-SA-01) | **yes**: `exit_quality` and `decision_grade` read realized R | **none as a Claude signal.** It is a function of fields we already hold (§ 1.2) |
| 2 | Per-order-package grades, LLM-written | same file | **220** rows: `performance-review*` 167, `system-review` 51, no source 2. Of these, 22 were executed and **6 carry `pnl`**. Written 2026-05-28 → 2026-10-10 | Claude in a review session, free text | `order_package_id` | mixed, unrecorded | **real but tiny.** Below every n floor in this repo (the label wall is n ≥ 300, ML-D2) |
| 3 | Per-trade grade log | `comms/claude_trade_scores.jsonl` | **0 rows** (one `_meta` line) | — | `trade_id` | — | none. **Superseded:** per-trade grading moved into #1 keyed on `linked_trade_id` (JC-SA-01, 2026-09-29). § 5 F1 |
| 4 | Daily stage-aware strategy reviews | `comms/strategy_reviews/<date>/INDEX.json` | 52 dated directories, 2026-09-01 → 2026-10-25 | **`scripts/ops/strategy_review_stage_aware.py`** (R4/R5 gates): a script | leg × date | yes | none as a Claude signal: these are measured gate outputs |
| 5 | `/perf-followup` records | `comms/perf_followup/*.json` | 3 records | Claude (Opus lane) | leg, queue-unit ids | yes | qualitative. Their outputs are already queue units and rows, which is the right channel. Not a training corpus |
| 6 | `/ml-review` and ML-plan loop records | `comms/reviews/ml-review-*.json`, `comms/ml-plan/*.json` | 5 + 4 | Claude | model id | yes | none for training. They are about models, not markets |
| 7 | Research readings (research-ops) | `comms/research/ops/*.json` | 45 records. 1,152 queue yamls, 1,260 result jsonls | research-ops applies **pre-registered rules** to measured results | `RQ-*` | yes | none. The verdict is mechanical by design. The *results* are measured data that `backtest_results` can already read |
| 8 | AI-analyst insights (M13) | `trade_journal.db::insights_history` on the live VM | **UNVERIFIED** (not read this session; query in § 7 row CJ-0) | `src/runtime/insights/generator.py`: Claude Haiku/Sonnet by default, **Gemini when `INSIGHTS_MODEL_MODE=gemini`** | strategy, window. `model_id` is stored per row | partly | low. These are window-level prose, not per-decision. They are only usable once `model_id` filters out non-Claude rows |
| 9 | **Live-trade-review rows (LTR-2)** | `comms/live_review/reviews.jsonl` (proposed) | **0: not built** (design `docs/plans/live-trade-review-DESIGN.md`, merged #20088, design only) | Claude, real time, on open trades | `order_package_id`, `trade_id`, `review_id` | **no: written while the trade is open** | **the highest of any source** once it accrues. § 2, § 4.4 |
| 10 | **LTR outcomes + counterfactuals (LTR-5)** | `comms/live_review/outcomes.jsonl` (proposed) | 0: not built | **computed** by replay on real candles, not by Claude | `review_id` | yes (this is the outcome) | high. It turns #9 into (action, realized vs counterfactual R) pairs |
| 11 | `/performance-review` and health-review narrative JSON | `comms/requests/REQ-*.json` (the `review_journal` family's source) | The `review_journal` family **materialised 0 rows**. Its manifest has been `.yaml.disabled` since 2026-05-19 | Claude | trade (when present) | yes | none: a dead path. § 5 F5 |

### 1.2 Why the rubric rows (#1) cannot teach "Claude's wider context"

The rubric reads `_grade_package` at `scripts/ops/score_order_packages.py:147`. Each of its fields is a fixed function of columns we already hold:

- **`entry_quality`** is a threshold on the *strategy's own* `confidence`: ≥ 0.7 `optimal`, ≥ 0.5 `acceptable`, ≥ 0.3 `late`, else `should_skip`. For vwap it is a threshold on `deviation_std`.
- **`risk_management`** thresholds `sl_distance / atr` at 0.5 and 3.0.
- **`exit_quality`** reads realized R: `tp_appropriate` if R ≥ 0.8, and so on.
- **`decision_grade`** is a hard-coded per-strategy baseline: vwap C capped at B, ict_scalp_5m B, everything else C. It is nudged by the three fields above.

So a model trained to predict this label learns `confidence` thresholds, a strategy-name prior written in May, and the outcome. There is no Claude knowledge in it.

**And the outcome-blind part carries ~no signal.** MEASURED over the 971 executed rubric rows whose rationale states a realized R and whose `entry_quality` is ranked: Spearman(`entry_quality` ordinal, gross R) = **+0.017**.

The rolled-up `decision_grade` does order the *mean*: A +5.25 R (n=11), B +1.13 (n=394), C +0.37 (n=984), D −0.05 (n=185). The *median* does not order: B −0.53 R, C 0.00. The mean ordering comes from `exit_quality`, which **is** the outcome (`tp_appropriate` mean +6.31 R, n=224). Population: 1,578 executed rubric rows with a parseable R, 1,573 distinct trades, all strategies and accounts pooled. R is **gross** price R from the rationale, **not** net of cost.

### 1.3 Nothing in `ml/` reads any of it

MEASURED: `grep -rn "claude_strategy_scores\|claude_trade_scores" ml/` returns nothing. The probe is not blind: the same grep over the repo finds the 5 real consumers (`src/runtime/insights/data_sources.py`, `src/web/api/routers/order_packages.py`, `scripts/ops/score_order_packages.py`, `scripts/ops/grade_closed_trades_from_diag.py`, `scripts/ci/check_grading_freshness.py`).

Two live docs claim otherwise, and both are wrong (§ 5 F2):

- `docs/ARCHITECTURE-CANONICAL.md` (§ training workflow, step 1) says these grades flow into `trade_outcomes` and `setup_labels` "as their primary label source".
- `docs/ml/training-center.md` (§ "Training session workflow", step 1) tells sessions to refresh `claude_trade_scores.jsonl` before training.

### 1.4 Quality and consistency findings (MEASURED, same population)

| finding | count | consequence |
|---|---|---|
| `reviewer: "claude"` on rubric-script rows | 4,127 of 4,347 | authorship is mislabelled. Any consumer would treat script output as Claude judgment |
| no rubric/prompt/model version on any row | 4,347 of 4,347 | a rubric change (e.g. the per-strategy baselines) cannot be separated from a change in the market |
| 5 different row shapes (`keyed_on`, `account_id`, `closed_at`, `account_class` appear in some rows only) | 5 shapes | the builder must normalise by shape |
| out-of-vocabulary `entry_quality` (`good` 25, `poor` 1), all from `system-review` | 26 | breaks an ordinal mapping |
| `order_package_id` graded more than once | 114 ids | needs a dedupe rule (latest, or per `keyed_on`) |
| `linked_trade_id` graded more than once | 6 trades | same |
| the rubric's strategy priors are fixed from 2026-05 ("vwap has no net edge", "ict_scalp_5m positive in-sample") | every vwap and ict_scalp row | the label encodes a stale opinion as a constant |

---

## 2. Uses, ranked by expected value

**"EV" here is a judgment (INFERRED). It weighs: does it bring information the models do not already have, is it available when the model must act, and what n can we reach.** The ranking is the build order in § 7.

| rank | use | source | EV | why | cost | precondition |
|---|---|---|---|---|---|---|
| **1** | **(e) Preference / counterfactual pairs → exit head** | LTR reviews (#9) + outcomes (#10) | **high** | The outcome is **computed** on real candles: realized R under the applied action vs replayed R under the untouched bracket. So the label is *measured*, and Claude is the exploration policy that chose which state to intervene in. This is exactly the "new information class" that `ML-S2` (the exit line) says it needs before it reopens. | low marginal: LTR-5 builds the replay. Here, a dataset view plus a manifest | LTR-2 carries § 4.4's fields. n ≥ the floor in § 3.4 |
| **2** | **(c) Teacher → student distillation** | blind grades (§ 4.3) and LTR verdicts (#9) | **high, conditional** | A cheap local model imitates Claude's judgment on every package and every bar, including those Claude never saw. It is free at inference, has no API in the order path, and lets parity be tested. Its value is capped by the teacher's: worthless if the teacher fails § 3.3. | Claude spend for teacher labels (§ 4.3 pilot measures it). Trainer CPU is negligible | the teacher source passes label validation (§ 3.3) |
| **3** | **(d) Evaluation set** | blind grades on a sealed slice | **medium** | Use it as a benchmark only: "does model X rank trades the way a context-rich reviewer does, *and* does that ranking predict net R?" It is never the promotion bar (§ 3.6). | small: a sealed split | it must be disjoint from every training set (§ 3.5) |
| **4** | **(a) Labels for supervised heads** (e.g. "should have tightened", process grade) | LLM post-trade grades, the *blind* half only | **medium-low** | A process grade is an opinion. It is worth training on only where it predicts the *next* trades' outcomes better than the outcome itself does. Otherwise just train on net R, which we already have. | as #2 | § 3.3 passes, *and* it beats an outcome-label control |
| **5** | **(b) Features at decision time** | an LTR verdict, or a live Claude assessment, as a model input | **low, high risk** | It exists only when the routine ran: sparse, cadence-dependent and non-stationary across model versions. It puts a paid external API in the decision path, and the parity harness cannot replay it. Rank 2 gets the same information into a model *without* those costs. | high: parity, availability, spend | only if a served path computes it for **every** scored row, and the operator wants that dependency (Q2) |

**Alternatives considered and rejected:**

- **Train directly on the existing 4,347 grades.** This teaches the rubric (§ 1.2). If we want rubric inputs as features, compute them; they are in `order_packages.signal_logic`.
- **Fine-tune an open LLM on Claude transcripts.** The volume is far too small (220 LLM rows). It is a GPU-class cost, and it creates a second LLM to version and parity-test. A tabular student over decision-time features is the proportional first step. Revisit only if § 3.3 passes and the tabular student plateaus. That would be a frontier-scan unit, not this build.
- **A live "Claude veto" on entries.** That is a new gate on the order path, and the Prime Directive bars a hidden third gate. It would also be a promotion of an unvalidated model past the ladder. Out of scope.

---

## 3. Guardrails

Each one is enforced in code (the builder, a manifest lint, or a CI guard) where it can be. The doc is the last line, never the only one.

### 3.1 No lookahead: the judgment's timing decides its role

Every row records **`judged_at`** and **`info_cutoff_at`**. The cutoff is the latest timestamp of any input the judge was shown: candles, fills, outcome.

| class | rule | may be |
|---|---|---|
| **T0: pre-outcome** (LTR reviews, blind grades) | `info_cutoff_at` < trade close | a **label** for a model whose features are all ≤ `info_cutoff_at`, or a teacher target. As a **feature**, only per § 2 rank 5 |
| **T1: post-outcome** (revealed grades, rubric rows, perf-review grades) | `info_cutoff_at` ≥ trade close | **a label only. Never a feature**, in any manifest, for any target |

The builder computes `outcome_visible = info_cutoff_at ≥ trades.closed_at` from the journal. It does not trust a declared flag.

### 3.2 Provenance: a judgment is its own class, never `MEASURED`

`src/runtime/provenance.py`'s four buckets (`MEASURED` / `ESTIMATED` / `FABRICATED` / `UNVERIFIED`) classify **measurements**: prices, fills, P&L. A Claude grade is not a measurement of anything; it is an opinion about one.

**Proposal:** a separate axis, `label_provenance ∈ {measured, computed, judgment}`, on every `claude_judgments` row.

- **`judgment`**: any LLM output, and the rubric too (it encodes opinions as constants).
- **`computed`**: e.g. an LTR counterfactual replay.
- **`measured`**: the joined realized P&L, classified by the existing `provenance.classify_pnl`.

A `judgment` value is never folded into a `measured` aggregate.

*Alternative:* add a fifth bucket `JUDGMENT` to `provenance.py`. Rejected. That module's buckets rank *trust in a number*, and a judgment is not a less-trusted number; it is a different kind of thing. Mixing the axes would let `split_counts` report Claude grades as "unverified P&L".

Every row also carries **`author_kind ∈ {llm, rubric_script, human}`**. For existing rows it is derived by rule: a templated rationale means `rubric_script`. A manifest must declare which `author_kind`s it trains on. The rubric is never silently mixed into a "Claude" label.

### 3.3 Validate every label source against outcomes before training on it

A source is the tuple (`author_kind`, `model_id`, `prompt_sha`, `rubric_id@version`). Each one passes a **pre-registered `research/queue/` unit** before any manifest may target it. The unit's rule is registered before the run:

- **T0 sources:** out-of-sample rank IC between the judgment (ordinal) and realized **net** R. Net means through `execution_costs.resolve_cost_policy()`, on trades the judge did not see in training. Pass = IC > 0 with the 95% CI excluding 0, at n ≥ 150 distinct trades. The n is a proposed default: it gives a ±0.16 CI half-width at IC≈0, which is the coarsest bar worth registering. The IC must **also** beat the strategy's own `confidence` on the same trades, or the source adds nothing.
- **T1 sources:** a grade that saw the outcome always correlates with that outcome, so the in-sample correlation proves nothing. The test is whether it predicts the ***next*** trades on the same leg and state bucket better than the realized R of the graded trade does. If it does not, the "process" in the grade is noise on top of the outcome, and we train on net R directly.
- **The verdict is stored with the source key.** A new prompt or model version is a new source that re-qualifies. Until it does, the trainer keeps using the last qualified version's rows.

### 3.4 Version every label

`label_version = "{author_kind}:{model_id}:{prompt_sha8}:{rubric_id}@{rubric_ver}"`. It goes into `DatasetMetadata.label_version`, which exists today and is `"n/a"` for raw families.

The rubric script gets a `RUBRIC_VERSION` constant, emitted on every row. Prompts for blind grades and LTR live in-repo, so `prompt_sha` is a git blob hash.

**Drift check:** `/ml-review` reports the label distribution per `label_version`. Any version change mid-dataset is a fold boundary in purged WF-CV, never pooled silently.

### 3.5 Leakage tests (in the builder and a guard, `claude-judgments-guard`)

1. **Timestamp test:** every feature column's as-of time ≤ the row's `info_cutoff_at` (T0) or ≤ `order_packages.created_at` (T1 labels).
2. **Manifest lint:** a manifest whose target comes from `claude_judgments` may not list any `claude_judgments` column as a feature. This includes sibling fields of the same judgment (`entry_quality` when the target is `decision_grade`), which the disabled `review_journal` manifest already documents as leakage.
3. **Rubric-reconstruction test:** fit a shallow tree from the rubric's own inputs (confidence, deviation_std, sl/atr, strategy, realized R) to the label. R² ≈ 1 means the "Claude" label is the rubric, and the build refuses it as `author_kind: llm`. This is how the 4,127 rows would have been caught.
4. **Disjointness:** train/eval split by time with the existing purge + embargo (`ml/promotion/oos_edge.py`). It is also disjoint by `trade_id` *and* by `order_package_id`, so a package that fans out to several accounts cannot straddle folds.
5. **LLM-memory leakage (new; specific to an LLM teacher):** Claude has seen market history up to its training cutoff. A "blind" grade of a 2026-05 BTC package may still be informed by remembered price action. So blind grading (§ 4.3) **masks** the symbol, the absolute dates and absolute prices: returns are normalised to ATR, and the regime is given as a cell, not a date. Rows whose decision time precedes the judge model's knowledge cutoff carry `pre_cutoff: true` and are excluded from the § 3.3 validation by default.

### 3.6 The promotion ladder is unchanged

- **No grading against the training labels:** a model distilled from Claude is never evaluated on agreement with Claude as its promotion metric. Agreement is a diagnostic. **The promotion evidence is the same as any head:** OOS edge over a baseline under purged WF-CV (`oos_edge.py`), then shadow, then the existing gates. All are on realized **net** R, with a committed evidence record and a rule registered before the run.
- The student enters at `candidate`, as every new manifest does. Shadow → advisory is the existing gate and, where Tier 3, the operator's.
- A Claude-taught model gets no shortcut and no new gate. The ladder decides; the teacher does not.

---

## 4. Pipeline: the exact mechanism

### 4.1 Overview

```
 producers (append-only jsonl, on main)            trainer (daily cycle, git-synced)
 ─────────────────────────────────────             ───────────────────────────────────────────
 comms/live_review/reviews.jsonl    (LTR-2, T0) ─┐
 comms/live_review/outcomes.jsonl   (LTR-5)     ─┤   ml/datasets/families/claude_judgments.py
 comms/claude_judgments/blind_grades.jsonl (T0) ─┼─► point-in-time join with trade_journal mirror
 comms/claude_judgments/revealed_grades.jsonl(T1)┤   (order_packages, trades, provenance.classify_pnl,
 comms/claude_strategy_scores.jsonl (T1, legacy) ┘    execution_costs net R) → versioned artifact
                                                         │
                                  label-validation unit (research/queue, § 3.3) ──► qualified sources list
                                                         │                          comms/claude_judgments/qualified.json
                                                         ▼
                              manifests (candidate) → oos_edge → shadow → existing gates
```

### 4.2 The `claude_judgments` dataset family

**Location:** `ml/datasets/families/claude_judgments.py`, registered in `ml/datasets/registry.py`. It is a normal `DatasetBuilder`, so it gets the existing metadata, versioning and `leakage_test_status`.

**One row per (judgment, subject).** Schema:

| column | type | notes |
|---|---|---|
| `judgment_id` | str | `review_id`, or `BG-<pkg>-<prompt_sha8>`, or the legacy `order_package_id#n` |
| `kind` | enum | `ltr_review`, `blind_grade`, `revealed_grade`, `legacy_score` |
| `timing` | enum | `T0`, `T1` (§ 3.1). **Computed**, not declared |
| `author_kind` | enum | `llm`, `rubric_script`, `human` |
| `model_id`, `prompt_sha`, `rubric_id`, `rubric_version`, `label_version` | str | § 3.4. `unknown` for legacy rows, and **that is a reason to exclude them, never to guess** |
| `judged_at`, `info_cutoff_at` | ts | |
| `pre_cutoff` | bool | decision time before the judge model's knowledge cutoff (§ 3.5.5) |
| `order_package_id`, `trade_id`, `leg`, `symbol`, `account_class`, `stage` | | join keys. `account_class` ∈ real/mirror/prop/paper |
| `decision_ts` | ts | `order_packages.created_at`: the as-of time for decision features |
| judgment fields | | `grade_score` (0–4), `entry_quality`, `risk_management`, `exit_quality` (T1 only), `action` and `level` (LTR), `ev_delta_r`, `confidence` (`measured`/`suggestive`/`anecdote`), `rationale` (bookkeeping only, never a feature) |
| outcome (joined) | | `gross_r`, `net_r` (full cost stack), `pnl_provenance` (`provenance.classify_pnl`), `exit_reason`, `closed_at` |
| counterfactual (LTR only) | | `cf_r` (untouched bracket replay), `delta_r = net_r − cf_r`, `cf_provenance: computed` |
| `label_provenance` | enum | § 3.2 |
| `qualified` | bool | the source key is in `qualified.json` (§ 3.3) |

**The outcome join** uses the trainer's journal mirror, the same source as `trade_outcomes`. Rows with `pnl_provenance ≠ measured` keep their outcome but are flagged. Validation and training default to measured-only, per the canonical rule that `UNVERIFIED` is never folded into measured.

**Refresh cadence:** inside the existing daily trainer cycle (`ict-trainer.service → run_training_cycle.sh`). The producers are jsonl files on `main`, which the trainer git-pulls each cycle. No new service and no new cron. Build cost is a jsonl scan plus a SQLite join: INFERRED seconds at these volumes.

**The legacy file (#1) is ingested, but as `kind: legacy_score`:**
- `author_kind` comes from the template rule.
- `rubric_version: pre-v1`.
- `qualified: false` until a § 3.3 unit says otherwise.

It is kept for the rubric-reconstruction test and as a T1 baseline label. It is not a teacher.

### 4.3 The new Claude producer: the blind-then-reveal grade

This is the change that makes post-trade grading teachable. It runs in the `/performance-review` grading step, which already grades every closed package. The skill changes; the rubric script stays as the cheap fallback.

1. **Blind pass (T0).** Claude receives only decision-time inputs:
   - the package's `signal_logic`
   - the leg's bracket
   - masked recent candles (ATR-normalised, no symbol or date, § 3.5.5)
   - the regime cell
   - correlated open exposure at the time

   It writes `grade_score`, `entry_quality`, `risk_management` and a one-line thesis to `comms/claude_judgments/blind_grades.jsonl`.
2. **Reveal pass (T1).** Claude is shown the outcome, the path (MFE/MAE) and the exit. It writes `exit_quality`, a revised grade and `alternative_action` to `revealed_grades.jsonl`, keyed to the blind row.

**The blind half is the teacher target.** The reveal half is a T1 label, and the difference between the two is itself a diagnostic of hindsight bias.

- **Retroactive scale:** 1,823 distinct closed trades already have packages and `signal_logic` (the rubric file's distinct `linked_trade_id`). So a backfill can reach the n floors without waiting for accrual, subject to the § 3.5.5 cutoff exclusion.
- **Backtest scale (distillation proper):** the harness ledgers' `--emit-trades` rows (`ML-M4` widens them with decision-time features) give tens of thousands of cases. Claude grades a sample; the student learns to grade the rest.
- **Cost:** UNKNOWN until measured. A 50-trade pilot (row CJ-3) records tokens and dollars per grade via `spend_meter.py`, and the backfill size is set from that number and the operator's budget (Q1).

### 4.4 The fields LTR-2 must carry so it is ML-ready from day one

The schema in `live-trade-review-DESIGN.md` § 3 is close. **Add these fields, and nothing else changes:**

| field | why |
|---|---|
| `schema_version` | the builder normalises by version, not by guessing a shape (§ 1.4) |
| `info_cutoff_at` | the last closed bar, mark and fill the reviewer saw. It is the T0 test |
| `prompt_sha`, `skill_sha` | the skill file's git blob hash. Label version (§ 3.4); `model` is already there |
| `features_at_review` | the numeric state the reviewer was given (`open_r`, `peak_r`, `giveback_r`, `bars_held`, `atr_now_over_entry`, regime cells, correlated exposure), **as a flat object of numbers**, so the student trains on exactly what the teacher saw |
| `recommendation.action` **as a closed enum**, plus `recommendation.level_atr` | the distance in ATR from the mark, so it is comparable across symbols. A prose action cannot be a label |
| `options[*].net` | `true` when the option's numbers are net of the full cost stack (the LTR-0 table promises it). This states it per row |
| `judge_prior` | the reviewer's probability that `hold` ends worse than the recommendation. Without a number there is no calibration (§ 3.3) |
| `applied` | whether the action was applied, separate from `disposition.route`. A recommended-only row is a cleaner counterfactual than an applied one, because the realized path is the untouched bracket |

And in `outcomes.jsonl` (LTR-5): `net_r`, `cf_r`, `cf_method` (the monitor replay version), `pnl_provenance`, `cf_provenance: computed`.

### 4.5 The first manifests (all `target_deployment_stage: candidate`)

| manifest | target | features | baseline it must beat (OOS, purged WF-CV, net R) | gated on |
|---|---|---|---|---|
| `claude-blind-grade-student-v1` | blind `grade_score` (teacher) | decision-time package features: the `setup_candidates` / signals-catalog columns, regime, hour/day | the take/skip selection lift of the student's score vs **take-all** and vs the **confidence-only** control, net R + max DD in ≥ 2/3 folds. This is the ML-M5 rule shape. Imitation accuracy is reported, not gated on | CJ-4 passes (§ 3.3) for the blind source |
| `ltr-tighten-head-v1` | `delta_r` sign and size for `tighten_sl` vs `hold` | `features_at_review` | always-hold and the leg's best static trail from `exit-refinement` | n ≥ the floor on recommended and applied rows (proposed 150 reviews with outcomes), and the LTR source qualified |
| `claude-revealed-vs-outcome-control-v1` | net R of the *next* k trades on the same leg and state | revealed grade vs realized R of the graded trade | — (this **is** the T1 validation of § 3.3, run as a unit, not a manifest) | ≥ 150 revealed grades |

The family dashboard (`ml_plan_status.py --diversity`) will count these as the families they actually are (logit or GBDT). Distillation is a *label source*, not a model family.

### 4.6 Who consumes and reports it

- **Sunday `/ml-review`, step 9 (the ML plan loop):**
  - one block, "Claude-taught heads"
  - per source key: n, the qualified state, the last validation verdict
  - per student: stage, OOS edge vs baseline, teacher agreement as a diagnostic
  - label distribution drift by `label_version`
  - plan items in `docs/plans/ml-plan-items.yaml` (§ 7) so `ml_plan_status.py` flags staleness
- **Weekly `/performance-review`:**
  - the blind-vs-revealed grade gap per leg (hindsight bias)
  - Claude blind-grade IC vs `confidence` IC over the window
  - for LTR, the "Live review" section the LTR design already specifies
- **`/perf-followup` Track 2** reads the revealed grades as a population of lessons, as it already does for the free-text grades.

---

## 5. Fixes to make now

Small, Tier 1, and independent of the build. All go in row CJ-0.

| id | fix | evidence |
|---|---|---|
| **F1** | **Retire `comms/claude_trade_scores.jsonl`**, rather than fill it. Its role moved into `claude_strategy_scores.jsonl` with `keyed_on: linked_trade_id` (JC-SA-01). Mark the schema file `superseded_by`, and point its readers there | 0 rows (§ 1.1 #3). Per-trade rows exist in the other file (747 keyed per trade) |
| **F2** | Correct the two docs that say grades feed `ml/`: `docs/ARCHITECTURE-CANONICAL.md` (training workflow, step 1) and `docs/ml/training-center.md` ("Training session workflow", step 1) | § 1.3 grep |
| **F3** | `ml/configs/baseline-setup-quality-audit.yaml` `description`: replace "against the health-review audit labels (the post-hoc reviewer's setup grades)" with "per-`audit_pattern` mean R-multiple from the pipeline's `signal_audit.jsonl` patterns". The notes already say this; the description contradicts them | the file: `feature_column: audit_pattern`, `target_column: r_multiple`, family `setup_labels_audit` |
| **F4** | `score_order_packages.py`: emit `author_kind: "rubric_script"` and a `rubric_version` on every new row, and stop writing `reviewer: "claude"` for script rows. Existing rows stay untouched (append-only); the builder derives the field for them | § 1.4 |
| **F5** | `review_journal` family plus `baseline-post-trade-review.yaml.disabled`: retire both, superseded by `claude_judgments`. Its source (`comms/requests` free text) has produced 0 rows since 2026-05 | § 1.1 #11 |
| **F6** | Normalise the vocabulary in the builder, not the file: `good` → `acceptable`, `poor` → `late`, flagged `vocab_mapped`. Add the 114 + 6 dedupe rule (latest `reviewed_at` per key and `keyed_on`) | § 1.4 |

---

## 6. Risks

| risk | mitigation |
|---|---|
| The teacher is no better than the strategy's own confidence | § 3.3 requires beating `confidence`. If Claude fails, we have learned it cheaply and stop; that is a result, not a failure of the mechanism |
| LLM memory of historical prices inflates blind grades | § 3.5.5 masking plus the `pre_cutoff` exclusion |
| Model or prompt churn makes labels non-stationary | § 3.4 versioning. A version change is a fold boundary and re-qualifies the source |
| LTR exploration bias: Claude reviews only "interesting" states, so `delta_r` is learned on a skewed population | record `trigger`, which LTR already has, and the due-but-`hold` rows. Weight by inverse trigger propensity, or restrict the head's claim to triggered states. Stated as the head's scope, not hidden |
| A Claude-taught model drifts toward imitation instead of edge | the promotion metric is net R vs baseline, never agreement (§ 3.6) |
| Spend | the pilot measures it (CJ-3), and Q1 bounds it. The student is the mechanism that keeps the cost per case falling |

---

## 7. Build plan: proposed checklist rows (NOT filed by this PR)

Roadmap `M25` for all rows. Rows 4 and 6 also reference `L-ATM` through LTR.

| order | id | what | tier | model | ceiling | depends on |
|---|---|---|---|---|---|---|
| 1 | `CJ-0-FIXES` | § 5 F1–F6. Also one diag read of `insights_history` (row count by `model_id`) to close § 1.1 #8's UNVERIFIED | 1 | Sonnet | $4 | — |
| 2 | `CJ-1-LTR2-ML-FIELDS` | § 4.4 fields added to the LTR-2 schema and validator. **Folded into `LTR-2-RECORDS` if that row has not started**, else a follow-up | 1 | Sonnet | $2 | LTR design approved |
| 3 | `CJ-2-DATASET` | `ml/datasets/families/claude_judgments.py`, registry entry, § 3.5 tests 1–4 and the `claude-judgments-guard` manifest lint, legacy ingestion with `author_kind` derivation | 1 | Opus (leakage design) | $10 | CJ-0 |
| 4 | `CJ-3-BLIND-GRADE-PILOT` | `/performance-review` skill: the blind-then-reveal protocol (§ 4.3), the masking helper, the `comms/claude_judgments/` stores and schema, a 50-trade pilot with measured cost per grade | 1 | Opus | $8 | CJ-2 |
| 5 | `CJ-4-LABEL-VALIDATION` | pre-registered `research/queue/` unit(s), § 3.3, for the blind source and the revealed-vs-outcome control. Writes `comms/claude_judgments/qualified.json` | 1 | Sonnet | $4 | CJ-3 backfill reaches n ≥ 150 |
| 6 | `CJ-5-STUDENT-MANIFESTS` | § 4.5 manifests at `candidate`. `ltr-tighten-head-v1` waits on LTR n | 1 | Sonnet | $6 | CJ-4 PASS (blind); LTR-5 plus n (tighten) |
| 7 | `CJ-6-REVIEW-HOOKS` | § 4.6: the `/ml-review` step-9 block, the `/performance-review` lines, `ml-plan-items.yaml` entries (an `ML-CJ*` track) | 1 | Sonnet | $3 | CJ-2 |

Total ceiling: **$37** across 7 rows, plus the backfill spend Q1 sets.

**What closes the operator's request:** CJ-2 and CJ-3 landed, *and* one trainer cycle builds `claude_judgments` with non-zero T0 rows (OBSERVED on the trainer). Until then the mechanism is designed, not running.

**If CJ-4 FAILS:** distillation stops for that source key. The dataset, the versioning and the LTR counterfactual path (rank 1, which does not depend on Claude being right) stay. The failure is recorded on `ML-CJ*` as the answer.

---

## 8. Questions for the operator (preferences only; no data settles these)

- **Q1: backfill budget.** The blind-grade backfill makes the corpus reach n quickly. The 1,823 historical closed trades come first; a backtest-ledger sample is optional. Cost per grade is unknown until the CJ-3 pilot measures it. **What is the most you want spent on teacher labels per week?** Proposed default: grade the historical trades once, then only new closes, with no backtest sample until CJ-4 passes.
- **Q2: Claude in the decision path.** Should a live Claude assessment ever be a model **feature at decision time** (§ 2 rank 5)? That puts a paid external API, and its outages and version changes, upstream of an advisory model. Or is Claude **teacher-only**, with the students carrying its judgment into the live path? Proposed default: teacher-only.

---

## 9. What this lane did and did not do

**Did:**
- measured § 1 on `origin/main` @ `05b4e72e`
- read the LTR design (`docs/plans/live-trade-review-DESIGN.md`, on `main` via #20088)
- read `ml/` (families, registry, `oos_edge`, `stage_guard`, metadata), the rubric script and the ML plan

**Did not:**
- file rows or queue units
- edit `ml/`, skills or the canonical docs (F2 names the fixes; CJ-0 makes them)
- read `insights_history` on the VM (§ 1.1 #8 stays UNVERIFIED)
- compute net-of-cost R for § 1.2. Those figures are **gross** price R parsed from the rubric rationale, so they show the grade's *shape*, not anyone's edge
