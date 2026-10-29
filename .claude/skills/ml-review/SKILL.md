---
name: ml-review
description: Weekly review of the ICT bot's ML LIFECYCLE, built on the shared four-layer analyst pattern (docs/reference/llm-analyst-skill-design.md). Layer 0 grades the previous review's calls. A fixed CHECKS layer (scripts and relays with stated populations) covers registry state, data and label freshness, the produced→labelled→trained→scored→changes-an-order chain, serve parity, drift split into score drift vs labelled decay, champion vs challenger on one replay and cost stack, and family concentration. An ANALYSIS layer then reasons over that evidence and a wide context: why each model does or does not add value to the decisions it feeds, which hypotheses were tested, and the next experiments ranked by expected value per cost. Each decision is a call with a pre-registered check. It also covers promotion/demotion proposals against the 3-stage ladder (candidate→shadow→advisory), the ML plan loop and the backlog drain. Files follow-ups to docs/claude/work/pipeline/ and the checklist. Use when the ML-FRONTIER-PREP lane of the Wednesday "Weekly review prep" routine runs, or when the operator says "run the ml review", "/ml-review", "how are the models doing", "is the ML learning", or "what should we train next". NOT for live trading promotion past shadow (Tier-3, operator-gated): this skill proposes and the operator promotes. NOT for system health (use /health-review) and NOT for strategy trade scoring (use /performance-review).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /ml-review — model/training lifecycle review

> **Practice principles (pointer):** the design and evaluation choices this skill makes follow [`docs/reference/trading-and-model-practice-principles.md`](../../../docs/reference/trading-and-model-practice-principles.md) (TRADING T1–T10 · MODEL M1–M10 · RESEARCH-OPS R1–R6), refreshed weekly by `frontier-research`. A principle never overrides a binding rule.

> **Why this shape (operator, 2026-10-28, binding).** This skill follows the shared pattern in
> [`docs/reference/llm-analyst-skill-design.md`](../../../docs/reference/llm-analyst-skill-design.md): **Layer 0** prior calls ·
> **Layer 1** CHECKS · **Layer 2** ANALYSIS · **Layer 3** decisions. Point at it; do not restate it. The pattern governs its
> rules (windows, sequential decay tests, competing hypotheses, neutral framing, no quota, probabilities with pre-registered
> checks) and the output template. This file only adds what is specific to ML.
>
> The ML evidence for the redesign is in
> [`docs/research/ml-review-frontier-diagnosis-2026-10-28.md`](../../../docs/research/ml-review-frontier-diagnosis-2026-10-28.md):
> - **too loose:** the trainer relay was skipped in 3 of the last 4 runs, so there was no gate packet and no soak audit;
> - **too scripted:** 90 of 96 per-model notes were two template phrases;
> - **wrong metric:** demotion arguments about a head that gates no order;
> - **not asked:** whether the ML is learning.

**What this session is.** End-to-end QA of the ML lifecycle. HUNT for broken or degenerate models, stalled cycles, GIGO datasets,
drift, heads that influence nothing, and data that is recorded but never learned from. ROOT-CAUSE what you find, then FIX it in
tier or FILE it as a row or unit. Put the Tier-3 calls to the operator with the exact change. Logging a fixable issue as a post-it
is a review failure. It is one of three reviews (`/health-review`, `/performance-review`); do not do their work.

**Cadence and coordination.** The review runs weekly, in the `ML-FRONTIER-PREP-<date>` lane of the Wednesday "Weekly review prep" routine (~18:53Z, after
the usage reset), and it feeds Thursday planning. The same lane runs `frontier-research`, and its kept candidates feed the next-experiments question below. Read your
checklist row, title it `ML-REVIEW-<YYYYMMDD>` (exempt from the `UNPLANNED` flag), and check the checklist for another lane already
on the trainer (a cycle or a build) before you pull. Claim the merge slot before landing
(`scripts/ops/claim_merge_slot.py --branch-claim --branch <b> --held-by <session>`). **Do not re-measure** what a same-week lane
already measured with a locator (e.g. `ML-COVERAGE-AUDIT`, `ML-PROGRAMME-PLAN`). Cite it, then check only what changed since.

---

## Layer 0 — PRIOR CALLS (always first)

**Follow-through first (2026-10-28):** run `python3 scripts/ops/review_followthrough.py --source ml-review --window-days 7` and record its cohort and backlog line before grading calls; an open item older than 14 d with no owner is a call to schedule or kill, not to re-file.

Read the previous `comms/reviews/ml-review-*.json` `calls[]`, and the previous `comms/ml-plan/*.json` `calls[]` / `frontier.grades`.
Re-run each call's own `check.command` and apply its `check.rule` as written. Grade each call `hit | miss | unresolved | void`,
and say whether its action happened. If it did not, say why, and re-file or kill it.
- Older records have no `calls[]`. For those, grade `promotion_recommendations[]`, `next_by_value_per_cost[]` and every
  "re-read next week" line, and say that you did. Example: P-1014's "BTC moderate drift: re-read next week".
- Keep the Brier series in `prior_calls_scorecard`. Below 10 resolved calls it is `INDETERMINATE` (pattern § 6).

## Layer 1 — CHECKS (run all of them; fixed order; each prints a state)

**Pattern rules apply to every row** (pattern § 2):
- **Windows** are lifetime / 90d / 30d / 7d. The training OOS figure is the lifetime baseline.
- Each check is measured **against its own expectation**: the registered gate, the training OOS metric, or the incumbent.
- **Decay is judged by a sequential test, never by one window.** The ML instrument for this is `LIVE-DECAY-MONITOR` (CUSUM,
  practice principle M10). Until that instrument exists, C7(b) reads `could_not_look: no instrument` and names the row. A cruder
  substitute is never hand-rolled in the session.

**Fire the trainer pull FIRST** (C1 block below). The Actions runner has queued it for 20–30+ minutes (2026-10-11), and C1, C5
and C6 wait on it. Do everything else meanwhile.

**The could-not-look rule.** Every check ends in one of three states:
- `ok`
- `finding` (with its numbers)
- `could-not-look` (with the failure)

A required check that cannot look is **chased this session**: retry with backoff, try the alternate route in the table, and
re-fire the relay once. If it is still blind, the review is published `overall_assessment: investigate`, the gap is filed as a
row naming the check, and the ANALYSIS layer may not draw any conclusion that depends on it. "Not run this lane" is never a quiet
footnote again (diagnosis § 2, "Checks actually run").

| # | check | how (exact) | population | `finding` when |
|---|---|---|---|---|
| **C1** | **Trainer + registry state** | the trainer-vm-diag block below (`ml list-models`, `ml stage-guard`, cycle log, builds) · direct HTTPS `GET /api/bot/ml/{status,registry,cycle,builds}` | every registry row; the last cycle | timer not active, last `cycle_end` > 24h, `overall_rc≠0`, builds failed, a `manifest_oom_red_flag`, a stage change with no recorded decision (`--plumbing` `REGISTRY-STAGES-CHANGED`) |
| **C2** | **Data and label freshness** | `python3 scripts/ops/ml_plan_status.py --plumbing` (exit 0 clean · 1 findings · **2 = could-not-look, an incident**) · gate-check `labels_accruing` per head (C1 block) | every shadow/advisory head; every dataset family the plan names | a family's newest build > 72h; `TRAINING-STALENESS`; labelled/total < 0.5 on a head (stale candle base, the MES 1,213-of-1,861 class); a shard ending at an exact page multiple (the `ML-SHARD-TRUNCATED` class) |
| **C3** | **Business-use map: what each model can change** | for every model at shadow/advisory, and any model a consumer reads, map it to its consumer and the legs where it can change an order. Method and consumer list: `docs/research/ml-coverage-audit-2026-10-28.md` § 1b (router `trend_vol` cells in `config/regime_policy.yaml`; exit-head `exit_head_action` in `config/strategies.yaml`; conviction stamps on `GET /api/bot/order-packages?...&include_paper&include_demo`; advisory sizing). Re-parse config each run; **never quote last week's counts** | rostered legs (re-parse `config/accounts.yaml`), and every shadow/advisory model | an advisory head with **0 legs it can change** (the SOL/MES case); a consumer that reads no model (conviction = `c_strat` only); a real-money leg with no ML input. Report `legs_changed / rostered` and `real_money_changed / real_money` |
| **C4** | **The learning chain (is it learning?)** | ML-PROGRAMME § 7 hops **H1 produced → H2 labelled → H3 in a dataset → H4 trained → H5 scored → H6 promoted → H7 changes an order**, per source (desk decisions, live-review rows, trade closes, paths corpus). Run `scripts/ops/ml_learning_ledger.py` **once it exists** (row `ML-LEARNING-LEDGER`). Until then, compute each hop from the sources in that table, and mark a hop you cannot compute `could-not-look` | each data source in ML-PROGRAMME § 7; the window = since the last review record | any hop at 0 for 14 days while the hop before it is non-zero; a manifest absent from the registry after 2 cycles (the `exit-policy-v1` class); `consumed.jsonl` not growing |
| **C5** | **Serve parity + soak mechanics** | for each shadow/advisory head, diff the live-logged `feature_row`s (`shadow_predictions.jsonl` via `/api/bot/shadow/predictions`) against its training dataset: present AND non-default AND equal; gate-check `live_parity` | every shadow/advisory head | a feature that is dead on one side and live on the other (the ETH `xa` all-zeros class); parity rows below the gate floor because of the daily-retrain reset (run gate-check about 20h after the cycle). Soak rule: **mechanics, never edge, never a sample size**. Point at [`OPERATING-PLAN § 2`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md); do not restate it |
| **C6** | **Champion vs challenger, one replay, one cost stack** | `python -m ml gate-check <id> --db data/trade_journal.db --datasets-root datasets-out` (on the trainer) for every shadow head with a challenger relation — its `cost_net` + mechanical `shadow_soak` (1–2 clean scored predictions, no calendar term) gates — and quote each run's `cost_gate.json` (enforced cost-net decision value vs incumbent + take-all / take-none / matched-random on the same rows, PSR and deflated Sharpe over `n_trials`; `promote-stage` refuses a failed or missing one, row `ML-TRAINING-PRINCIPLES-GAPS`); for any `research/results/` record this window that compares a challenger to an incumbent, check that it used **the same fold file, the same rows and the same cost stack** (`execution_costs.resolve_cost_policy()`) | each (champion, challenger) pair: an advisory head and its shadow or offline rivals on the same target | a comparison on different rows/folds/costs (not reported as a result; filed as a re-run); a challenger `ready: true` with no proposal; a champion beaten on the same replay and still advisory |
| **C7** | **Drift, split** | (a) **score/data drift**: `GET /api/bot/shadow/drift?model_id=X` (KS/PSI), plus the weekly plan-only scan below; (b) **labelled-performance decay**: rolling log-loss/Brier or decision value on *labelled* live rows vs the training OOS figure (`/api/bot/trades/scores`, gate-check `oos_edge`) | every shadow/advisory head | (a) alone is a `watch`. It becomes a remediation row only when **persistent** (the same model drifted in 2 consecutive weekly reads). (b) beyond the head's registered tolerance on any `advisory` head is the urgent case |
| **C8** | **Concentration (aggregate model risk)** | `python3 scripts/ops/ml_plan_status.py --diversity`, plus from C3: how many advisory heads share one target/family/data source | registry; open family-tagged plan items | `CONCENTRATION` / `FAIL-STREAK`; all advisory heads on one target; a (symbol, target, timeframe) cell with > 3 nightly manifests (ML-PROGRAMME § 3.2 cap) |
| **C9** | **Research landed + backlog population** | `git log --since=<last record> -- research/results comms/research`, filtered to ML plan refs; per result, the unit's `decision_rule` applied by `research_disposition.py --record` (research-ops grades; you read). Backlog: the pipeline population defined in § "Backlog drain" | results since the last record; the open ML pipeline rows | a result with no disposition; a unit `blocked` across 2 reviews (raise it, do not re-file); `count_untriaged > 0` |

**The trainer block (one batched trainer-vm-diag issue, label `trainer-vm-diag-request`):**

```
cmd: |
  REPO=/home/ubuntu/ict-trading-bot; cd "$REPO"
  echo "=== SERVICE ==="; systemctl is-active ict-trainer.service ict-trainer.timer
  systemctl show ict-trainer.service --property=ExecMainStatus,ActiveEnterTimestamp,ActiveExitTimestamp
  echo "=== CYCLE ==="; tail -n 100 runtime_logs/training_cycle.jsonl
  echo "=== BUILDS ==="; tail -n 40 runtime_logs/trainer/dataset_builds.jsonl
  echo "=== REGISTRY ==="; .venv/bin/python -m ml list-models
  echo "=== STAGE-GUARD ==="; .venv/bin/python -m ml stage-guard --db data/trade_journal.db
  echo "=== GATE-CHECK ==="; for m in <every shadow/advisory model_id>; do .venv/bin/python -m ml gate-check "$m" --db data/trade_journal.db --datasets-root datasets-out; done
  echo "=== DRIFT SCAN (plan-only) ==="; sudo systemctl start ict-drift-retrain.service; systemctl show ict-drift-retrain.service -p Result,ExecMainStatus
  python3 -c "import json,datetime as d;c=(d.datetime.utcnow()-d.timedelta(hours=1)).isoformat();R=[json.loads(l) for l in open('runtime_logs/drift_retrain.jsonl') if l.strip()];R=[r for r in R if r['ts']>=c];print(len(R),'rows');[print(r['ts'],r['action'],r['model_id']) for r in R if r['action'] in ('dispatch','skip_no_manifest')]"
  echo "=== RESOURCES ==="; df -h /home | tail -1; free -m | head -2
```

There is **no** `python -m ml.registry list`. **Direct HTTPS first** for every `/api/bot/ml/*` and `shadow/*` read
(`https://ict-bot.duckdns.org/api/bot/<path>`, no token; MEASURED 200 on 2026-10-04 including the 6.5 MB registry). The
`vm-diag-snapshot` relay is the fallback, and only `shadow/{predictions,stats,drift}` and `trades/scores` are on its allowlist;
batch them into ONE `vm-diag-request` issue (MB-20260706-CI-MINUTES). If the mirror's age is far older than the last cycle, the
trainer pull is ground truth.

**C1 detail — single-manifest OOM red flag (mandatory; BL-20260717).** Scan the cycle log for `manifest_oom_red_flag`,
`manifest_oom_retry` and `manifest_oom_recovered`. A red flag means a manifest OOMs alone on 3 consecutive cycles. Under NO-HALT it
is still retried every cycle, so the flag is a **required disposition**: (a) shrink peak RSS (Tier-3 manifest proposal),
(b) route it to the GPU burst, or (c) drop or split it. File a pipeline row naming the disposition; `manifest_oom_recovered`
closes it.

**C7 detail — the plan-only drift scan (operator, 2026-10-25, binding).** The `ict-drift-retrain.timer` is retired. The scan runs
here, plan-only. **Do not re-add a timer and do not set `RETRAIN_PLAN_ONLY=0`.**
- **Drifted** means `action ∈ {dispatch, skip_no_manifest}` in `runtime_logs/drift_retrain.jsonl` within the last hour.
- An rc other than 0 or 11, or an empty log, is **could-not-look**, never "no drift".
- **Persistent** means drifted in this read AND in the previous record's `drift.drifted`. Each persistent model gets a
  `DRIFT-REMEDIATE-<model_id>` checklist row (`scripts/ops/checklist.py add`, with a roadmap ref and both read dates), or a note on
  the existing row. Then apply the `drift-remediation` skill.
- A first-time drift is *watch*.
- Copy the drifted list into the run record, because the trainer log is not in git.

---

## Layer 2 — ANALYSIS (reason; the pattern fixes the method, not the answers)

Read the checks **together with** the wide context:
- the previous review record and its calls;
- this week's research results and the frontier scan;
- the ML plan (`docs/plans/ML-PROGRAMME-2026-10-28.md`, `docs/plans/ml-plan-items.yaml`);
- the practice principles;
- what `/performance-review` said about the legs these models feed.

Every claim names its population and its MEASURED / INFERRED status. Every recommendation names the alternative you rejected,
and why.

The pattern's ten prompts (§ 3) apply; read them first. The questions below are where the ML review usually finds its 3–7
material ones. They are **candidates, not a quota**: pick by money and decision impact, write ≥ 2 hypotheses per question (one
is always noise / expected variation), run the discriminating test, and record what was eliminated.

- **Value (start from C3, not from the registry).** For each model that can change an order, what is its *decision value*?
  That is: what the consumer would do without it, on which legs, net of cost, out of sample (M6, M10). Say whether that value is
  measured or only implied by a classification metric; a macro-F1 lift is feature lift, not value. For each consumer that reads
  no model, and each model that feeds none, ask why: wiring, a missing cell, a degenerate head, or a question nobody owns. Every
  candidate-only model is **one line** (count and families).
- **What this week's tests mean.** Take each C9 result and each C6/C7 finding. Say what it shows **and does not show**, and
  whether the test could have answered the question at all. Check power on the **unit of the test**: folds for a fold-paired
  interval, with the corrected resampled variance (`ff8f-04`: "power" was computed on 24,000 rows, but the test was over 5 folds
  and needed ~70). Look for patterns no single unit shows: every arm matches LightGBM, every null comes from one data limit,
  every family was tested on one target.
- **Is it learning?** Find the first broken C4 hop, and the reason it broke.
- **Drift and risk.** Use C5/C7. An input shift on a head whose labelled performance holds is a regime-mix question, not a
  capability failure. Name the mechanism you believe and the observation that would refute it.
- **Next experiments, ranked by expected value per cost.**
  - Score each as (decision value if it passes) × p(pass) × (powered at the registered design?) ÷ (cost and time to a verdict).
  - Combine A-questions with the frontier scan's kept candidates.
  - Prefer real-money legs, order-changing consumers and the broken C4 hop over another variant in a crowded cell (C8).
  - Every experiment filed as a unit names its consumer and the decision it would change (`ml_consumer:`,
    `research/queue/PLANNING.md` § 1c); the station it serves is in `docs/plans/ml-pipeline-design-2026-10-29.md` § 1.
- **Stages.**
  - Cite the gate packet (`ready`, `blocking[]`) **and** the C3 decision value.
  - A head that changes no order is a wiring-or-retire question, not a promotion question.
  - Never `promote` on `ready: false`.
  - `shadow → advisory` and every demotion are Tier-3, or data-backed per canonical § "Data-backed Tier-2/3 decisions".

## Layer 3 — DECISIONS

Every call is a `calls[]` entry with `p`, `tier` and a **pre-registered `check`** (`command`, `rule`, `resolves_when`). Its
ending is one of:
- a checklist row;
- a `research/queue/` unit (rule registered first, power on the test unit);
- a pipeline item;
- `no action, because …`.

Premortem each one (pattern § 3.9). Next week's Layer 0 re-runs the check as written.

**Anti-patterns (each one is a review failure; check your draft against them before you publish):**
- one row per registered model as the body of the review;
- a metric restated with no "so what";
- "no change this week" with no C3/C4 numbers behind it;
- "needs more soak/data" without a power calculation or a filed accrual row;
- a promotion argument about a head that changes nothing;
- a comparison on different rows or costs reported as a result;
- a missing check footnoted instead of chased;
- a proposal with no rejected alternative;
- plus the pattern's list (§ 5): week-only windows, restating numbers, predetermined outcomes, amnesia, dead-end endings.

---

## Output — fixed template

**1. The brief.** Markdown in the pattern's § 4 order, headed `MODEL track — /ml-review <date> — <the one sentence that most
affects money/risk now>`:
- `0 Prior calls`
- `1 CHECKS`: C1–C9 tables, each with population + windows, could-not-look listed
- `2 ANALYSIS`
- `3 Decisions`
- `4 Not done`

Under `1 CHECKS`, always print the two headline numbers: ML changes x/rostered legs and y/real-money legs, and the first broken
C4 hop. Add a `TRADING track` line only where a decision touches a leg's trading; cite the leg and hand it to `/performance-review`.

**2. The response JSON** follows `comms/schema/ml_review_response.template.json`. It carries the pattern's four blocks,
`prior_calls_scorecard`, `checks{C1..C9}`, `analysis{questions[], surprises[]}` and `calls[]`, plus the ML blocks:
- `model_status[]`: **only** shadow/advisory models and any model a consumer reads; everything else is one count line in
  `model_status_summary`;
- `promotion_recommendations[]`, `experiments_proposed[]`;
- `backlog_drain[]`, `backlog_coverage`;
- `anomalies[]`, `recommended_action`, `operator_attention_required`.

Write it to `comms/reviews/ml-review-<YYYYMMDD-HHMMSS>.json`.

**3. The ML plan run record** `comms/ml-plan/<YYYYMMDDTHHMMZ>.json` (§ "The ML plan loop" step 6).

**4. One ping** via the `send-ping` system-action (fallback `docs/claude/pending-pings.jsonl`), ≤ 200 chars:
`/ml-review — ML changes x/N legs (real-money y); chain: <first broken hop|ok>; <P> proposals; calls hit/miss h/m; trainer=<state>.`
Priority `high` only if an advisory head is decaying on labelled data.

---

## Lifecycle rules (unchanged in substance; they feed C1/C5/C6 and the stages question)

- **3-stage ladder** `candidate → shadow → advisory`. Normalize legacy names with `ml.manifest.canonical_stage` and report the
  canonical stage. `candidate → shadow` is the trainer's autonomous track: note readiness, and the `model-training` skill flips it.
  `shadow → advisory` is the live-trading gate (Tier-3).
- **Refine, do not abandon** ([`docs/claude/model-refinement-lifecycle.md`](../../../docs/claude/model-refinement-lifecycle.md)):
  - A stage-guard `demote` on an advisory head becomes a soft-off proposal (advisory → shadow) plus a `[refinement]` pipeline row,
    with a hypothesis and `resolution_criteria`. The row resolves as re-gate → restore, or 3 attempts → retire to candidate.
  - Drive each open `[refinement]` row one step every run.
- **Lens role** (`docs/unified-confidence-risk-DESIGN.md`): tag each model as `c_reg` / `c_setup` / `c_wr` (conviction) or sizing.
  `conviction-meta-v1`'s `shadow → advisory` is the switch that turns learned conviction live. Report calibrator coverage, staleness
  and Brier/ECE (`scripts/ml/fit_confidence_calibrators.py`). A degenerate head feeding conviction is a conviction-quality finding.

## Backlog drain — a hard completion gate

- **Population** (fixed 2026-10-04): every record in `docs/claude/work/pipeline/` (folded by `scripts/ops/pipeline.py::load()`;
  `PIPELINE.jsonl` is the legacy name) whose `state` is not `done`/`killed` AND that matches any of these:
  - `origin.ref` names `ml-review`;
  - `routed_to` starts with `ML`;
  - `what` starts with `[ml]` or `[refinement]`.
  Print the count and the ids first. A row that matches only on an incidental string is recorded as not-ML.
- **Triage every one** against this run's checks, into one of: resolved · fixed_now · invalid/superseded · kept_open (with this
  run's re-validation and the blocker).
- **Writing back:**
  - a re-read: `python3 scripts/ops/pipeline.py --redate <id> --observation … --next-due …`;
  - a state change: `append(rec, intent="update", based_on=read_log(STORE).sources[id])`;
  - a new finding: `mint_id()` + `intent="new"`, with `origin{kind,ref,rerun}` and `due_when`.
  `load()` returns a `LoadResult`; iterate `.items`.
- Emit `backlog_coverage{open_at_start, triaged, resolved, fixed_now, closed_stale, kept_open, count_untriaged}`.
  **`count_untriaged` must be 0**, or the review is incomplete and does not ping.

## The ML plan loop (operator, 2026-10-11, binding) — consumes the checks; produces plan movement

Artefacts the loop edits:
- `ROADMAP.md` § "AI trader (ML) — build plan";
- `docs/plans/ml-plan-items.yaml`;
- `comms/ml-plan/<stamp>.json`.

The consolidated programme is `docs/plans/ML-PROGRAMME-2026-10-28.md`: its § 4.3 questions are plan track T3, and its § 7 ledger is C4.

1. **Plan vs field.** C2's `--plumbing` flags are resolved in this run:
   - `ORPHAN` / `CLOSED-OPEN` / `OPEN-DONE` / `STALE`: re-point the item, close it with its terminal reason, or file the row.
   - `UNPLANNED`: fold it into the plan or kill it.
   - A stage decision updates `plumbing.expected_registry_stages` in the same run.
2. **Results read.** From C9, set each plan item's state and update the roadmap's measured-state table with the numbers **and their
   locators**. A line is killed only by its registered exhaustion condition, never by one pass.
3. **Plumbing.** C2/C4/C5. A silent or constant head with no owning row is a finding: fix it, file it, or add it to
   `plumbing.tracked` **with** its owning row.
4. **Ideas — at least one per run, or "none, because".** Come from the next-experiments question. Each idea becomes:
   - a `research/queue/` unit with its decision rule registered **before** the run (`perf-followup` § "Filing a queue unit"), with
     power computed on the test unit; or
   - a lever row plus a unit in `research/queue/blocked/`.
   A hand-written unit holds for a human merge (E57). A `CONCENTRATION`/`FAIL-STREAK` finding re-points capacity or opens a
   family-retirement review. It never queues another variant.
5. **Write back and re-prioritise.**
   - Update `ml-plan-items.yaml` (items only with their row or unit), the roadmap measured-state block (date + locators), and the
     order of work.
   - Close, kill or re-dispatch stale rows with a terminal reason.
   - Tell the manager the next rows by value per cost. The review does not spawn lanes.
6. **Record** `comms/ml-plan/<stamp>.json`:

   ```
   {run, finished_at, plan_items, open, flags, plumbing_findings,
    results_read[{unit, verdict, plan_item}], ideas[{id, source, rule_registered, power_unit}] | "none: …",
    frontier{… frontier-research § "The run record"}, practice{…}, drift{scan_rc, heads_scanned, drifted, persistent, watch, rows_filed, could_not_look},
    checks{C1..C9 states}, calls[ same shape as the review JSON calls[] ], writebacks, rows_filed, units_filed, next_by_value_per_cost, handoff}
   ```

   Cite its path in the response JSON's `sources` and in the ping.

Between runs (no lane): the manager's twice-daily read runs `ml_plan_status.py` (without `--plumbing`). research-ops sets the plan
item's state when it grades a plan-ref result.

## Limits

**Write:**
- pipeline rows via `scripts/ops/pipeline.py`;
- checklist rows via `scripts/ops/checklist.py`;
- queue units in a hold PR;
- the run record and the review JSON;
- the ping;
- read-only diag issues.

**Never:**
- touch `src/`, `config/` or `ml/configs/` (manifest and code changes are proposals);
- run a training cycle, promote, or build a dataset (chain into `model-training` after approval);
- promote past `shadow`;
- edit `config/strategies.yaml` or `config/accounts.yaml`;
- place an order;
- create a cron or trigger (a cadence change is a `handoff` request to the manager);
- close another review's rows;
- append to `comms/claude_strategy_scores.jsonl`;
- ask the operator to paste, SSH, or scope the review.

**Relays down:**
- If the trainer relay is down after the chase, C1, C5 and C6 are `could-not-look`. The review still runs the backlog drain, the
  rest of the checks and every analysis question that does not depend on them, and it publishes `investigate`.
- If only the live relay is down, the trainer view is ground truth, and you note the stale mirror.
- Never synthesize model data.
