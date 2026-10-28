---
name: programme-review
description: The WEEKLY research programme review (routine "Weekly research programme review", Wed 19:29Z, one Opus lane). Reads the research map, every programme plan (research/programmes/*.yaml + docs/research/programmes/*.md) and every result graded in the week; runs in two layers -- a script-computed CHECKS packet (scripts/research/research_ops_checks.py --kind programme_review --since 7d) and an ANALYSIS per programme and per track (TRADING / MODEL) -- then updates each plan (learned; questions answered / unlocked / retired; the next 3-4 weeks of pre-registered units, value-ranked; cross-programme and cross-track feeds), turns needs_authoring nodes into unit specs, grades last week's calls, and lands one HELD PR for the manager's merge. Feeds Thursday planning. Use when the routine fires, the manager dispatches a PROGRAMME-REVIEW-<date> lane, or the operator says "review the research programmes". NOT the 4x/day pipeline pass (research-ops), NOT the external scan (frontier-research), NOT closed-trade grading (performance-review).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /programme-review — what this week's research means, and what we ask next

**Why this file exists.** Until 2026-10-28 the procedure lived only in the routine's prompt (lane SKILL-DESIGN-RESEARCH
found no repo copy). **Operator, 2026-10-28 (paraphrased by the manager, binding):** recurring reviews are redesigned on
researched practice — neither **too loose** (skims, no deep analysis) nor **too scripted** (restates the numbers it was
fed); reason over wide context inside a fixed format that guarantees the checks; research is **two tracks, TRADING** (how
to trade better) and **MODEL** (how to build a better AI trader model). Diagnosis of the previous runs and sources:
[`docs/research/research-ops-redesign-2026-10-28.md`](../../../docs/research/research-ops-redesign-2026-10-28.md); shared
pattern `docs/reference/llm-analyst-skill-design.md`.

**Scope.** One lane per week, Opus, ceiling set by the manager on the checklist row. Tier 1. The deliverable is the plans
moving, not a report: edits to `research/programmes/<NN>-*.yaml` and the "Programme review <date>" section of each
`docs/research/programmes/<NN>-*.md`, plus one record. **Programme-tree edits HOLD for the manager's merge** (E57 queue
machinery); never self-land them. Never edit `config/*`, `THEMES.yaml` or a unit's registered rule.

**The programmes** (`research/programmes/`): P1 active trade management · P2 AI trader · P3 strategy improvement ·
P4 macro sleeve · P5 prop · P6 data infra · P7 timeframes. **Tracks:** MODEL = P2, P6 and any unit with an `ml_bakeoff:`
block or theme `ml_health`; INFRA = theme `infra`; everything else TRADING (`research_ops_checks.track`).

## Step 0 — read

`docs/research/programmes/RESEARCH-MAP.md`; each plan's last "Programme review" section; the last review record
`comms/research/programme_review/*.json` (newest); this week's research-ops records `comms/research/ops/*.json`; the
latest `/perf-followup` and `/ml-review` records if they landed this week; `research/queue/PLANNING.md` § 1 (authoring
rules, binding). Read the plans **in full** — wide context is the point of this lane.

## Step 1 — CHECKS (computed; read, do not recompute)

```bash
python3 scripts/research/research_ops_checks.py --kind programme_review --since 7d --records 28 --out /tmp/checks.json
python3 scripts/research/programme_coverage.py              # plan questions with no node
python3 scripts/research/queue_replenish.py --programme-state   # node states: answered / ready / moot / needs_authoring
python3 scripts/research/queue_replenish.py --authoring-queue   # ready needs_authoring nodes, ranked
python3 scripts/research/trial_ledger.py --real-money-table     # configs tried per real-money leg (report-only)
```
Population line goes at the top of the record and of each plan section: units graded in the window, how many carry a
programme field, how many do not (the 2026-10-21 review left 486 of 657 out of every plan — **this review assigns each
unprogrammed cluster to a programme** in its analysis, by what it asks, not by the field).

## Step 2 — ANALYSIS (the lane's real work; at least two thirds of the budget)

Fixed questions, open answers. Do them in this order.

0. **Follow-through first (2026-10-28):** run `python3 scripts/ops/review_followthrough.py --source programme-review --window-days 7` and record its cohort and backlog line before grading calls; an open item older than 14 d with no owner is a call to schedule or kill, not to re-file.
1. **Grade last week's calls** (`previous_calls`): each prediction → hit / miss / not yet, with why. Then one line: what
   did last week's ranking get wrong (a top-ranked test that turned out uninformative, a low-ranked one that mattered)?
2. **Per programme, then per track — what was learned.** Read result rows for every PASS and for the largest FAIL
   clusters (arms, folds, n, cost basis), not titles. Write beliefs, not counts: "momentum-keyed exits help on 4h trend
   legs and not on 2h pullback legs (6 of 8 cells, 2 batches)". Every PASS carries its batch denominator (`batches`) and
   stays a discovery until its confirmation unit passes. Power: `accruing` is a non-signal; compare realised n with the
   unit's `power.expected_n` and say when you could not.
3. **Failed first tests — diagnosis, never retirement by one test.** For every FAIL cluster (start with
   `fails_without_next`): the likely cause among {design, power / n, cost drag, regime / window, harness, idea}, the
   evidence, and the variant that tests the diagnosis. A family is retired only through
   `scripts/research/family_retirement_policy.yaml` + a review record (`research/family_reviews/`).
4. **Questions answered / unlocked / retired** — per plan, with the unit ids. Retirement needs a stated reason
   (superseded, moot, answered elsewhere); a first-test FAIL is never one on its own.
5. **The next 3–4 weeks, value-ranked.** Per programme, 3–6 pre-registered questions. Each states the **decision it
   changes**, what we do on PASS and on FAIL, its cost (compute class, est. minutes) and a one-line **pre-mortem** ("if
   this FAILs, the most likely reason is … ", which is also the first variant). A test whose two branches lead to the
   same action is not proposed. Balance the tracks: if `runnable_by_track` shows a track thin, say whether that is a
   supply gap (author) or a build gap (name the row).
6. **Cross-programme and cross-track feeds.** Update the map's feed table: TRADING → MODEL (validated levers and legs
   become labels / features / negative classes for P2), MODEL → TRADING (a head that cannot beat the prior is not a gate;
   one that can is a Tier-3 candidate), P1 ↔ P5, P3 → P1 (exit-process every new leg), P6 → everyone. Each feed names
   its destination node, unit or row and its state.
7. **Calls for next week.** 3–6 falsifiable predictions with probabilities, at least one per track, each with a
   pre-registered check (`command`, `rule`, `resolves_when`).

The shared ANALYSIS prompts (read wide, compete hypotheses with *noise* always one, judge the residual, count
comparisons, hunt surprises, premortem, neutral framing, no quota) bind every step above:
`docs/reference/llm-analyst-skill-design.md` § 3. Pointed at, not restated.

## Step 3 — ACT

- **Edit the trees.** In `research/programmes/<NN>-*.yaml`: add nodes for new questions (a `needs_authoring:` line is
  enough to make a plan question visible), move answered nodes, and **turn every ready `needs_authoring:` node you ranked
  into a full pre-registered `unit:` body** (research-ops step E.0 rules: `decision_rule` with
  `registered_before_run: true`, `theme`, `priority`, `compute:` + `routing:`, a `value:` block, `what_it_does_not_do`;
  mint ids with `python3 scripts/research/next_rq_id.py --fetch`). Cap ~15 nodes; the rest go to the record's handoff
  ranked, for research-ops.
- **Write the plan sections.** Each `docs/research/programmes/<NN>-*.md` gets "## Programme review <date>" at the top
  of the review history: population, learned, answered / unlocked / retired, next 3–4 weeks (the ranked table), feeds.
  The map gets its own section with the feed table and the two-track summary. Prose that reasons; no numbers that
  only repeat the packet.
- **File builds**, not units, for questions whose instrument does not exist (checklist row via
  `scripts/ops/checklist.py add`, or a pipeline item) — once, after searching for a twin.

## Step 4 — RECORD and LAND

`comms/research/programme_review/<YYYYMMDD>.json` (newest file = next week's `previous_calls`), with the shared
pattern's four top-level blocks (`docs/reference/llm-analyst-skill-design.md` § 4; reference shape
`comms/schema/performance_review_response.template.json`) plus this skill's own fields:
```json
{"run": "PROGRAMME-REVIEW-2026-10-28", "finished_at": "...", "by": "<session id>", "population": "...",
 "prior_calls_scorecard": [{"call": "...", "p": 0.4, "check_rerun": "<command>", "outcome": "hit|miss|unresolved|void",
                            "action_happened": true}],
 "checks": {"graded_by_window": {}, "runnable_by_track": {}, "fails_without_next": 0, "batches_quoted": [], "could_not_look": []},
 "analysis": {"ranking_error": "...",
              "programmes": {"P1": {"learned": [], "fail_diagnoses": [], "answered": [], "retired": [],
                                    "next": [{"node_or_unit": "...", "decision_changed": "...", "on_pass": "...",
                                              "on_fail": "...", "cost": "...", "premortem": "..."}]}},
              "tracks": {"TRADING": "three sentences: where trading research stands", "MODEL": "same"},
              "feeds": [{"from": "P1", "to": "P2", "what": "...", "dest": "node/unit/row", "state": "..."}],
              "surprises": []},
 "calls": [{"call": "...", "p": 0.4, "track": "MODEL",
            "check": {"command": "...", "rule": "...", "resolves_when": "2026-11-04"}}],
 "nodes_authored": [], "nodes_added": [], "rows_filed": [], "not_run": [], "handoff": []}
```
**Quality bar** (the manager reads this before merging): every `learned` line is a belief with its evidence and
denominator; every FAIL cluster has a diagnosis or is in `not_run`; every `next` row names a decision; last week's calls
are graded. A review whose `analysis` restates counts is **too scripted** and goes back; one with no packet is **too loose**.

One PR: the trees, the plan sections, the map, the record. `.github/pr-landing/<slug>.json` declares `tier: 1`,
`landing: "hold"`, `hold_reason: "changes_landing_machinery"` -- `research/programmes/**` is on `check_pr_landing.py`'s
landing-machinery list (a node's `unit:` is a pre-registration the replenisher emits), so the guard verifies that
reason against the diff. Guards before push:
`python3 scripts/ci/run_guards.py` (at least `check_research_queue_decision_rule.py`, `programme-coverage`,
`family-retirement-guard`, `canonical-doc-coherence`) and `python3 scripts/ci/check_pr_landing.py --base origin/main`.
Report to the manager in one line: calls graded (hit/miss), nodes authored, the top next test per track, PR number.

## What this skill never does

Never edits config, weights or a registered rule; never retires a family on one FAIL; never self-lands a tree edit;
never proposes a test without the decision it changes; never ends without grading last week's calls.
