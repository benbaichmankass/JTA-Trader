---
name: frontier-research
description: The WEEKLY frontier scan — look OUTSIDE the repo for better models, methods and strategy ideas than the ones we happened to pick first, triage them against our data/compute/latency/leakage constraints, and turn every kept idea into a pre-registered research/queue unit (or a checklist lever row) with a declared baseline it must beat net of cost. Also owns the model-FAMILY diversity check (ml_plan_status.py --diversity) that stops capacity piling onto one family. Use when the manager dispatches a FRONTIER-SCAN-<week> lane, when /ml-review reaches step 9 (the ML plan loop), when perf-followup runs Track 3, or the operator says "scan for better models", "what's new in open-source time-series / tabular models", "are we stuck on one model family". NOT for tuning an existing model (model-training / perf-followup Track 1) and NOT for grading results (research-ops).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-11` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /frontier-research — stay on top of what is out there, test it, apply it

> **Operator, 2026-10-11 (voice, paraphrased closely):** the ML research mandate must not be limited to
> new training runs, datasets or variations of models we already chose. Do deep research on **better
> models**. There is a vast and growing set of open-source models, methods and resources, with new
> developments all the time; we must stay on top of them, test whether they are relevant, and apply
> them. *Don't let early, somewhat arbitrary choices dictate the scope and potential of the project;
> don't lazily keep the first good thing; don't spend capacity on 100 variations of the same model
> that isn't going anywhere. Use our capacity wisely to test genuinely different things.* Same for
> strategies, but especially for ML. **A recurring part of the workflow, alongside the work already
> under way (which continues).**

## The one hard rule

**A scan produces units, not prose.** Every idea you keep becomes a `research/queue/` unit with a
decision rule registered **before** any run (or, when its instrument is missing, a checklist *lever
row* plus the unit in `research/queue/blocked/` naming it). Every idea you drop is dropped **with a
stated reason in the run record**. A shortlist with no unit behind it is a memo, and this repo has 404.
The first scan's output is the worked example:
[`docs/research/frontier-scan-2026-10-11.md`](../../../docs/research/frontier-scan-2026-10-11.md).

## Cadence and who runs it

Weekly. The manager dispatches one `FRONTIER-SCAN-<YYYY-MM-DD>` lane (Sonnet, ceiling ~$8) the same
day as the Sunday `/ml-review`; `ml-review` § "The ML plan loop" step 4 *consumes* its output (ideas →
the plan's track N) and `perf-followup` Track 3 runs the **strategy half** of this skill (§ "Strategy
frontier" below). No new cron: the manager binds it to the weekly routine it already runs. A run that
finds nothing writes "none, because" with the sources it checked — silence is the failure.

## Step 0 — close the loop on the previous scan (always first)

Read the last `comms/ml-plan/*.json` `frontier` block. For each idea it filed: has the unit run? read
its verdict (research-ops grades them). Append the graded verdict (`PASS`/`FAIL`/`INDETERMINATE`) to
`docs/plans/ml-plan-items.yaml` `families.<family>.history`. **A FAIL closes only the exact
configuration tested** (checkpoint, input, target, horizon) — write down what was and was NOT tested
before moving the family's status. The frozen-TSFM result is the cautionary case: Chronos-Bolt-Tiny,
frozen, on a 4.6%-base-rate volatility label closed *that*, not "time-series foundation models".

## Step 1 — measure where we are concentrated

```
python3 scripts/ops/ml_plan_status.py --diversity
```

Prints, per model **family** (gbdt · linear_logit · deep_sequence · ts_foundation_model ·
tabular_foundation_model · rl_bandit · bayesian_probabilistic · conformal_calibration ·
ssl_representation · ensemble_stack · rule_baseline): registered models, live/shadow count, open
family-tagged plan items, and graded history. Findings:

- `CONCENTRATION` — more than `diversity.max_family_share` (60%) of open family-tagged plan items in one family;
- `FAIL-STREAK` — a family whose last `diversity.max_fail_streak` (3) graded units all FAILed and that
  is **still getting new units** → retire the line by its registered exhaustion rule, or change the *kind* of lever;
- `MANIFEST-CONCENTRATION` — reported, not failed: the registry predates this scan (2026-10-11
  measurement: 75 of 96 registered models, 78%, are `gbdt`).

A family with **0 models and 0 open items** is not "not promising" — it is *untested*. Those are where
the scan looks first. (Note: a TSFM used as a frozen *feature extractor* inside a GBDT head, like
`fc_*`, counts as `gbdt` here; tag the plan item `ts_foundation_model` when the experiment is about
the TSFM.) Every new plan item names its `family:`.

## Step 2 — scan the sources (time-box ~2h; record which you actually checked)

| source | how | look for |
|---|---|---|
| Hugging Face Hub | the Hugging Face MCP tools (`hf_fs ls hf://models/trending`, `search hf://models <q>`, `hf_fs ls hf://papers/trending`, `hub_repo_details` for licence/params/date) | new/updated time-series, tabular, finance models; **read the licence field on the Hub, not the blog** |
| arXiv | WebSearch; `q-fin.TR`, `q-fin.CP`, `q-fin.ST`, `cs.LG` time-series / tabular / conformal / offline-RL | methods with code AND a leakage-safe evaluation |
| GitHub | WebSearch / trending for `time-series`, `quant`, `tabular`; repo licence + last commit | maintained implementations, not demos |
| Lab releases | WebSearch: Amazon (Chronos), Google (TimesFM), Salesforce (Moirai), NX-AI (TiRex), Datadog (Toto), IBM (TTM), Prior Labs (TabPFN), Tsinghua/Kronos | version bumps; benchmark (GIFT-Eval / fev-bench) claims are **self-reported** until replicated |
| Competitions / write-ups | WebSearch: Kaggle finance & time-series winners, M-competition style reports | what actually beat GBDT, and on what data size |
| Quant practitioner literature | WebSearch: SSRN / practitioner blogs / open quant repos | strategy mechanisms with an economic reason to exist |

Every claim you carry forward cites a URL and says whether it is **primary** (paper/model card) or
**secondary** (blog). Benchmark rank from a vendor blog is a rumour, not a finding (the first scan
found a "TimesFM 3.0" claim it could not confirm — it was dropped, not carried).

## Step 3 — triage each candidate (four gates, all answered in writing)

1. **Data** — do we have the input it needs, point-in-time? (OHLCV yes; order-book/liquidation streams
   mostly no — Binance's liquidation snapshot dump is discontinued; label count is the usual binding
   constraint: ~99 closed BTC trades.)
2. **Compute** — fits the trainer VM (CPU/ARM, disk 43.8% of ~104 GB on 2026-10-11)? GPU burst needed?
3. **Latency / serving** — can it run at the live tick? Our pattern is *mirror-publish*: compute on the
   trainer, ship the artifact, **zero torch on the money box**. A model that cannot be served that way
   is research-only.
4. **Leakage and licence** — pretraining overlap with our test window (a finance-pretrained model has
   seen crypto candles — hold out bars **after** its release); label leakage; and the **licence**: a
   non-commercial weight (`cc-by-nc`, Prior Labs TabPFN-2.5/3 `license:other`) may be used for offline
   research evaluation but **serving it live is an operator licence decision**, never a default.

A candidate that fails a gate is dropped with the gate named. A candidate that passes all four and
whose family is already crowded (Step 1) needs a *genuinely different* hypothesis than the unit it
would join — "the same head with checkpoint #5" is a variation, not a test.

## Step 4 — rank and keep ≤ 5

Rank by **expected information per dollar**, not expected P&L: (does it test a family we have never
tried) × (does it attack the binding constraint — labels, base rate, serve-parity) ÷ (cost to try).
Write the shortlist (top ~8; what / licence / fits which problem / why it could beat the current head /
cost to try / **kill criterion**) into `docs/research/frontier-scan-<date>.md`. Keep the top 3–5.

## Step 5 — every kept idea becomes a unit (never a memo)

Follow `perf-followup` § "Filing a queue unit": mint the id with `python3
scripts/research/next_rq_id.py --fetch`; required fields; **`decision_rule` registered before the run**
with every branch (PASS / FAIL / underpowered) and a **declared baseline it must beat NET of the full
cost stack** (a feature-lift gate says so explicitly and routes any live use through the downstream
net-of-cost walk-forward — feature lift is not edge); `what_it_does_not_do`. If the instrument does not
exist: a checklist **lever row** (`scripts/ops/checklist.py add FRONTIER-LEVER-<X>`) with the
observation that closes it + the unit in `research/queue/blocked/` with `blocked_on`/`clears_when`. A
new hand-written unit lands in a hold PR (E57). Add the plan item to `docs/plans/ml-plan-items.yaml`
**with `family:`**; run `python3 scripts/ops/ml_plan_status.py --diversity` and
`ml_plan_status.py` before pushing.

⚠️ **Lever rows are the failure mode of this scheme** — blocked units can sit forever. The weekly run
re-reads the lever rows it filed; one still `queued` after two scans is raised to the manager as the
blocker, not re-filed.

## Strategy frontier (the lighter half — run by `perf-followup` Track 3, or here when no review ran)

Same loop, narrower inputs: **(a)** quant literature and open-source quant repos for a *mechanism with
an economic reason to exist* (risk premium, forced flow, structural constraint); **(b)** new
market-structure research (funding/basis, liquidation dynamics, venue changes); **(c)** the
gap list — which entry/exit/sizing families does `config/strategies.yaml` NOT contain? Each kept idea
is a Stage-0 `new_strategy_prop` unit on an **existing dispatchable harness** where one exists (check
the harness's cost stack against CLAUDE.md's list of harnesses still lacking one — a unit on a
fee-only harness is blocked on a cost lever row, not run), with the same decision rule shape and a
placebo/shared-beta control where the mechanism could be plain beta. Keep ≤ 3 per week.

## The run record

Add to the ml-review record `comms/ml-plan/<stamp>.json` a `frontier` block:

```json
{"frontier": {
  "run": "<session>", "finished_at": "...",
  "previous_scan_read": [{"unit": "RQ-…", "verdict": "PASS|FAIL|INDETERMINATE|not-run", "family": "…"}],
  "diversity": {"command": "ml_plan_status.py --diversity", "findings": ["…"]},
  "sources_checked": [{"source": "hf-trending-models", "date": "…", "note": "…"}],
  "candidates": [{"name": "…", "family": "…", "licence": "…(primary|secondary)", "gate_failed": "data|compute|latency|leakage|licence|none", "kept": true, "unit_or_row": "RQ-…|ROW", "baseline": "…", "kill": "…"}],
  "strategy_ideas": [{"name": "…", "unit_or_row": "…"}],
  "none_because": null}}
```

so next week's Step 0 reads exactly what this one found.

## Hard limits

Never promotes a model, edits `config/strategies.yaml` / `config/accounts.yaml` / `ml/configs/*.yaml`,
places an order, or creates a cron/trigger. Never uses a non-commercial weight in anything that serves
live. Never reads a vendor-blog benchmark as a result. Never kills a *family* on one configuration.
Spend: web/HF reads only — training and backtest runs are the units' job, dispatched by research-ops.
