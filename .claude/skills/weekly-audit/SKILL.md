---
name: weekly-audit
description: The WEEKLY system audit (Wednesday 18:31Z after the weekly reset, one Opus lane, feeding Thursday planning). Four layers per docs/reference/llm-analyst-skill-design.md: PRIOR CALLS grades the last audit's findings first; CHECKS is a fixed core of script-computed control tests, each with its population, a read-state and a positive control. They cover protection and reconciliation recomputed from rows, TP doctrine, live = mirror, the full cost stack, stated populations, follow-through, spend and lane utilisation, the research SLOs, shadowed features, consumed-input freshness, the grading loop, AS-DESIGNED (the demo floor actually trades, recorded data actually trains models, the mandated loops actually ran) and an independent re-test of the last health review. ANALYSIS reads the trend across audits, root-causes why findings recur or stall, and runs one rotating deep pass (ISO week mod 4: 0 OUTCOME+INDEPENDENCE, 1 CONSISTENCY+LIVENESS, 2 MODULARITY, 3 DESIGN CRITICISM). Every finding becomes a fix, a row, a unit or a pipeline item with a detector and a pre-registered check. Use when the manager dispatches a WEEKLY-AUDIT-<date> lane, or the operator says "/weekly-audit", "run the weekly audit". NOT the health review (/health-review, same night 19:11Z), NOT a performance review, NOT a code review.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /weekly-audit — do the controls work, and does the system run as designed?

> **Redesigned 2026-10-28** (lane `SKILL-DESIGN-SYSTEM`, operator directive ~07:15Z). It follows the shared
> two-layer pattern in [`docs/reference/llm-analyst-skill-design.md`](../../../docs/reference/llm-analyst-skill-design.md).
> The predecessor (2026-10-15) is kept verbatim at
> [`docs/archive/2026-10-28-skill-redesign/weekly-audit-SKILL.md.pre-redesign`](../../../docs/archive/2026-10-28-skill-redesign/weekly-audit-SKILL.md.pre-redesign).
> Its core checks are kept. What changed: a grade of last week's findings, trend across audits, AS-DESIGNED,
> and an independent re-test of the health review, which replaces "health review #2". See § Design basis.

**Split with `/health-review`** (it runs 40 min after you, on the same night):
- **health** asks *is the machine running, and is it getting worse?*
- **this audit** asks ***do the controls that are supposed to catch problems actually catch them, does what we built
  deliver, and does the system run the way its design says?***

Audit outcomes, not descriptions. The old audit returned clean on a broken system because it asked the system to
describe itself: MGC sat 122.74 points past its target for 11 days across two clean audits, because
`protection_coverage` said `covered`. Recompute the verdict from the least-reduced rows. A verdict that nothing
outside its producer can falsify is itself the finding.

## Mechanics and budget

| | |
|---|---|
| Who / when | one Opus lane; Wednesday 18:31Z (trigger "Weekly audit (Wed after reset)"); row `WEEKLY-AUDIT-<YYYY-MM-DD>` created `in_flight` at start, owner = your session |
| Branch | `claude/weekly-audit-<YYYY-MM-DD>` |
| Output | `docs/reviews/<date>-weekly-audit.md`, one page, in one self-landing PR |
| Scope | **read-only on the fleet**. Writes go to rows, pipeline items, units, the report, and Tier-1 fixes and detectors. No config, no order path, no Tier-2/3 |
| Shape | the [shared pattern](../../../docs/reference/llm-analyst-skill-design.md): **0 prior calls** (~10 %) → **1 CHECKS** (≤ 35 %) → **2 ANALYSIS** incl. the deep pass (≥ 35 %) → **3 decisions** + close-out (~20 %, reserved first). If short, report a check as `not_reached` and file it; never drop Layer 0 or the deep pass silently |

**Deep pass:** `python3 -c "import datetime as d;print(d.date.today().isocalendar()[1] % 4)"`.
2026-10-28 is ISO week 44, so `0`; then 11-04 → 1, 11-11 → 2, 11-18 → 3. If the dispatch names another pass,
use it and say so.

## Step 0 — trustworthy instruments, last audit loaded

- `git fetch --deepen=2000 origin` if the clone is shallow.
- Self-tests first:
  - `python3 scripts/ops/system_invariants.py --self-test`
  - `python3 scripts/ci/guard_selftests.py --all`
  - `python3 scripts/ops/checklist.py --self-test`
  - `python3 scripts/ops/pipeline.py --self-test`
  - `python3 scripts/research/research_slo.py --self-test`
  - `python3 scripts/ci/check_shadowed_features.py --self-test`
  - `python3 scripts/ops/check_claude_grade_loop.py --self-test`

  A failing self-test is finding #1, and the reading that instrument would have produced is `could_not_look`.
- **Load the last 4 `docs/reviews/*-weekly-audit.md`** and every row and item they filed (ids from their findings
  tables), each with its current `state` and `updated_at`. That is the input to Layer 0 and 2a.

## Layer 0 — PRIOR CALLS (first, never skipped)

**Follow-through first (2026-10-28):** run `python3 scripts/ops/review_followthrough.py --source weekly-audit --window-days 7` and record its cohort and backlog line before grading calls; an open item older than 14 d with no owner is a call to schedule or kill, not to re-file. (The script lands in #20871, REVIEW-FOLLOWTHROUGH. If it is not on main, record `could_not_look: no instrument`.)

For every finding in the last audit, and every one still open from earlier audits:
1. re-run the check it named (or the closest check that answers it);
2. grade the call `hit` / `miss` / `unresolved` / `void`, per the [shared pattern](../../../docs/reference/llm-analyst-skill-design.md) § 6;
3. grade its action: `closed+detector` · `closed-no-detector` · `moving` · **`stalled`** (no state change ≥ 7 d).

Report the counts, the closure ratio (closed+detector ÷ filed) and a Brier score (`INDETERMINATE` below 10
resolved calls).

A call `stalled` across ≥ 2 audits is now a **follow-through finding**. Say *why* it is not closing (no owner? a
decision nobody asked for? too big to close? nobody reads the row?), then decide in Layer 3: fix it now (Tier 1),
put the exact decision to the operator, re-scope it into something closable, or kill it with a reason. Never
re-file it. Re-run the check; do not re-argue the call.

## Layer 1 — CHECKS (fixed; every one runs and is recorded)

**Every check produces one Verdict line:** status (`pass | fail | watch | could_not_look | not_reached`), the
value, the **population with n**, the evidence path, and **last audit's value beside it**.

- **Positive control.** Every "0 violations" names its positive control: the same probe returning a known
  positive (a planted fixture, a self-test case, or last week's finding that should still reproduce).
- **Read-state.** `could_not_look` carries the reason, is never a pass, and is a liveness finding about the
  instrument or relay.
- **Re-run, never quote.** Last week's number appears only in the "prior" column.

| id | control under test | instrument (exact) | population | fail means |
|---|---|---|---|---|
| C1 | **Protection + reconciliation, recomputed from rows** (money at risk, first) | live payloads via `diag-data` (stems `ib_open_orders`, `bybit_open_orders`, `exchange_positions`, `positions`, `journal_trades`, `exit_loop_health`; `positions` is `curl https://ict-bot.duckdns.org/api/bot/positions?include_paper=true` directly, never diag_fetch, and never without the flag) → `python3 scripts/ops/system_invariants.py --payloads <dir>`. Prop accounts are read by their own route; one without a probe is `could_not_look` (AUD-20261019-PROP-INVARIANT-BLIND). Plus **one full pipeline trace** per week, rotating real-money / prop / demo / refused: signal → intent → sizing → placement → journal → protective legs → exit → reconcile → close + P&L provenance. Record the hop where it died | open positions; (account, symbol) pairs; package legs; one trace | a naked / over-covered / target-less position; journal ⇄ venue mismatch; a close that is not TP / SL / strategy-close; an aggregate mixing MEASURED with FABRICATED (`src/runtime/provenance.py`) |
| C2 | TP doctrine | `python3 scripts/ci/check_tp_doctrine.py --strict --json` | routings by class: real-money → prop → mirror → paper | new non-compliant routings, or debt not shrinking. Each one maps to an exit-refinement row/unit by money at stake |
| C3 | Live = mirror | `pytest tests/test_paper_portfolio_accounts.py` (roster equality + `test_mirror_trade_shaping_fields_equal_live`); positive control = drop one leg locally and see it fail; plus trade-level twins over the week from the journal | roster legs; mirror trades in the window | a divergence. A Tier-3 proposal; never edit the roster |
| C4 | Full cost stack on promotable results | every Stage-0 evidence record or mandate fire since the last audit; `python3 scripts/ci/check_cost_model_single_owner.py` | records changed in the window | a fee-only record on a promotion path; `scripts/backtest_orb.py` / `src/backtest/backtester.py` in a corpus; a rule not registered before the run |
| C5 | Populations stated | `python3 scripts/ci/check_stated_population.py <diff of the week's docs>`, plus your read of this week's brief and reports | quantitative claims read | a number with no population, window or cost basis; a sign that flips on a filter |
| C6 | Follow-through | `python3 scripts/ops/pipeline.py --due` / `--stats` / `--gate`; `python3 scripts/ops/owner_liveness.py`; checklist rows `in_flight` with no live lane, `landed_unproven` past `due_by`, `blocked_on` cleared | due items; unrouted; laned rows | unrouted rising, oldest-unrouted > 7 d, stale `in_flight`, unpulled observations. Disposition what you were handed; the class goes to 2a/2b |
| C7 | Spend and lane utilisation | `python3 scripts/ops/spend_meter.py` and `--capacity`; `list_sessions(mine=true)` | lanes dispatched; ceilings vs `spend_usd` | over-ceiling lanes, ceilings with no spend recorded, hours below the KEEP-N target while `checklist.py queue` was non-empty (`not_observed` if lane timing cannot be read). Never report session length |
| C8 | **The health review, tested independently** (replaces "health review #2") | take 2 of last week's health-review `ok` verdicts on money or deploy checks (H2 / H3 / H4 / H6 in `comms/reviews/health/<newest>.json`) and re-derive each from raw rows yourself | 2 verdicts | your re-derivation disagrees: the health check reads a reducer, not the outcome. Also grade the health review's own `prior_calls` honesty |
| C9 | Research pipeline SLOs | last 7 `comms/research/health/<date>.json` (`scripts/research/research_slo.yaml`) | days × SLOs; runs | a red SLO with no same-day disposition; a missing day; a run gap > 4 h |
| C10 | Off the trade path is not off the data path | `python3 scripts/ci/check_shadowed_features.py`; `git log -p config/strategies.yaml config/accounts.yaml` since the last audit | registry entries; `execution: shadow` legs | a turned-off feature with no registry entry, a stale **consumed** artifact, or no owner row with a re-entry test |
| C11 | Consumed-input freshness | `python3 scripts/macro/check_producer_liveness.py` (extend it, never a parallel checker); enumerate readers in `src/` | readers found (and how) vs readers with a consumer-side check | a consumed file with no consumer-side check |
| C12 | The Claude grading loop ran | `python3 scripts/ops/check_claude_grade_loop.py --live` (exit 2 = `could_not_look`: deepen or fix the relay, then re-run) | the 4 checks' populations | a `missing_outcome`, an unlogged SKILL/BRIEF version, or `role_grade.json` older than 2 d |
| C13 | **AS-DESIGNED: does the system run the way its design says?** | (a) **demo floor** (OPERATING-PLAN § 2 "Stage 1 is the DEMO FLOOR"): re-parse the `strategies:` rosters of `bybit_1` / `alpaca_paper` / `ib_paper` in `config/accounts.yaml`; per rostered leg, trades + packages + logged refusals over 7 d from diag `journal` (page past 1000 rows); count `execution: shadow` on non-retired legs. (b) **learning**: rows produced → datasets built → models trained → models scored, per family, from the trainer registry via `trainer-vm-diag-request` (`python -m ml list-models`, `dataset_builds.jsonl`, `training_cycle.jsonl`). (c) **mandated loops**: research-ops 4×/day, the hourly live review, the desk wake, the daily report and the weekly routines each have a run record in the window (`list_triggers` `last_run`, plus their output files) | (a) rostered legs × floor accounts; (b) model families; (c) scheduled routines | a non-retired leg that neither traded nor logged a refusal (state quiet-by-design vs blocked, with the cause); a shadow non-retired leg; data recorded but never trained; a loop with no run. **Merged ≠ deployed ≠ observed:** a design is "running" only when its output is observed |

## Layer 2 — ANALYSIS

Never paraphrase the Verdict lines; write what they *together* imply. Follow the shared prompts (pattern § 3):
- read wide before forming a view, and search the repo before calling a finding new;
- choose 3–7 material questions by money and risk;
- for each, write ≥ 2 hypotheses, one of them always *noise or expected variation*, and run the test that
  discriminates between them;
- hunt surprises, and count your comparisons.

There is no quota of findings. "Nothing material" stands only with the falsification attempt shown.

**2a. Trend across audits.** Put each C-check's value beside the last 4 audits (lifetime where its series
exists). Name every series moving the wrong way for ≥ 2 audits, say what drives it, and what it predicts if
nothing changes.

**2b. Recurrence: the class, not the instance.** For every finding closed in the last 7 days:
1. Is there a detector that fails if it returns? If not, open a row `DETECT-<finding>`, or add it in this PR if
   it is small.
2. **Sweep the class**: grep for it and report the remaining population with its denominator.

**2c. Root cause of the top questions.** Name the cause at file / line / key / job level, give a probability,
and say what would change your mind. Remove what the environment did (regime, the instrument, a shared upstream)
before blaming the subject. Blameless: name the mechanism that let it through, and whether a control *should*
have caught it and why it did not.

**2d. The deep pass (ISO week mod 4) — exactly one per week.** Each is a bounded question with an instrument. If
the instrument is missing, building it is the finding.
- **0 OUTCOME + INDEPENDENCE.**
  - Outcome: for each subsystem shipped since this pass last ran, quote its *promise* (ROADMAP row, design doc,
    the gating A/B). Measure the outcome on the population the promise was about, with n and provenance
    coverage. Grade it `delivered` · `no measurable effect` (a finding; removal is a valid outcome) · `harmed` ·
    `not yet measurable` (what settles it, by when). "The gate enforces" is not "the gate helps".
  - Independence: for each load-bearing published verdict, what would falsify it, and does that evidence live
    where its producer cannot touch it? Hunt **reducers**: a boolean or scalar standing in for a structured state
    (`covered`, `active`, `[]` meaning both empty and failed).
- **1 CONSISTENCY + LIVENESS.**
  - Consistency: rules ↔ code ↔ config ↔ data (`canonical-doc-coherence`, `doc-freshness`, the API table vs the
    router). Field beats comment.
  - Liveness (the zombie hunt): brokers (`integrator.py::EXCHANGE_MAP`), units/timers (`deploy/*`,
    `_CANONICAL_UNITS`), workflows, every `*_ENABLED`/`*_MODE`, transports. For each, probe reachability (call
    sites, not definitions), runtime use and provenance. A present-but-unreached artifact is a corpse to remove
    or justify.
- **2 MODULARITY.** Count the edit sites of the last two ≥ 4-file changes. Count **definitions per concept**
  (cost constants, symbol maps, risk units, provenance predicates). Each duplicate becomes a row to consolidate
  behind one owner, plus a guard on the second definition (`check_cost_model_single_owner.py`, `src.utils.paths`
  and `provenance.py` are the pattern).
- **3 DESIGN CRITICISM.** One or two subsystems, chosen by spend or incidents (name them and why). Should it
  exist? Is it the right mechanism? Where does one concept have two implementations, and where has
  "observe first" become fail-silent? What would we build today? What are we not measuring at all? What should
  be deleted? Findings are proposals (row, tier, `next_action: ask_operator` for Tier 3).

## Layer 3 — DECISIONS (every call ends somewhere)

One `calls` list, ranked by money at risk:
1. real money;
2. prop;
3. the demo floor;
4. learning and research;
5. observability;
6. docs.

Each call has:

| field | rule |
|---|---|
| `claim` | one sentence, falsifiable |
| `evidence` | the exact command or query **and** its output path |
| `expected` vs `actual` | they differ, or it is not a finding |
| `population` | n and window |
| `p` | a probability, MEASURED / INFERRED |
| `blast_radius` · `tier` | |
| `detector` | the permanent check that fails on recurrence, or "no detector possible because X" |
| `check` | pre-registered `{command, rule, resolves_when}`: what next week's Layer 0 re-runs |
| `ending` | **fixed** (in this PR; state merged/deployed/observed) · **row** `AUD-<YYYYMMDD>-<slug>` via `scripts/ops/checklist.py add … --tier N --owner manager` + `set <ID> roadmap='["L-OPS"]'` · **unit** `research/queue/<id>.yaml` (rule registered before the run) · **pipeline** via `scripts/ops/pipeline.py` (`due_when`, `origin.rerun`) · **no action, because …** (with the probe) |

Premortem each Tier-2/3 call: assume it made things worse in three months and say why. Tier-2/3 calls carry the
exact proposed change and `next_action: ask_operator`. An audit finding is a claim, not the evidence record that
would let the data-backed authorization fire. "Not my task", "noted", "monitor" and "it was already like that"
are not endings.

## Report — one page (≈ 60 lines), `docs/reviews/<date>-weekly-audit.md`, in the shared order

```
# Weekly audit <date> — <one sentence: what most affects money/risk now>
(doc-status line · lane · window · deep pass and why)
## 0. Prior calls  — graded counts, closure ratio, Brier; every stalled call by name + the decision taken
## 1. CHECKS       — one line per C-id: status · value · population · prior · positive control; could_not_look listed
## 2. ANALYSIS     — trend (3–6 lines); per question: hypotheses · test · survivor · p; recurrence; the deep pass (3–10 lines); surprises
## 3. Decisions    — ranked: id · money/risk · tier · p · detector · check · ending (every id resolves via checklist.py / pipeline.py)
## 4. Not done     — what was not reached or only read, each filed; behavioural vs reading counts; never imply the whole system was audited
For the operator: Tier-3 proposals and genuine preference calls, one line each with the row, or "none".
```

## Completion test (paste the output in the PR body)

```bash
python3 scripts/ops/checklist.py --check
python3 scripts/ops/pipeline.py --check          # grandfathered collisions only = baseline, rc 0
python3 scripts/ops/pipeline.py --due | head -40
git diff origin/main -- docs/reviews > "$TMPDIR/d.patch"; python3 scripts/ci/check_stated_population.py "$TMPDIR/d.patch"
wc -l docs/reviews/$(date +%F)-weekly-audit.md
python3 scripts/ci/run_guards.py --base-ref origin/main
```

Answer each yes/no in the PR body:
1. every finding resolves to a fix, row, item or unit;
2. every finding has a detector or a stated reason why none is possible;
3. C1–C13 each have a result, or a filed `not_reached`;
4. every "0" has a positive control;
5. Layer 0 graded every prior finding;
6. the deep pass ran;
7. every touched row has a TRUE state (`landed_unproven` ≠ `done`, with its observation);
8. `close-out` was run.

## Landing

1. Commit the report and the rows/fixes.
2. Run `python3 scripts/ops/land_pr.py --held-by <session id> --why "<tier judgement>" --verify`. It writes the
   three landing files; commit them in the same push. A computed **hold** means the manager merges; say so.
3. Push, open the PR, subscribe, and drive it green.
4. `checklist.py set WEEKLY-AUDIT-<date> state=landed_unproven prs='[<n>]'` with the observation that closes it, then
   `done` once merged and observed.
5. Report to the manager once, in 1–5 lines: PR, verdict, the Layer-0 closure ratio, findings by disposition, anything for
   the operator.

## Never

Edit `config/`, an order path, strategy params, risk caps or account modes (proposals only). Resurrect retired
registers. Re-run `/performance-review` / `/ml-review` / `/health-review`. Report how long it took.

## Design basis (2026-10-28) — why this shape

**Diagnosis.** One audit has run under this skill (`docs/reviews/2026-10-19-weekly-audit.md`, run 10-21). Its
predecessors were the archived full-system audits (`docs/audits/system-audit-2026-09-29.md`, `-10-04.md`).

- **The checks were done well.**
  - 9 invariants recomputed from live payloads, with positive controls.
  - One real-money trace.
  - An instrument bug found and fixed in-PR (F1).
  - Every check had a population.
- **The deep pass was real reasoning.** D1 found that liveness is spread over three unjoined layers, and
  proposed what to build.
- **Follow-through failed.** At 2026-10-28, 7 of its 10 finding rows are still `queued` and 1 is
  `landed_unproven`. Nothing in the skill graded them, so the next run would have re-measured the same 253 due
  items and re-filed them: findings became post-it notes at the next step down.
- **The window was this week only.** "63 due as of 10-14" appeared once, as an aside, not as a series.
- **"Health review #2" (C8) duplicated the health review.** Since 2026-10-28 the two run 40 min apart on the same
  night. It is replaced by an independent re-test of the health review's verdicts (C8), which tests the control
  rather than repeating it.
- **"Does it run as designed" was not asked.** Nothing checked that demo-floor legs trade or that recorded data
  trains anything. That is now C13.
- The Monday run was skipped for the usage wind-down (10-19 ran 10-21). The schedule moved to Wednesday after the
  reset (operator 2026-10-19/-21).

**Practice adopted** (ACAD academic · PRAC practitioner · VEND vendor):

- **Annual and regular review of control *effectiveness*, documented with an inventory of the controls,
  thresholds and systems reviewed** — SEC Rule 15c3-5
  ([SEC](https://www.sec.gov/rules/final/2010/34-63241-secg.htm)) and FINRA's 2026 oversight report, which lists
  a missing inventory as a deficiency
  ([FINRA](https://finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/market-access-rule))
  — PRAC/regulatory. Basis for the CHECKS layer as an inventory with populations.
- **Self-assessments omitted required elements; good practice is action-tracked recommendations and independent
  review of the self-assessment** — FCA multi-firm review of algorithmic trading controls, 2025
  ([FCA](https://www.fca.org.uk/publications/multi-firm-reviews/algorithmic-trading-controls-high-level-observations))
  — PRAC/regulatory. Basis for Layer 0 and C8.
- **Risk assessment that inventoried existing controls instead of examining risks; earlier incidents fixed
  narrowly without root cause; alerts nobody acted on** — Knight Capital, SEC 2013
  ([SEC 2013-222](https://www.sec.gov/news/press-release/2013-222)) — PRAC/regulatory. Basis for 2b, 2c, deep pass 0 and
  the positive controls.
- **Risk-based audit planning, with continuous risk assessment so a fixed rotation does not miss a changed risk
  profile** — IIA practice guide
  ([IIA](https://www.theiia.org/en/content/guidance/recommended/supplemental/practice-guides/developing-a-risk-based-internal-audit-plan/))
  — PRAC. Eulerich, Georgi & Schmidt (survey of 264 CAEs) — ACAD. Basis for keeping the rotation to ONE deep
  pass while the core runs weekly, and for choosing DESIGN-CRITICISM subjects by spend and incidents.
- **Untracked action items are forgotten; failures that mirror earlier incidents need a deeper review** — SRE
  Workbook ch. 10 ([sre.google](https://sre.google/workbook/postmortem-culture/)) — PRAC. Basis for Layer 0 and
  the pre-registered `check`.
- **Toil: measure it, and bound the share of time it takes** — SRE Workbook ch. 6
  ([sre.google](https://sre.google/workbook/eliminating-toil/)) — PRAC. Basis for treating a check that costs
  more than its catch as a DESIGN-CRITICISM subject.
- **Compare metrics to their history at a weekly cadence** — AWS Well-Architected OPS11-BP07
  ([AWS](https://docs.aws.amazon.com/wellarchitected/2024-06-27/framework/ops_evolve_ops_metrics_review.html))
  — VEND. Basis for 2a.
