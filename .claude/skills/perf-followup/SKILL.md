---
name: perf-followup
description: The routine that runs after every /performance-review lands — turns the review's findings into research. Four tracks: (1) TUNE underperforming legs (diagnose, pre-register, re-test), (2) LESSONS — a deep, wider-context post-mortem of the window's trades and strategies (not grading) naming the system's strengths and weak points, (3) EXTRAPOLATE each lesson to other legs and new strategy hypotheses, (4) PORTFOLIO research tied to overall net P&L (overlap, concentration, sizing vs contribution, drawdown clustering, add/remove). Every output is a research/queue unit or a checklist/pipeline row — never a memo. Closes the loop by reading what the previous run's units produced. Use when the manager dispatches a PERF-FOLLOWUP-<week> lane, or the operator says "/perf-followup", "follow up the performance review", or "what research comes out of the review". NOT for grading (that is /performance-review) and NOT for changing config (Tier-3 proposals only).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-10` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /perf-followup — from a performance review to research

> **Operator, 2026-10-10 (verbatim):** *"I want to make sure we also have a routine for followups from performance review, that should include things like: 1. Further research to tweak the underperforming strategies to see if we can improve them and try again 2. Lessons learned from trades that deserve further research - this means not just grading, but a deep, wider-context review the trades and strategies to identify the systems strong and weak points 3. Extrapolation of lessons to other strategies or new strategies 4. Portfolio level research that ties back to improving overall pnl"*

`/performance-review` grades and reports. This skill is what happens **next**: it asks
*why*, asks *where else it applies*, and files the questions that would change a
decision. It runs once per review, as one lane, on Sonnet.

## The one hard rule

CLAUDE.md § "Two categories. That is the whole taxonomy": **every output is a
`research/queue/<id>.yaml` unit (a question) or a checklist row / pipeline item (a
build or a decision).** A lessons write-up that nothing points at is a memo, and this
repo has 404 of them. So:

- Every lesson, tweak candidate and portfolio idea ends in exactly one of: a queue unit
  id, a pipeline id (`PI-…`), a checklist row id, or an explicit
  `"no action, because <reason>"` disposition. Nothing else is a valid ending.
- The run's record (§ "The run record") is a **ledger, not a deliverable.** It exists so
  the next run can check the work; it is valid only if every entry links onward.
- Do not write a prose report. The PR body carries the counts and ids.

## Inputs (read, don't ask)

| Input | How |
|---|---|
| The review | `comms/reviews/performance-review-<stamp>.json` — the one that triggered this run (named in your dispatch). **Start from its `calls[]` and `analysis.questions[]`** (two-layer reviews, 2026-10-28): your job is to TEST the hypotheses the review left `untested` or could not settle in-session, not to redo its checks or analysis. Also use `checks{}`, `strategy_performance`, `proposed_tweaks`, `anomalies`, `paper_book_tracker`, `real_money_allocation_benchmark`, `research_pipeline`, `prop_trade_quality`. |
| Grades | `comms/claude_strategy_scores.jsonl` — rows with `reviewed_at` in the window. Grade ≠ outcome; the disagreement cells are where lessons live. |
| Live trades | `diag-data` skill. Pull the window's closed trades and order packages per the same table as `.claude/skills/performance-review/SKILL.md` § "Fetching trade data" (batch diag paths into ONE issue; `limit` caps at 200, page with `&strategy=`). Run the artifact pre-filter (`scripts/analysis/classify_paper_records.py`, JOURNAL-shaped rows) — **bucket-A rows drive every statistic**; bucket-C only flagged as reconstructed. |
| Provenance | Read `docs/CLAUDE-RULES-CANONICAL.md` § "The row you are reading outranks the label in it" before concluding anything from a stored field. `strategy_liveness.py <strategy>` before quoting a rate as current. |
| Previous run | `comms/perf_followup/` — the newest earlier record (§ Step 0). |

If the diag relay fails, run what the review JSON alone supports, say what was not
pulled, and **do not fabricate** (same rule as `/performance-review`).

## Reading results: a FAIL is not a dead idea

When Step 0 or Track 1 reads a unit that FAILED its registered rule, that settles only the live/config
question the rule asked. Diagnose why (legs/regime, grid, trigger definition, cost drag, n/power, test
design), check outside sources, author pre-registered variant units, and record the programme as
**"first test failed → variants queued"**, never "dead". Policy and operator quote: `research-ops` § D;
family retirement: `scripts/research/family_retirement_policy.yaml`.

## Step 0 — close the loop on the PREVIOUS run (always first)

The previous run's units are this run's first input. For each entry in the newest
`comms/perf_followup/*.json`:

1. **Unit state.** For each `queue_units[]` id: `python3 scripts/research/research_queue.py`
   status + `last_dispatched_at`; results under `research/results/<id>/*.jsonl`;
   `python3 scripts/research/research_disposition.py --report` for read/unread.
2. **Classify each unit exactly one way** — never collapse:
   - `ran_and_read` — result landed and a disposition (`research_disposition.py --record`) exists.
   - `ran_unread` — result landed, nobody dispositioned it. **Read it now**, apply its
     pre-registered `decision_rule` (the result IS the decision), record the disposition,
     and carry any resulting build into a pipeline item/checklist row.
   - `not_run` — queued ≥ 7 days with no stamp. Find out why (`unroutable`, session-bound
     `run.workflow`, theme starvation, `blocked`) and fix it or file the fix. A unit that
     can never fire is the `PI-20261006-LCEVL8D5-0002` debt — don't add to it.
   - `underpowered` / `accruing` — a READ whose answer is "cannot answer yet"; leave it
     queued and state what accrual would change that. Not a verdict (research queue README § power).
   - `killed` — only with a stated reason.
3. **Pipeline items** the previous run filed: apply the same disposition test
   (`scripts/ops/pipeline.py --due`); re-run each `origin.rerun`; `done`/`killed` with a
   `terminal_reason`, or an `update` carrying fresh evidence.
4. **Write the result into this run's record** as `previous_run: {record, units_total,
   ran_and_read, ran_unread, not_run, underpowered, killed}` plus the actions taken. A run
   whose `previous_run` shows `ran_unread > 0` after Step 0 is **not done.**
5. **First-ever run:** `previous_run: null` with the note `"first run"`.

## The four tracks

Work in order; each later track consumes the earlier ones. Budget the tokens: Track 2 is
the expensive one (see § Cost).

### Track 1 — TUNE: underperformers get diagnosed, then re-tested

*Operator point 1.* For each leg the review marks underperforming (negative net window,
`grade_drift`, a `proposed_tweaks` demote/kill candidate, or a low-grade cluster):

0. **FIRST STEP — is the live result outside what the backtest predicts for this many
   trades?** (operator, 2026-10-15: *"that should be a first step for any underperforming
   strategy"*.) Run `python3 scripts/research/live_vs_backtest.py [--leg <leg>]` (reads the
   canonical journal via `/api/bot/performance/recent?n=200`, bootstraps the leg's committed
   Stage-0 per-trade `net_r`, reports p5/p50/p95 and the live percentile). The verdict picks
   the next step: `BELOW_BACKTEST` → a **fidelity/regime investigation unit** (research/queue)
   and then steps 1-2; `CONSISTENT` → **keep accruing** and let R4 decide at its
   pre-registered threshold (do not tune on luck-sized evidence); `NO_BACKTEST` → a
   **backtest unit**; `INSUFFICIENT_N` / `NO_LIVE_TRADES` → keep accruing. R4's 40-trade
   threshold is NOT changed by this. Limits (i.i.d., ~10% false flags across many legs) are
   in the script's docstring.
1. **Run `.claude/skills/performance-review/SKILL.md` § "Underperformance → diagnose, don't
   demote"** (binding; do not restate or shorten it here). Output: `cause ∈ regime | cost |
   execution | overfit` with the robust-retest reference. A demote is the last resort.
2. **Turn the diagnosis into a research unit** — one question per unit:
   - *regime* → regime-selectivity skill harness (`regime_cell_walkforward.py`); the unit
     asks whether a vol/trend off-cell survives walk-forward (no-cosmetic-cell rule).
   - *cost* → re-price on the full cost stack (`execution_costs.resolve_cost_policy()`;
     fee + slippage + funding). Harnesses lacking a full cost stack are out of scope for
     any promotion corpus (CLAUDE.md lists them).
   - *execution* → this is a bug, not research: a **checklist row** (build), not a unit.
   - *overfit* → walk-forward with exact live params; `backtesting` skill.
   - *exit shape* (giveback, MFE capture, TP-doctrine non-compliance) → `exit-refinement`
     skill; the unit sweeps the lever and registers the bar.
3. **Try-again loop:** if a prior unit for this leg already ran and failed, the new unit
   must change the *hypothesis*, not re-run the same parameters. Cite the prior unit id.
   (A first FAIL re-queues for a confirmatory run automatically — don't duplicate that.)

### Track 2 — LESSONS: the wider-context post-mortem (not grading)

*Operator point 2.* Grading already happened, and a two-layer review (2026-10-28) has already asked its 3–7 material questions: skip any cut below that its `analysis.questions[]` already answered with a test, and cite it. Here you read the window's bucket-A trades
**as a population** and ask what the system is good and bad at. Cover every cut below;
state the population (n, window, accounts, bucket) beside every number, and mark
estimated/unmeasured P&L as such (`journalTrust`, `provenance.classify_pnl`):

| Cut | Question |
|---|---|
| Regime / vol cell | Which `(trend, vol)` cells made or lost money, per leg and pooled? Is the router's off-cell policy firing where it should? |
| Time of day / session | Hour-of-day and session (Asia/London/NY, weekends) expectancy; clusters of stop-outs. |
| Entry quality vs signal features | Do the features in `order_packages.signal_logic` separate winners from losers? Where do A/B-graded entries lose and D/F-graded entries win (grade drift)? |
| Exit path | MFE/MAE per trade, giveback fraction, time-in-trade, exit-reason mix, **TP-doctrine compliance** (`python3 scripts/ci/check_tp_doctrine.py` — re-run, never quote counts): did the TP sit where the move was predicted to end? |
| Execution & cost vs assumed | Realized slippage/fee/funding vs the backtest's assumption per venue (feeds Gate-1 cost fidelity); partial fills; bracket anomalies. |
| Cross-strategy co-movement | Same-bar, same-direction clusters across legs/accounts; do losses arrive together? (Feeds Track 4.) |

**The live-review population is an input to this track** (LTR-5, design § 5). Read the review's `live_review{}`
block, or re-run `python3 scripts/ops/live_review_grade.py --live --json`, and treat `comms/live_review/reviews.jsonl` +
`outcomes.jsonl` as one more population: which legs, which state buckets (open R / peak R / giveback) and which actions
the reviewer keeps landing on, and what `delta_r` they earned. Two hooks:

- **A repeating pattern is no longer a judgment, it is an exit rule.** The same leg, the same state bucket and the
  same action in **3 or more** reviews becomes a pre-registered `exit-refinement` queue unit (as 4ef5-01 did), so the
  strategy's own `monitor()` does it free on every trade, in backtest and live alike. The reviewer's success measure
  is making itself unnecessary for each pattern it finds. Cite the `review_id`s as the lesson's evidence.
- **Judgement calls are a lesson about the reviewer.** If the `judgement` stratum's calibration reads `measured`
  (n >= 10 priced) and its Brier is worse than the `table` stratum, that is a weakness row; if it is `INDETERMINATE`
  say `anecdote` and end in an `accruing` unit, not a verdict. Carry each pattern found on one leg to its siblings
  in Track 3.

**Lessons → briefs (CLAUDE-GRADE-LOOP, operator 2026-10-26: "making sure those lessons are impacting how
we use the Claude decisions").** Read the review's `live_review{}` and `desk{}` blocks (or re-run
`live_review_grade.py --live --json` and `desk_grade.py --live --json`). Each **graded** Claude weakness
(a stratum whose verdict is `OVERCONFIDENT`, `NO_SKILL`, `NOT_MONOTONE`, `NEGATIVE`, or a use rule reading
`PROPOSE_NARROW`) becomes ONE versioned amendment of the contract that produced the calls:

- live-trade-review `SKILL.md` / `REVIEWER-BRIEF.md`, or trading-desk `DESK-BRIEF.md`;
- made in a PR (never a silent edit; one amendment per PR so its effect is separable), whose diff also adds
  one line to that skill's `AMENDMENTS.md`: `new_skill_sha` (`git hash-object <file>` after the edit),
  `prior`, `basis: <grader + window>, n=<k> <stratum>`, `change`, `PR #`;
- the amendment is graded by the NEXT review's `by_skill_sha` split: the new version against the prior one on
  the same stratum. Do not amend the same stratum again until the new version has ≥ 10 graded calls in it
  (`claude_calibration.MIN_N`), or the effect of the first amendment is unmeasurable.

`INDETERMINATE` strata do not amend a brief: they end in an `accruing` note naming what n would answer them.
A `PROPOSE_WIDEN` / `ELIGIBLE_TO_PROPOSE` is not a brief change: it is a mandate-scope proposal for the
operator (`docs/plans/ml-claude-distillation-DESIGN.md` § 3.7 rules (a) and (b)). The weekly audit (C13)
fails any contract version that has no `AMENDMENTS.md` line with an `n=`.

**Output: a strengths/weaknesses list of the SYSTEM**, not of individual trades. Each
lesson is one row with: `id` (`L1…`), `kind: strength | weakness`, `claim` (one sentence),
`evidence` (**trade ids / order_package_ids / record paths** — a lesson with no cited id
is dropped), `population`, `confidence ∈ measured | suggestive | anecdote`, and its
**ending** (queue unit / pipeline id / checklist row / `no action, because …`).

- A *weakness* normally ends in a queue unit (is it real, does a fix beat the pre-registered
  bar?) or a checklist row (it is a bug).
- A *strength* ends in Track 3 (where else does it apply?) or `no action, because it is
  already in the roster/config at <path>`.
- `anecdote` confidence (n too small to say anything) ends in an `accruing` unit that states
  what data would answer it, or an honest `no action, because n=<k> cannot support a claim`.
  Do not manufacture a verdict from a thin cell.

### Track 3 — EXTRAPOLATE: where else does the lesson apply?

*Operator point 3.* For every lesson that survived Track 2 with confidence ≥ `suggestive`:

1. **Other legs:** enumerate the legs the same mechanism could touch (same symbol family,
   timeframe, entry family, or exit class — read `config/accounts.yaml` /
   `config/strategies.yaml`, don't recall them). One unit that sweeps the set beats N
   one-leg units, but only if its power declaration is honest for the *smallest* leg.
2. **New strategies:** if the lesson implies a hypothesis no leg tests (a new entry
   filter, a regime-conditional exit, a market-neutral pair, a new instrument class),
   file it as a Stage-0 unit under theme `new_strategy_prop`, citing the lesson id. A
   new-strategy hypothesis is a *question*; building it is a separate row filed only if
   the unit passes.
3. **Frontier (strategies, weekly):** don't only extrapolate from our own trades — run the
   strategy half of `.claude/skills/frontier-research/SKILL.md` § "Strategy frontier": scan
   quant literature, open-source quant repos and new market-structure research for a mechanism
   with an economic reason to exist, diff it against `config/strategies.yaml`'s gaps, and file
   ≤ 3 Stage-0 units per week by the same rule (existing harness whose cost stack is complete,
   else a lever row; placebo/shared-beta control where the mechanism could be plain beta).
   The 2026-10-11 first scan is the worked example (`docs/research/frontier-scan-2026-10-11.md`
   § 5). Operator, 2026-10-11: same mandate as ML — don't keep the first good thing.
4. **Structural:** if the lesson is a tooling/methodology gap affecting several legs, file
   the tooling fix as a checklist row (the "pattern of demote proposals is the tell"
   rule in performance-review).

### Track 4 — PORTFOLIO: research that ties back to net P&L

*Operator point 4.* Use the artifacts the review already produced — the
`real_money_allocation_benchmark` and the `paper_book_tracker` — plus Track 2's
co-movement cut. Questions to cover (each answered with a number or filed as a unit):

- **Correlation and overlap** between legs (trade-level overlap, daily-P&L correlation,
  co-drawdown); legs that are the same bet twice.
- **Concentration** by symbol, side and regime — what fraction of risk/PnL rides on one
  cell.
- **Allocation and sizing vs contribution** — risk budget share against net-of-cost P&L
  share per leg, in R, not raw $ (paper notionals aren't comparable).
- **Drawdown clustering** — do the account's drawdowns trace to a few legs/regimes?
- **Removals and additions** — which leg removal or addition would have improved window
  and trailing net P&L? Use the mirror rule (Stage 2 live = mirror; strict equality tests
  in `tests/test_paper_portfolio_accounts.py`) when reasoning about roster changes.

Output is one of:
- a **queue unit** (portfolio replay/optimisation over committed trade records, decision
  rule registered first), or
- a **Tier-3 proposal with evidence** — a pipeline item with `next_action: ask_operator`
  carrying `{scope, current_value, proposed_value, evidence (ids), risk_note, tier: 3}`
  in the `proposed_tweaks[]` shape. **Proposals are never applied here.** Check
  `scripts/ops/mandate_resolver.py` / `config/mandates.yaml` first: a change a granted
  mandate already covers is a mandate firing for the manager, not a popup; a case where
  data is missing is a `NEEDS_DATA` research unit, not a question to the operator
  (manager skill § "classify the decision").

**ML-shaped lessons go in the ML plan.** A lesson or extrapolation whose answer needs a model,
a feature, a label source or a regime/gate head (not a strategy parameter) is filed as a queue
unit **and** added as an item under track N/R/X of `docs/plans/ml-plan-items.yaml` (the unit id
or lever row as its `ref`), so the weekly ML plan loop (`ml-review` § "The ML plan loop") sees it.

## Filing a queue unit (valid and auto-dispatchable)

1. Read `research/queue/README.md` (fields, power gate, `decision_rule`, scheduling), look
   at a template in `research/templates/` and a sibling unit, and use
   `scripts/research/research_queue.py` to validate.
2. Mint the id: `python3 scripts/research/next_rq_id.py --fetch` (never hand-pick).
3. Required: `title`, `question` (asked BEFORE the run), `status: queued`, `cadence: once`,
   `theme` + `priority` (a key of `research/THEMES.yaml`), `kind`, `power` with
   `feasibility` (or `why_not_inferential` for `deterministic`), `routing`, `run`, `lands`.
4. **`decision_rule` — registered BEFORE the run, net of the full cost stack** (CI:
   `check_research_queue_decision_rule.py` refuses a new unit without an admissible one):
   `id`, `registered_at` (today), `registered_before_run: true`, `statistic`, `rule`
   covering **every** branch (PASS / FAIL / underpowered / null), and
   `what_it_does_not_do` (a PASS is a Tier-3 proposal, never an applied change).
   Never write or edit the rule after seeing a result.
5. **Make it dispatchable when the instrument exists:** `run.workflow:
   research-script-run.yml` with `run.command: [python3, scripts/research/<script>.py, …,
   --out, '{out_dir}']`; the script writes `verdict.json`; `lands.store: research/results/`,
   `assert_field: read_state`, `min_rows: 1`. Opt into mechanical grading with
   `grading: {auto: true}` when the rule is computable from `verdict.json`.
6. **If the instrument does not exist**, do not invent a workflow name. Either (a) file the
   missing instrument as a checklist row and put the pre-registered question in
   `research/queue/blocked/<id>.yaml` with `blocked_on` and `clears_when`, or (b) if the
   run genuinely needs a session (live-data pulls), declare it session-bound and pipeline
   the pickup. Say which in the record — session-bound units count as debt
   (`PI-20261006-LCEVL8D5-0002`), so prefer (a)/dispatchable.
7. A **new** hand-written unit holds for a human to merge (E57) — that is expected; the
   PR landing declaration says so.

## The run record (the ledger)

Write `comms/perf_followup/perf-followup-<review-stamp>.json` (create the directory; one
file per run; never rewrite earlier ones):

```json
{
  "run_at": "<iso>", "reviewer": "claude (perf-followup)", "session": "<id>",
  "review": "comms/reviews/performance-review-<stamp>.json", "window": ["<iso>","<iso>"],
  "previous_run": {"record": "<path>|null", "units_total": 0, "ran_and_read": 0,
                   "ran_unread": 0, "not_run": 0, "underpowered": 0, "killed": 0, "actions": []},
  "tune":        [{"leg": "", "cause": "regime|cost|execution|overfit", "retest_ref": "", "ends_in": "RQ-…|PI-…|row|no action, because …"}],
  "lessons":     [{"id": "L1", "kind": "strength|weakness", "claim": "", "evidence": ["trade:…","op:…"],
                   "population": "", "confidence": "measured|suggestive|anecdote", "ends_in": "…"}],
  "extrapolate": [{"lesson": "L1", "applies_to": ["leg…"], "new_hypothesis": "", "ends_in": "…"}],
  "portfolio":   [{"question": "", "finding": "", "ends_in": "RQ-…|PI-… (tier-3 proposal)|no action, because …"}],
  "queue_units": ["RQ-…"], "pipeline_items": ["PI-…"], "checklist_rows": ["…"],
  "cost_usd": 0.0, "done": {"every_entry_ends": true, "previous_run_closed": true}
}
```

**Validity check before you commit** (run it; a record that fails is a memo):

```bash
python3 - <<'PY'
import json,sys,glob
p=sorted(glob.glob("comms/perf_followup/perf-followup-*.json"))[-1]; d=json.load(open(p)); bad=[]
for sec in ("tune","lessons","extrapolate","portfolio"):
    for e in d.get(sec,[]):
        end=str(e.get("ends_in","")).strip()
        if not end or end.lower().startswith("no action") and "because" not in end.lower(): bad.append((sec,e))
for e in d.get("lessons",[]):
    if not e.get("evidence"): bad.append(("lesson-no-evidence",e.get("id")))
print(p,"BAD:" if bad else "OK",bad); sys.exit(1 if bad else 0)
PY
```

## Bounded cost

- **Model: Sonnet** (`claude-sonnet-5`). Opus only if the manager says a Track 4 proposal
  touches a real-money order-path judgment call. Never Fable here.
- **Ceiling: $6 per run**, recorded on the lane's checklist row (`ceiling_usd`). At ~$4.50
  stop opening new analyses: finish the record, file what you have as units/pipeline items,
  and run `close-out`. Stopping early is a handoff, not a failure — but a silent stop is a
  drop; list what is unfinished as a pipeline item with `due_when` and `origin.rerun`.
- Read narrowly: grep/jq single fields; don't dump 200-row pulls into context. Do heavy
  numeric work in scripts under the scratchpad that read the pulled JSON, not in the
  context window. Don't spawn sub-lanes; this is one question ("what does this review
  imply?") per lane.
- **Caps that keep the output reviewable:** ≤ 8 new queue units per run (rank by money at
  stake: real-money and prop first, then mirrors, then paper — the TP-doctrine ordering);
  overflow is a ranked pipeline item, not dropped.

## What "done" means for a run

All of these, or the run is a handoff:

1. Step 0 complete — every previous-run unit classified and `ran_unread = 0`.
2. All four tracks addressed (an empty track states why — e.g. "no leg underperformed in
   the window, n=<k> trades" — and still shows the evidence).
3. The record validates (every entry ends in an id or an explicit `no action, because`;
   every lesson cites ids).
4. Every filed unit passes `research_queue.py` validation and the decision-rule guard; every
   build has a checklist row; every Tier-3 proposal is a pipeline item with evidence.
5. Record + units + rows are on `main` (PR merged, or HELD with the blocker stated and
   filed) — **merged ≠ deployed ≠ observed; say which** — and the lane's checklist row
   states the run's counts. Then `close-out`.

## Landing

Docs/research-queue/pipeline files only → Tier 1, self-land per
`.claude/skills/manager/SKILL.md` § "How lane PRs land". New hand-written queue units hold
for a human merge (E57); put the record, pipeline items and rows in a separate Tier-1 PR
if that keeps them from waiting. **You change no `config/` or `src/` file** — param,
roster, risk and mode changes are Tier-3 proposals.

## Out of scope

- Grading decisions or appending to `comms/claude_strategy_scores.jsonl` (`/performance-review`).
- Running the sweeps yourself on a long horizon — you register and (where the instrument
  exists) the dispatcher fires; you read results next run.
- System health (`/health-review`), model lifecycle (`/ml-review`).
- Placing orders, ever.
