---
name: weekly-audit
description: The WEEKLY system audit, run Mondays 06:07Z by one Opus lane (trigger "Weekly audit (Monday): core + rotating deep pass"). A COMPLETION TEST, not a memo — a CORE pass every week (behaviour invariants on live data, TP-doctrine compliance, live = mirror, full cost stack on promotable results, stated populations, overdue items, spend vs plan, health review #2, RECURRENCE) plus a ROTATING deep pass chosen by ISO week mod 4 (0 OUTCOME+INDEPENDENCE, 1 CONSISTENCY+LIVENESS, 2 MODULARITY, 3 DESIGN CRITICISM). Ends in a one-page report in a self-landing PR, and every finding becomes a checklist row or pipeline item with a permanent detector. Use when the manager dispatches a WEEKLY-AUDIT-<date> lane, or the operator says "/weekly-audit", "run the weekly audit", "audit the system". It is the compact successor to the retired full-system-audit program. NOT a health review (Saturday, /health-review), NOT a performance review (Wednesday/Thursday), NOT a code review.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-15` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /weekly-audit — a completion test, not a memo

> **Operator, 2026-10-14 (weekly planning) and 2026-10-15 06:20Z ("Weekly audit skill (Rec.)").** The
> archived `full-system-audit` program (7 axes + axis 0, multi-session, 694 lines) is merged with the
> operator's weekly checks into **one weekly lane**: a core that runs every week and a deep pass that
> rotates, so every axis is covered once a month without any single run being a program. Row
> `WEEKLY-AUDIT-SKILL`. Source axes:
> [`docs/archive/2026-09-21-operating-reset/skills/full-system-audit/SKILL.md`](../../../docs/archive/2026-09-21-operating-reset/skills/full-system-audit/SKILL.md)
> (read § "READ THIS FIRST" once — it is the design input).

## Why this audit exists in this shape

The old audit returned clean on a system that was broken, because it asked the system to **describe
itself** (`/api/diag/services` says `active`; `protection_coverage` said `covered` for a stop-only
position — MGC sat 122.74 points past its target for 11 days across two clean audits). So:

1. **Audit outcomes, not descriptions.** Use the least-reduced surface (order ROWS, position ROWS,
   journal rows) and recompute the verdict yourself. A verdict nothing outside its producer can falsify
   is the finding.
2. **A fix without a detector is a fix that will be found again.** Every finding closes with a permanent
   detector or an explicit "no detector possible because X".
3. **It is a completion test.** The audit is not done when you have written prose; it is done when
   `§ Completion test` below passes. Prose that no row points at is a memo, and this repo has 404.

## Mechanics

| | |
|---|---|
| Who | one Opus lane, ceiling ~$8 (the dispatching row states the ceiling) |
| When | Monday 06:07Z; row `WEEKLY-AUDIT-<YYYY-MM-DD>` (create it at start, state `in_flight`, owner = your session) |
| Branch / slug | `claude/weekly-audit-<YYYY-MM-DD>` |
| Output | **one** file, `docs/reviews/<date>-weekly-audit.md`, **one page** (§ Report), landed in **one self-landing PR** |
| Reads | live data through `diag-data` relays (never ask the operator for a snapshot); `credentials`/VM mutation are out of scope — this audit is **read-only on the fleet** |
| Writes | checklist rows (`scripts/ops/checklist.py add|set|note`), pipeline items (`scripts/ops/pipeline.py` API), research units, the report. **No config, no order path, no Tier-2/3 change** — those are filed as proposals |

**Pick the deep pass first:** `python3 -c "import datetime as d;print(d.date.today().isocalendar()[1] % 4)"`
(use the Monday's date). `0` OUTCOME + INDEPENDENCE · `1` CONSISTENCY + LIVENESS · `2` MODULARITY ·
`3` DESIGN CRITICISM. (2026-10-19 = ISO week 43 → `3`; then 10-26 → 0, 11-02 → 1, 11-09 → 2.) If the
operator or the manager names a different deep pass in the dispatch, use theirs and say so in the report.

**Budget the close-out first** (`close-out` skill): reserve enough to land the PR. Running out
mid-audit is a HANDOFF — say so in the report and file what you did not reach (§ Coverage).

## Step 0 — make the instruments trustworthy (always first, ~10% of the run)

- `git fetch --deepen=2000 origin` if the clone is shallow (the SessionStart hook says so) — the
  history rule does not hold on a truncated clone.
- Run the instruments' own self-tests before trusting a green from them:
  `python3 scripts/ops/system_invariants.py --self-test`, `python3 scripts/ci/guard_selftests.py --all`,
  `python3 scripts/ops/checklist.py --self-test`, `python3 scripts/ops/pipeline.py --self-test`.
  A failing self-test is finding #1 and the reading it would have produced is **not_measured**.
- **Positive control on every negative.** Before reporting "0 violations", show the same probe returns a
  known positive (a planted fixture, or a prior-week finding that should still reproduce).
- **Last audit.** Read the previous `docs/reviews/*-weekly-audit.md` and its rows: which are still open?
  That list is the first thing the RECURRENCE step below must disposition.

## CORE — every week, in this order (blast radius, not convenience)

Never spend the first half of the run on the cheap checks. A naked live position and a doc-drift
finding are not the same finding.

### C1. Behaviour invariants on live data (the money-at-risk pass)

Assert on rows, not on summaries. Pull the payloads through the diag relays and feed
`scripts/ops/system_invariants.py --payloads <dir>` (stems: `ib_open_orders`, `bybit_open_orders`,
`exchange_positions`, `positions`, `journal_trades`, `exit_loop_health`). Standing invariants (extend,
never shrink):

| invariant | fail means |
|---|---|
| **Two-sided protection sized right** on every open position: resting stop qty ≥ position qty **and** ≤ position qty (over-cover is its own hazard); a declared `take_profit_1` has a resting target or a recorded reason | naked / over-covered / target-less position |
| **Journal ⇄ exchange quantity reconcile**, netting-aware, per account + symbol | orphaned or phantom position |
| **Signal accounting closes**: every actionable signal in the window has an order package **or** a logged refusal with a cause | silent drop |
| **Every declared-live account placed or refused** in the window | silent-refusal class |
| **No aggregate mixes MEASURED with FABRICATED/ESTIMATED** without stating coverage (`src/runtime/provenance.py`) | fiction in a headline number |
| Any close that is not TP / SL / strategy-close (reconciler-driven, orphan) | bug to root-cause this week |

`not_measured` is not a pass: a payload you could not pull is reported as **could-not-look**, with the
reason, and filed (it is a liveness finding about the relay). One **full pipeline trace** per week
(rotating account × venue × strategy; at least one refused, one orphaned/prop, one paper, one
real-money over a month): walk signal → intent → sizing → placement → journal → protective legs →
monitor/exit → reconcile → close + P&L provenance → analytics, assert at each hop, and record **which
hop each trace died at**.

### C2. TP-doctrine compliance

`python3 scripts/ci/check_tp_doctrine.py` — **re-run, never quote last week's counts**. Report
compliant / non-compliant by money at stake (real-money & prop → mirrors → paper) with the denominator.
New non-compliant legs go to the exit-refinement queue as rows/units, ordered by money at stake.

### C3. Live = mirror (Stage 2 is one stage)

`tests/test_paper_portfolio_accounts.py` (roster equality: `test_bybit_portfolio_mirrors_bybit_2_exactly`,
`test_alpaca_portfolio_mirrors_alpaca_live_exactly_minus_proxies`) **and**
`test_mirror_trade_shaping_fields_equal_live` (every trade-shaping field). Run them; do not recall them.
A divergence is a Tier-3 finding: file the exact proposed change, do not edit the roster.

### C4. Full cost stack on every promotable result

For every Stage-0 evidence record or mandate fire since the last audit: the harness resolved slippage and
funding through `execution_costs.resolve_cost_policy()` (not a silent `0.0`; `scripts/backtest_orb.py` and
`src/backtest/backtester.py` are still out of corpus); the record names harness, n, and a rule registered
**before** the run. `python3 scripts/ci/check_cost_model_single_owner.py`. A fee-only record on a promotion
path is a finding.

### C5. Numbers that state no population

`python3 scripts/ci/check_stated_population.py` over the week's merged docs, plus your own read of the
last week's brief/reports: any quantitative claim with no population, window or cost basis is listed.
A figure whose sign flips on a filter choice is not a figure. Fix in place if Tier 1; otherwise a row.

### C6. Overdue items

`python3 scripts/ops/pipeline.py --due` (and `--stats`): every due item gets a disposition now — redate
**with an observation you actually read** (`--redate ID --observation … --next-due … --evidence …`),
done, or killed **with a stated reason**. Then the checklist: rows `in_flight` with no live lane (stale
`in_flight` routes the next session around free work), `landed_unproven` past its observation `due_by`,
`blocked_on` rows whose blocker has cleared. Report the unrouted count and its trend (`JC-SA-06`).

### C7. Spend vs plan

`python3 scripts/ops/spend_meter.py` against the weekly workplan on `WEEKLY-PLANNING` and each lane's
`ceiling_usd` / `spend_usd`. Name lanes over ceiling and ceilings with no spend recorded. Spend is
reported; **session length is never a metric.**

### C12. Lane utilisation vs target (operator, 2026-10-26)
The manager's REFILL step (manager SKILL.md § The operating loop) says running build lanes should
track the meter's *"KEEP N LANES RUNNING"* target while the queue is non-empty. Measure it over the
week: from `list_sessions(mine=true)` (lane start/end) and `spend_meter.py --capacity` readings, state
the population (lanes dispatched, queued rows at each reading) and the **hours below target while
`checklist.py queue` was non-empty**. Under-target hours with a non-empty queue and no recorded
operator preference is a finding (checklist row against the manager loop). If lane timing cannot be
read, say `not_observed` — never report full utilisation by default.

### C8. Health review #2

The Saturday `/health-review` is review #1. This is the Monday second look at the same plumbing after the
weekend: services, heartbeats, alert delivery, DB integrity, relay health — through the diag relays, using
`health-review` § checks as the list. Anything it found Saturday that is still open and unrowed is a finding
here; anything fixed is verified fixed (read the field, not the PR).

### C8b. Research pipeline health (operator, 2026-10-16)

Read the last 7 days of `comms/research/health/<date>.json` (written every 2 h by `research-slo.yml`; SLOs and
thresholds in `scripts/research/research_slo.yaml`). Report, per SLO: days red / 7, current value, and whether a
lane was dispatched the same day it went red (manager § "Research SLO escalation"). **Every breach and every
`could_not_look` in the window needs a disposition** — a fix merged, a checklist row or pipeline item with a near
`due_when`, or a reasoned threshold change in a PR. A missing day's file, or `runs` with gaps > 4 h, is itself a
finding (the monitor is a pipeline too). Positive control: `python3 scripts/research/research_slo.py --self-test`
(a planted starved queue must alert) — paste its line beside a "no breaches" verdict.

### C10. Off the trade path is not off the data path (operator, 2026-10-26)

`python3 scripts/ci/check_shadowed_features.py` - **re-run, never quote**; report entries scanned and the
`execution: shadow` leg count it prints. Then, beyond what CI can see: for every feature, model or signal
turned off or annotate-only since the last audit (`git log -p config/strategies.yaml config/accounts.yaml`,
`*_MODE`/`*_ENABLED` defaults, advisory heads demoted), confirm it has a registry entry, its **consumed**
artifact is fresh (read the file's newest timestamp, not the producer's log), and an owner row with a
re-entry test exists. Each `gap` / `could_not_verify` entry and each shadow leg without its own owner row
becomes a row. Positive control: `python3 scripts/ci/check_shadowed_features.py --self-test`.

### C11. Consumed-input freshness (operator, 2026-10-26: "Yes, add it to the weekly audit core checks")

Every file or feed the live trader or web-api **reads at runtime** must have a freshness check on the
**consumed** artifact, not on its producer's output. Enumerate by measuring the code: the readers in `src/`
and the paths they open (`config/*.yaml` data files such as `economic_calendar.yaml`, `comms/*` stores read
by `src/`, news / funding / candle sources). State the **population** (readers found, how found) and the
**denominator** (how many have a consumer-side check). List every one without a consumer-side check and
file each as a checklist row or pipeline item. Checks live in `scripts/macro/check_producer_liveness.py`
(being extended with the consumer-side calendar and news checks by the DATA-FEEDS lane) - extend that
checker, **do not build a parallel mechanism**. Positive control: show the probe flags a known-stale
consumed file. Worked example: 2026-10-26, that checker watched `comms/macro/econ_calendar_snapshots.jsonl`
(fresh) while `config/economic_calendar.yaml` (consumed) sat stale from 2026-07-30. Related: C10.

### C9. RECURRENCE — the anti-treadmill step (never skipped)

For every finding that **closed in the last 7 days** (checklist rows moved to `done`, pipeline `done`):

1. **Is there a test, guard or alert that fails if it returns?** No detector ⇒ open a row
   `DETECT-<finding>` (or add the detector in this PR if it is Tier-1 and small).
2. **Sweep the class, not the instance.** Grep the class and report the remaining population **with its
   denominator** (the pairs fix corrected the pairs tests and left the same fictional column in 20
   other fixtures).
3. For every instrument you leaned on this week: does it have a failure-path self-test? Name the ones
   that do not (`guard_selftests.py` coverage is the denominator).

## ROTATING deep pass — ISO week mod 4

Run **exactly one** per week (the others rotate in). Each is a bounded question with an instrument; if
the instrument is missing, building it is the finding (a row).

### 0 — OUTCOME + INDEPENDENCE

- **OUTCOME — did it deliver what the design promised?** For each subsystem shipped since the last time
  this pass ran, quote the *promise* (ROADMAP row, design doc, the A/B that gated it: "cuts maxDD",
  "removes flip-churn"), measure the outcome over history **on the population the promise was about, stating
  n and provenance coverage**, and grade: `delivered` · `no measurable effect` · `harmed` · `not yet
  measurable (what settles it, by when)`. `no measurable effect` is a finding, not a null result — removal
  is a legitimate, high-value outcome. Do not confuse "the gate is enforcing" with "the gate is helping".
- **INDEPENDENCE — can the claim be contradicted?** For each load-bearing verdict the system publishes,
  what evidence would falsify it, and does that evidence exist where its producer does not control it?
  Hunt **reducers**: a boolean or scalar standing in for a structured state (`covered`, `active`,
  `present`, `[]` for both "empty" and "failed"). If nothing can contradict it, build the read surface
  (a row), then re-audit through it.

### 1 — CONSISTENCY + LIVENESS

- **CONSISTENCY**: rules ↔ code ↔ config ↔ data. `canonical-doc-coherence`, `doc-freshness`; the
  API table in `docs/reference/bot-api-reference.md` against the router. **Field beats comment.**
- **LIVENESS — the zombie hunt**: inventory brokers (`integrator.py::EXCHANGE_MAP`), services/timers
  (`deploy/*`, `diag.py::_CANONICAL_UNITS`), workflows, every `*_ENABLED`/`*_MODE` gate, external
  transports. Three probes each — reachability (grep *call sites*, not the definition), runtime usage
  (pull it), provenance (`git log`, retirement notes). An artifact present but unreached/unrun is a
  **corpse to remove or justify in writing**, not an inventory gap to document.

### 2 — MODULARITY

How many files must change to make ONE system change, and can a change be half-applied? Pick the last
two changes that touched ≥ 4 files (add a strategy, add an account, add a guard) and count the edit
sites. Also count **definitions per concept** (the sharper probe — a duplicated definition produces no
diff and no error, it quietly disagrees): cost constants, symbol/instrument maps, risk units,
provenance predicates. The single-owner pattern already exists (`check_cost_model_single_owner.py`,
`src.utils.paths`, `src/runtime/provenance.py`); each new duplicate found is a row to consolidate
behind one owner plus a guard that fails on the second definition.

### 3 — DESIGN CRITICISM

*Should this exist at all, and is this the right mechanism?* A finding of the form "built exactly as
specified and the specification is wrong" outranks a conformance finding of the same severity.
Bounded to **one or two** subsystems per run (pick the ones with the most spend or the most incidents
since the last design pass; name them and why):

- **Cohesion**: where does one concept have two implementations that can disagree? where does a
  decision need facts from three places with no join? which seams have no owner?
- **Philosophy**: where has "observe first, gate later" produced a soak nobody reads, and fail-permissive
  become fail-silent? Does the tier system make *removal* harder than adding? Which guard now costs more
  attention than the defect it catches?
- **Mechanism**: what would we build if we started today? Answer in writing even if it is "the same".
- **What are we not measuring at all?** **What should be deleted?**

Design findings are **proposals**: row with the reasoning and trade-off, `tier` stated, `next_action:
ask_operator` where Tier 3. Never a unilateral change.

## Findings — schema and routing (binding)

Every finding, from any step, is recorded with:

| field | rule |
|---|---|
| `claim` | one sentence, falsifiable |
| `evidence` | the exact command/query **and** its output (or path to it). Not a description of one |
| `expected` vs `actual` | the two must differ or it is not a finding |
| `population` | what was measured over, with n |
| `blast_radius` | money-at-risk / accounting / observability / docs |
| `tier` | 1 / 2 / 3 |
| `detector` | the permanent check that fails if this recurs — **or** "no detector possible because X" |
| `disposition` | **fixed** (merged or in this PR) · **row** (checklist id) · **pipeline** (`PI-…`) · **unit** (`research/queue/…`) · **verified non-issue** (with the probe) |

**Routing — exactly one of these, chosen by what the finding is:**

- *A build* (fix a bug, add a detector, consolidate a definition, wire a read surface) → **checklist row**
  via `scripts/ops/checklist.py add <ID> --title … --tier N --owner manager --note "<claim; evidence;
  detector>"`, with a `roadmap` ref (`set <ID> roadmap='["L-OPS"]'`). Row ids: `AUD-<YYYYMMDD>-<slug>`.
- *A question* (does X still hold? is Y worth keeping?) → **`research/queue/<id>.yaml`** with the decision
  rule registered before any run.
- *A thing that needs picking up later* (recheck in N days, awaiting data, awaiting an observation) →
  **pipeline item** via `scripts/ops/pipeline.append(item, intent="new")` with `due_when`, `origin.rerun`
  (the command that re-asks the question), and — to close — `terminal_reason`.
- *Tier-1, small, in scope* → **fix it in this PR** and list it as `fixed`.
- *Tier-2/3* → a row or pipeline item with `next_action: ask_operator` and the **exact proposed change**;
  the report's "for the operator" line points at it. Data-backed Tier-2/3 decisions follow the standing
  authorization (decide, ship, notify) only when a committed evidence record settles it — an audit
  finding is a claim, not that record.

**"Not my task" and "it was already like that" are not dispositions.** A finding in a chat message, a PR
comment or a new memo is not filed.

## Report — one page, `docs/reviews/<date>-weekly-audit.md`

One page means ≈ 60 lines. Detail lives in the rows and in the evidence paths they cite, not in the report.
Header: doc-status line (`live`, lane id, window), deep pass chosen and why. Then, in this order:

1. **Verdict** — one line each: *invariants* (pass n / fail n / could-not-look n, with populations),
   *TP doctrine* (compliant x of y), *live = mirror* (pass/fail), *cost stack* (n records, n fee-only),
   *overdue* (n dispositioned / n found), *spend* (vs plan).
2. **Findings table** — `id · axis · blast radius · tier · disposition (row/PI/unit/fixed) · detector`.
   Every row of this table resolves to something that exists (check with `checklist.py` / `pipeline.py`).
3. **Deep pass** — what was asked, what was measured, the grade/answer. Three to ten lines.
4. **Closed since last audit and whether they have a detector** (C9).
5. **Coverage** — what was **not** reached and why, each as a filed row. Both numbers: behavioural
   (invariants + traces run) and reading (what was only read). Never imply the whole system was audited.
6. **For the operator** — Tier-3 proposals and genuine preference calls only; one line each, pointing at
   the row. If empty, say "none".

State **merged ≠ deployed ≠ observed** for every item you call fixed.

## Completion test — the audit is done only when ALL of these pass

Run this before you open the PR; paste its output in the PR body.

```bash
python3 scripts/ops/checklist.py --check                       # store consistent
python3 scripts/ops/pipeline.py --check                        # no NEW violations (4 collisions are GRANDFATHERED; "NOT clean" with only those is the baseline, rc=0)
python3 scripts/ops/pipeline.py --due | head -40               # nothing you were handed is still due-and-untouched
git diff origin/main -- docs/reviews > "$TMPDIR/d.patch"; python3 scripts/ci/check_stated_population.py "$TMPDIR/d.patch"  # the report states its populations
wc -l docs/reviews/$(date +%F)-weekly-audit.md                 # ≈ one page
```

And by hand, each answered yes/no in the PR body:

1. Every finding in the report's table resolves to a row, a PI id, a unit, or a merged/in-PR fix — no
   finding is prose-only.
2. Every finding has a `detector` or an explicit "no detector possible because …".
3. C1–C11 each have a result in the Verdict or in Coverage as a filed "not reached" row. None silently skipped.
4. Every "0 violations" has a positive control stated beside it.
5. The deep pass for this ISO week ran, or the report names why not and the row that carries it.
6. Every row you touched has a TRUE state (`landed_unproven` ≠ `done`, and names the closing observation).
7. `close-out` skill run: working tree clean, branch pushed, PR open, row `WEEKLY-AUDIT-<date>` updated.

## Landing — a self-landing PR

1. Commit the report plus any Tier-1 fixes/rows (they ride the same PR).
2. `python3 scripts/ops/land_pr.py --held-by <your session id> --why "<tier judgement in your own words>" --verify`
   — it writes the three landing files from the guard's own derivation (`.github/pr-landing/<slug>.json`,
   `.github/pr-automerge-requests/<slug>.txt`, `.github/merge-slots/<slug>.json`). Commit them in the same push.
   If the diff touches a Tier-2/3 path or a path outside `TIER1_SURFACE`, the script computes a **hold**; then the
   manager merges — say so in the report's operator line, do not route around the guard.
3. Push, open the PR as a **draft is the default; mark it ready only through the landing route the script armed**,
   subscribe to its activity, and drive it green (red CI on your PR is yours until proven otherwise).
4. Update the row: `checklist.py set WEEKLY-AUDIT-<date> state=landed_unproven prs='[<n>]'` with the
   observation that closes it ("PR merged to main and the findings' rows are visible on the Workflow page"),
   then `done` once merged and observed. Report to the manager in **one line**: PR, verdict, n findings by
   disposition, anything for the operator.

## What this audit does not do

- It does not edit `config/`, any order path, strategy params, risk caps, or account modes. Proposals only.
- It does not resurrect the retired registers (backlogs, `SESSIONS.json`, the board). Rows and pipeline items only.
- It does not re-run `/performance-review` or `/ml-review` (Wed/Thu walk-through) or replace `/health-review`
  (Saturday); C8 is a second look, not a second review.
- It does not report how long it took.

## Honesty

Say "I did not look" rather than imply a clean pass. A negative needs a denominator and a positive
control. Verify your own output hardest where it confirms what you expected. If you did not check it this
session, say so plainly.

## Composes with

`diag-data` (reads) · `health-review` (C8) · `exit-refinement` (C2 follow-ups) · `backtesting` (C4) ·
`manager` § "Weekly planning (Wednesday) and the weekly cycle" · `close-out` (completion) ·
`doc-freshness` (consistency pass) · `research-ops` (units filed here are graded there).
