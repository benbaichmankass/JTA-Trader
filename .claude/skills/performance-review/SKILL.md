---
name: performance-review
description: Autonomous review of the ICT trading bot's TRADING PERFORMANCE, in two layers. Layer 1 CHECKS is fixed and deterministic (every leg over lifetime / 90d / 30d / 7d windows, live vs its own backtest band, attribution, decay, cost, baselines, data coverage, grading, research-pipeline and backlog gates, each computed by a named script). Layer 2 ANALYSIS is Claude's work (read each material leg's full history, backtest evidence, prior reviews and what happened to their calls; form competing hypotheses and try to falsify them; hunt what does not fit; rank findings by money; make every call a row or queue unit with a pre-registered check). Opens by grading the previous review's calls. Owns comms/claude_strategy_scores.jsonl (per-decision grading, append-only) and files trading + research follow-ups to docs/claude/work/PIPELINE.jsonl via scripts/ops/pipeline.py. Also answers \"did anyone read that sweep\", \"is the research queue healthy\", \"/research-review\". Use when the operator says "run the performance review", "/performance-review", "score the recent trades", or "how are the strategies doing". NOT for ML/model perf (use /ml-review) and NOT for system/pipeline plumbing (use /health-review).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /performance-review — CHECKS, then ANALYSIS

> Also answers to **`/research-review`**. Serves the **TRADING** research track
> ([`docs/reference/trading-and-model-practice-principles.md`](../../../docs/reference/trading-and-model-practice-principles.md)).

> **Why it has this shape (redesign 2026-10-28, lane `ANALYTIC-SKILL-DESIGN`).** The operator asked
> whether this review moves performance, suspecting it was either too loose (no deep thinking) or too
> scripted (statistics in, statistics out), and that it checked last week's trades while ignoring each
> strategy's whole record. Measured on the last six reviews
> ([`docs/research/analytic-skill-design-2026-10-28.md`](../../../docs/research/analytic-skill-design-2026-10-28.md) § 1):
> **it was both.** The grading core was scripted (82% of 908 grades since 2026-09-20 came from the daily
> rubric cron; `risk_management: unknown` on 907/908; the B cohort won 32% of the time and the C cohort
> 46%, so the grade carried no information). The analysis was loose: 4 of 4 JSON reviews read only the
> window since the previous review; none formed or tested a hypothesis; 3 of 4 proposed nothing; 10 of
> 13 filed items were mechanics, not performance; a recommendation ("run the M8 sweep for
> `ada_pullback_2h`") was repeated twice and never ran; and the 2026-10-21 headline finding had already
> been attributed three days earlier. The prep routine asked for "grading and numbers only". **The fix
> is a split of labour, not more rules:** scripts compute the checks so Claude never spends its
> reasoning on arithmetic; Claude spends it on the questions the checks raise.

## The shape in one screen

| Layer | Who does it | What it must produce | What it must NOT do |
|---|---|---|---|
| **0. Prior calls** | Claude, from the last review's `calls[]` | each call graded `hit / miss / unresolved / void`, with the check it named re-run | re-argue a call instead of running its check |
| **1. CHECKS** | named scripts; Claude runs them and reads them | the fixed tables C1–C12 below, **every leg, every window**, each with its population | narrate, rank or interpret; quote a number without its n and window |
| **2. ANALYSIS** | Claude | 3–7 **material questions**, each with competing hypotheses, the test run, what survived, confidence, and money at stake; surprises; ranked decisions | restate check numbers as findings; end on "n too small"; repeat a prior call without saying why it did not happen |
| **3. Decisions** | Claude | every call is a checklist row / queue unit / pipeline item with a **pre-registered check**, or `no action, because …` | write a memo; enact a Tier-3 change |

**Where the effort goes.** The checks are table stakes: run them, do not admire them. The value of
this session is layer 2. A review whose ANALYSIS section is a paraphrase of its CHECKS tables has not
been done. **Dispatch note for the manager:** this is an analysis job; give it a model and a ceiling
that can carry the ANALYSIS layer, not a numbers-only lane.

**No predetermined outcome.** There is no quota of findings, tweaks or demotions. "No leg is outside
what its backtest predicts and nothing surprised me" is a valid conclusion **if** the ANALYSIS section
shows the falsification attempt behind it (A4). A red week is not a finding; a leg outside its own
expected band, a cost that drifted, or a mechanism that explains several legs is.

**Scope.** Trading + strategy performance (every account, paper and prop included), per-decision
grading, the Claude reviewer and desk grades, and the research pipeline's read/disposition stages.
**Out of scope:** pipeline plumbing / DB integrity / service state (`/health-review` — route
mechanics findings there, do not let them crowd out performance); models (`/ml-review`); editing
`config/` or `src/` (Tier-3 changes are proposed only); running sweeps (`backtesting`).
**Coordination:** read your lane's row in `docs/claude/work/MANAGER-CHECKLIST.json` first; claim
the merge slot with `scripts/ops/claim_merge_slot.py --branch-claim --branch <branch> --held-by
<session-id>` before landing (`.claude/skills/manager/SKILL.md`).

## Layer 0 — grade the previous review's calls (always first)

Open the newest `comms/reviews/performance-review-*.json` (and its markdown under `docs/reviews/`).
For each entry in its `calls[]` (older records without `calls[]`: use `recommended_action` and
`proposed_tweaks[]`, and say so):

1. **Re-run the check the call named** (`check.command`), and apply its `check.rule` as written. Do
   not substitute a new rule.
2. Grade it exactly one way: `hit` (the rule resolved as predicted), `miss` (resolved the other way),
   `unresolved` (its `resolves_when` has not arrived: say what is still missing), `void` (the check
   could not run: name why; a void call is a tooling finding).
3. For any call whose **action** did not happen (no row moved, no unit ran): say why in one line and
   either re-file it with an owner or kill it with a reason. **A call repeated without this line is the
   failure this layer exists to stop** (the M8 sweep, 2026-10-04 and 2026-10-10).
4. Score the batch: `n_calls`, hits, misses, unresolved, void, and the **Brier score** over resolved
   calls using each call's stated `p`. Below 10 resolved calls, report the counts and say the score is
   `INDETERMINATE`. Keep a running series in `prior_calls_scorecard` so calibration is visible across
   reviews.

## Layer 1 — CHECKS (fixed, deterministic, every run)

Every check is computed by a script or a fixed query. Claude's job here is to run it, state its
population, and record a failed check as `could_not_look` (never `0`, never omitted). **Windows are
lifetime, 90d, 30d and 7d for every leg with any closed trade in the last 90 days, never just "since
the last review"**; classes (real_money / mirror / paper / prop) are never pooled. Procedures and
caveats for each pull are in § "Reference" below.

| # | Check | Computed by | Population / note |
|---|---|---|---|
| **C1** | **Per-leg scorecard, four windows**: n, net R (sum, mean), net $ (measured-only beside total), win rate, R per capital-day | `/api/bot/performance` `perStrategy[]` (lifetime, provenance counts) + `scripts/research/giveback_census.py` (R/cap-day; filter the trade dump by `closed_at` per window, its `--since-days` is ignored on the JSON path) | bucket-A rows (§ Bucket records) + flagged C; `pnl_coverage` beside every $ |
| **C2** | **Expected vs realised**: live cumulative R against the leg's own Stage-0 band for the same n | `python3 scripts/research/live_vs_backtest.py` (default Stage-2 legs; `--leg` for Stage-1 legs) | whole history per book; verdict `CONSISTENT / BELOW_BACKTEST / NO_BACKTEST / INSUFFICIENT_N` |
| **C3** | **Decay**: is the recent window drifting from the leg's own lifetime and backtest mean? | interim: C1's 30d and 90d mean R vs lifetime mean R vs the C2 band, and `scripts/research/as_traded_stage0.py` (latest-25% fold) for legs C2 flags. **No CUSUM / sequential test exists yet** (row `PERF-CHECKS-SCORECARD`) | say `interim` until the scorecard lands |
| **C4** | **Attribution**: entry vs exit vs execution vs cost, per flagged leg | `scripts/research/live_bt_trade_join.py` (per-trade join to the backtest bar), `scripts/research/real_money_close_attribution.py` (what actually closed each real-money trade), `giveback_census.py` (peak R vs realised R) | run for every leg C2 or C3 flags and every real-money leg |
| **C5** | **Cost drift**: realised slippage / fee / funding vs the cost the backtest assumed | `scripts/research/realized_slippage.py` (per venue, MEASURED fills) | per venue; cite the cost policy it compares to |
| **C6** | **Baselines**: hold vs act for Claude's in-trade calls; random entry for the desk; leg vs its family siblings | `scripts/ops/live_review_grade.py --live --json`, `scripts/ops/desk_grade.py --live --json`, `scripts/ops/claude_role_grade.py --live` (§ Live review, § Desk); C1 grouped by family | each comparison with n, CI and verdict as the generator prints it |
| **C7** | **TP doctrine** | `python3 scripts/ci/check_tp_doctrine.py` (re-run, never quote) | routings per class |
| **C8** | **Data coverage**: bucket A/B/C split, `pnl_coverage`, `journalTrust`, R-telemetry coverage | `scripts/analysis/classify_paper_records.py` (journal-shaped rows), `/api/bot/trades/closed` `journalTrust` | a leg with low coverage is flagged, not graded |
| **C9** | **Grading**: freshness, and whether the grade carries information (grade cohort vs net R) | `scripts/ci/check_grading_freshness.py`; grade-vs-outcome table over `comms/claude_strategy_scores.jsonl` rows in the 90d window | the rubric is a check, not a judgement; a cohort inversion is `grade_drift` |
| **C10** | **Research pipeline**: queue health, unread results, dispositions | the latest `comms/research/ops/` record (research-ops runs 4×/day) + `python3 scripts/research/research_disposition.py --unread-only` | `superseded_unread` is not a finding; `corpus_unreadable` is `could_not_look` |
| **C11** | **Books and benchmarks**: paper-book tracker append, real-money allocation benchmark, prop trade quality | `scripts/ops/paper_book_tracker.py`, § Real-money allocation benchmark, `scripts/prop/trade_quality_review.py` | as each section states |
| **C12** | **Backlog gate**: every open performance/research pipeline item re-checked | § Draining the backlog | `count_untriaged` MUST be 0 |

A check that needs a tool that does not exist is listed with `could_not_look: no instrument` and the
row that builds it. Do not hand-roll a cruder substitute (`docs/research/RESEARCH-CAPABILITY-INDEX.md`
routes the 300+ research scripts by question).

## Layer 2 — ANALYSIS (Claude's work)

Practice basis: [`docs/research/analytic-skill-design-2026-10-28.md`](../../../docs/research/analytic-skill-design-2026-10-28.md) § 3
and the principles list (T1–T3, M4–M7, R3–R5).

**A1 — Read wide context before you form a view.** For each leg you will discuss: its committed
Stage-0 evidence (`comms/strategy_evidence/<leg>.json`) and the cost basis it was measured on; its
research units and results (`research/queue/`, `research/results/`); the last four performance
reviews and perf-followup records (`comms/reviews/`, `comms/perf_followup/`) and what happened to
their calls (Layer 0); open pipeline items and checklist rows that name it (`grep` the leg); live
review rows on it (`comms/live_review/reviews.jsonl`); regime state; the operator's current priorities
(`docs/claude/work/IDEAS.md`, the latest weekly planning record). **Search before you claim a new
finding**: if the repo already answered the question, cite that answer and move on.

**A2 — Choose the material questions (3–7).** Rank by money at stake, not by this week's P&L:
real-money exposure first, then the size of the deviation from expectation (C2 percentile, C3 drift),
then lifetime $ or R, then mechanisms that touch several legs. A leg with a red week inside its own
band is usually not material. A green leg far above its band is (luck, or a measurement error?).

**A3 — For each question, compete the hypotheses and try to kill your favourite.**
- Write **at least two** explanations, one of which is always *noise* (what the leg's own backtest
  distribution says the chance of this result is at this n), plus the relevant ones of *regime*,
  *cost*, *execution / fidelity*, *decay / overfit*, *measurement artefact*.
- For each, state **what it predicts that the others do not**, in data you can actually read (a
  regime split, a per-trade join, a cost line, a sibling leg, an earlier period).
- **Run that test now** where a script or diag pull answers it (C4–C6 tools, `diag-data`); otherwise
  it becomes a queue unit with the rule written before it runs.
- Record which hypotheses survived, which were eliminated and by what evidence. Your confidence is a
  probability, not an adjective.
- **Judge the residual, not the raw P&L**: take out what the instrument or its regime did (the leg's
  siblings, the asset's own move) and what cost did, before you call anything decay.
- **Count your comparisons.** Reviewing ~30 legs at 5%, about 1.5 will look significant by chance; say
  how many you looked at when you report one that did.
- **Verify against data, not by re-reading your own reasoning.** A claim is checked by a query, a
  script or a diag pull. Rereading your reasoning does not check it.

**A4 — Hunt what does not fit.** List the things that surprised you: a number that contradicts a
prior review, a doc, or the backtest; a leg that behaves unlike its siblings; a cost that moved; a
grade cohort that inverts. For each: an explanation you tested, or an open question with its owner.
If nothing surprised you, say what you checked to look for surprises.

**A5 — Look across legs.** If the same mechanism explains several legs (a bar-timing mismatch, a
cost-model gap, an exit-path giveback), the finding is structural: one tooling or methodology row,
not N leg-level ones (§ Underperformance → diagnose, don't demote, step 3).

**A6 — Decide, ranked by money.** Each finding becomes one entry in `calls[]`:
`claim`, `money_at_stake` (R or $ per month, with the arithmetic), `confidence p` (0–1), `decision`
(what changes, its tier), and a **pre-registered `check`** (`command`, `rule`, `resolves_when`) that
the next review will run in Layer 0. Its ending is a checklist row, a queue unit, a pipeline id, a
`proposed_tweaks[]` entry (Tier-3, with the diagnosis block if it is a demote), or
`no action, because …`. "n is too small" is never an ending on its own: name the n that would answer
it, when it arrives, and the unit or row that waits for it.

**Before you file a decision, run a premortem on it:** assume it is three months later and the change
made money worse, and say why. If the answer is plausible, add it to the call's `check`.

**Reason first, fill the template last.** Write the ANALYSIS in prose, then copy it into the JSON.
Do not draft the analysis inside the JSON fields. Read prior reviews for their **calls and checks**
(Layer 0), not for their conclusions, so that you do not inherit their framing.

**Anti-patterns (each was measured in the 2026-09-24…10-21 reviews):** reading only the window;
restating the CHECKS tables as findings; mechanics findings filed as performance; repeating a prior
call without Layer 0; a "new" finding the repo had already answered; a recommendation that names no
owner and no check.

## Output

Two files, one PR. The markdown is for the operator; the JSON is for the next review and the tools.

**`docs/reviews/<YYYY-MM-DD>-performance-review.md`** — fixed sections, in this order:

```
# Performance review <date> — <one-sentence answer: what most affects money now>
## 0. Prior calls      — table: call · p · check re-run · result (hit/miss/unresolved/void) · action happened?
## 1. CHECKS           — C1–C12 tables; populations and windows; could_not_look listed. Numbers only.
## 2. ANALYSIS         — per material question: hypotheses · test run · result · survivor · p · money at stake
##    Surprises        — what did not fit, and what you did about it
## 3. Decisions        — ranked by money: call · decision · tier · pre-registered check · ending (row/unit/PI id)
## 4. Not done         — what was not run or not pulled, and why
```

**`comms/reviews/performance-review-<stamp>.json`** — conforming to
`comms/schema/performance_review_response.template.json`: the existing fields (§ Reference → Output
fields) plus `checks{}` (C1–C12, each `{status: ok | could_not_look, population, result}`),
`prior_calls_scorecard{}`, `analysis{questions[], surprises[]}` and `calls[]`.

Then the Claude-channel ping (§ Posting) and the hand-off to `/perf-followup`: it **tests** the
`calls[]` and open hypotheses this review could not settle in-session; it does not redo the review.

---

# Reference — procedures the checks and analysis rely on

## Fetching trade data (use the diag-data skill)

This skill is a consumer of `diag-data` + `git-actions`. The required
pulls:

| Pull | Path | Use |
|---|---|---|
| Order packages (decision-level) | `GET /api/bot/order-packages?since=<iso>&limit=200&include_paper=true` (⚠️ the router caps `limit` at **200** and has NO `offset`; a `limit=500` call returns HTTP 422 — page the window per strategy with `&strategy=<name>`, measured 2026-10-04) | one row per decision; **`include_paper=true` so PAPER + PROP packages are graded too, not just real-money** (operator directive 2026-06-22); includes `claudeScore` from prior reviews so dedupe is trivial |
| Closed trades | `GET /api/bot/trades/closed?since=<iso>&limit=200&offset=<n>&include_paper=true` (cap 200 per page; walk `offset`) | realized PnL + exit reason (all funding classes) |
| Paper-book trades | `GET /api/bot/trades/closed?account_id=bybit_1&limit=200&offset=<n>` (walk `offset` to the end) | the diversified paper cohort's closed trades, for the tracker (§ "Diversified paper-book tracker"). `account_id=` returns that account incl. paper; pull the **full** book (no `since`) so the tracker's recency split + cumulative trajectory are correct |
| Journal — order_packages | `journal?table=order_packages&limit=200` (diag) | redundant cross-check; carries `signal_logic` blob |
| Journal — trades | `journal?table=trades&limit=200` (diag) | exit_reason, pnl, position_size |
| Audit tail | `audit?limit=600` (diag) | `*_eval` events for context around each decision |
| M13 insights — summary | `GET /api/bot/insights/summary` | latest AI-analyst summary of the window |
| M13 insights — recent | `GET /api/bot/insights/recent?limit=N` | per-trade analyst notes |
| M13 insights — per strategy | `GET /api/bot/insights/strategy/{name}` (each enabled strategy) | strategy-level analyst note |
| M13 insights — health | `GET /api/bot/insights/health` | data-window + cache age |
| Sweep mirror | `GET /api/bot/backtests/sweeps?limit=5` | trainer-VM sweeps that may justify a tweak proposal |
| **Prop trade quality** | `python3 scripts/prop/trade_quality_review.py` (reads `/api/bot/prop/{fills,tickets}`) | **placed-vs-ticketed** — the cut that separates a BRIDGE problem from a STRATEGY one |

> ⚠️ **BEFORE YOU CONCLUDE ANYTHING FROM A FIELD IN THESE PULLS, read
> `docs/CLAUDE-RULES-CANONICAL.md` § "The row you are reading outranks the
> label in it".** Every pull above returns STORED fields, and a stored field's
> name is a claim about what wrote it, not a measurement (`pnl` is not the
> account's money without `position_size`; `exit_reason` is not the exit
> mechanism without `exit_price`). A journal query IS a measurement — of the journal.
> Cheap mechanical answers: `journalTrust` rides in the `/api/bot/trades/closed`
> response already (⚠️ `no_record` is NOT "trusted"); `scripts/ops/column_provenance.py
> trades.<column>` names every writer; `scripts/ops/strategy_liveness.py <strategy>`
> answers whether a rate you are about to quote is still happening or belongs in
> the past tense.

All pulls go through the **diag relay** (issue label
`vm-diag-request`, title is the path) OR direct HTTPS when the
session is configured for it. Do not SSH; do not ask the operator to
paste anything. If the relay fails, fire `vm-web-api-recover` once
and retry; if still failing, emit a partial review with a note —
**never fabricate**.

### Prop trade quality — run it, and read BOTH halves (P4, 2026-08-23)

`breakout_1` is a **manual bridge**, so its failures split two ways that a win
rate cannot tell apart, and `scripts/prop/trade_quality_review.py` is the cut:

- **BRIDGE** — entry slippage against the *ticketed* entry (signed, **+ = worse**)
  plus how many fills carry no ticket link. This is *"did the human place what
  the bot asked for?"*
- **STRATEGY** — where the exit landed relative to the *ticketed* levels. This
  is *"given a faithful placement, was the trade any good?"*

⚠️ **Do NOT grade this account on ticket answer-rate.** Operator-directed
(2026-08-23): the operator is not always at the terminal when a ticket is live,
so an unanswered ticket is the **expected** shape, and *"that shouldn't be a
metric of success here"*. An unacted ticket is not a finding and must not enter
`proposed_tweaks[]` as one.

⚠️ **`UNCLASSIFIED — no ticket link` is not a manual exit.** The tool keeps the
three unclassified reasons distinct precisely so a review cannot manufacture a
discretionary-exit rate out of missing data; carry them through as unclassified.

⚠️ **Read `near_boundary` and the stated tolerance before quoting the split.**
The exit classification is a judgement about closeness; `--tolerance-bps`
decides it, and the output says how many rows would move if it changed. A split
with rows near the boundary is not robust at that n.

**Batch the diag-labeled rows above into ONE `vm-diag-request` issue.**
Per the `diag-data` skill's default pattern (MB-20260706-CI-MINUTES —
every relay issue is its own billed Actions job; this repo hit its 2,000
min/month cap opening 427 issues in 5.5 days, mostly single-path relay
calls), put every diag path you need this run in the issue **body** as a
JSON array or one-per-line list (e.g. `journal?table=order_packages&limit=200`,
`journal?table=trades&limit=200`, `audit?limit=600` in one issue) instead
of three separate issues. The non-diag `GET /api/bot/*` rows above are
direct HTTPS/no-relay reads when the session is configured for it, so
they don't add to the issue count either way.

## Bucket records before aggregating (artifact pre-filter)

Paper (and some real) records are dominated by **technical artifacts** — intent
reduce/flip legs, netting-guard / hold-policy suppressions, reconciler closes with
no classifiable bracket, orphan flaps, and credential/funding refusals — NOT clean
strategy round-trips. Blending those into win-rate / expectancy makes every
aggregate wrong (a 2026-06-26 window was 0/48 gradeable; see
`docs/audits/order-packages-zero-qty-2026-06-26.md`). Run the pre-filter FIRST:

```
python scripts/analysis/classify_paper_records.py --limit 500 --format md   # on the VM
# or, from a diag-relay trades dump in a sandbox:
python scripts/analysis/classify_paper_records.py --json trades.json --reconstruct
```

⚠️ **Feed it JOURNAL-shaped rows (`/api/diag/journal?table=trades`), not the
`/api/bot/trades/closed` shape.** The classifier keys on `exit_reason`; the
closed-trades endpoint collapses every non-sl/tp/reconciler reason into
`closeReason: "other"`, so fed that shape it buckets every pairs exit as
`unclassified:other` (bucket B). Measured 2026-10-04 on one window: API shape
A=27/B=86/P=0, journal shape A=16/B=1/C=4/P=54 — same trades.

It buckets each record (`src/analysis/paper_record_classifier.py`):

- **A — gradeable** (clean SL/TP / monitor exit): the **only** rows that drive
  per-strategy win-rate / expectancy below.
- **B — technical artifact**: exclude from the scorecard; surface the
  `by_category` counts as a *technical-health* note (route real bugs to the
  health-review backlog), not a strategy verdict.
- **C — reconstructable** (broker-truncated / open-at-edge, but entry+SL+TP
  present): reconstruct the would-be SL/TP outcome from candles
  (`src/analysis/trade_reconstruction.py`, first-touch; `--reconstruct`) →
  `reconstructed_win` / `reconstructed_loss` / `open_at_window_end`. Keep the
  *decision* grade (entry quality, R:R) and fold the reconstructed outcome into
  the strategy read, flagged as reconstructed (intrabar-ambiguous ties resolve
  pessimistically to SL by default).

Report each strategy's A/B/C split so a low win-rate that is really an
artifact-heavy record set is visible, not mistaken for a bad strategy.

## Per-strategy aggregates

Compute the aggregates below over **bucket-A rows only** (plus bucket-C
reconstructed outcomes, flagged). For each strategy with at least one decision in
the window:

- `n_decisions` (order_packages emitted)
- `n_filled` (linked to a non-null `trades` row)
- `n_rejected` (status ∈ `failed_*`)
- `win_rate` (closed_filled rows where `pnl > 0` ÷ closed_filled rows)
- `pnl_total`, `pnl_avg_per_trade`
- `pnl_measured_n` and `pnl_coverage` — **required beside every `pnl_total`**
  (SA-AUD-3, FIX-SA-05). `pnl_measured_n` is the number of closed rows whose
  `provenance.classify_pnl` bucket is MEASURED, `pnl_coverage` is
  `pnl_measured_n ÷ closed rows`, and `pnl_estimated_n` counts the ESTIMATED
  rows. Take them from `/api/bot/performance` `perStrategy[].pnlMeasuredCount`,
  `.pnlCoverage`, `.pnlEstimatedCount`; never recompute over a different
  population. `pnl_total` sums fabricated marks too, so a sum quoted without
  its coverage is a number of unknown provenance.
  ⚠️ **`totalPnlMeasured` is MEASURED+ESTIMATED despite its name.** Quote
  `totalPnlMeasuredOnly` (the MEASURED rows, the same population as
  `pnlMeasuredCount`) beside it and say so when the two disagree in sign: a
  paper window read `totalPnlMeasured` +94,618 over 367 MEASURED rows against
  699 ESTIMATED.
- `avg_hold_seconds` (closed_at − opened_at)
- `rejection_cluster` — most common rejection reason if rejections >
  filled
- `accounts_touched[]` — which accounts traded this strategy

`execution: shadow` strategies are included with the same fields;
their `n_filled` should be 0 (shadow does not place live orders) — if
not, that's an anomaly. Closed-trade attribution joins by
`trades.strategy_name`.

⚠️ **Shadow is not a refusal** (PI-20261010-ERFFUW41-0001). Every
`execution: shadow` dispatch journals an order package with `status:
rejected`, `close_reason: NULL` and reason `dry_run_no_order_placed`
(`src/units/accounts/execute.py`, the non-live rejection row). Count those
as `n_shadow`, never in `n_rejected`, and never list a shadow leg's
packages as "rejected with no recorded cause" — on 2026-10-10 that flagged
`mgc_trend_1h` (16/16 "rejected", all shadow by design) as an anomaly and
would have hidden a real refusal among them. `n_rejected` is the remainder:
a package refused for a cause, on a leg that is `execution: live`.

## Per-decision scoring (PERSISTED, keyed by order package)

> **This rubric is check C9, not analysis** (2026-10-28). Since 2026-09-29 the daily
> `grade-closed-trades` cron writes it for every closed trade. Measured over the 908 rows with
> `reviewed_at` ≥ 2026-09-20 it carried no outcome information (B cohort 32% wins, C cohort 46%,
> D 16%; no A or F; `risk_management: unknown` on 907). Read its cohort-vs-outcome table in C9; do
> not spend the session hand-grading packages. Claude's own judgement of a trade belongs in the
> blind-then-reveal grade below and in the ANALYSIS layer.

The score belongs to the **strategy DECISION**, so it is keyed by
`order_package_id` and persisted to
`comms/claude_strategy_scores.jsonl`, **not** the trade journal
(operator decision 2026-05-25). Cross-reference the executed `trade_id`
(and the trade's outcome) on the row when the package filled; leave it
`null` for shadow / never-filled packages (graded on setup quality
only, `exit_quality: unknown`).

Anchor each grade on the package's `signal_logic` blob
(`order_packages.signal_logic`) — judge the decision against its own
stated edge and (when filled) the fill/exit data, independent of
dollar outcome.

**Letter grade (one per decision):**
- `A` — textbook
- `B` — good, one minor deviation
- `C` — acceptable, EV marginal in hindsight
- `D` — poor (fired against HTF / thin confidence, saved by noise)
- `F` — bad (should not have fired, or should have stayed in)

Mirror to `decision_grade_score` A/B/C/D/F → 4/3/2/1/0 (matches the
`review_journal` family the trainer ingests).

**Three categorical labels (training-friendly):**
- `entry_quality` ∈ `optimal | acceptable | late | early | should_skip | unknown`
- `exit_quality` ∈ `optimal | tp_appropriate | sl_appropriate | premature_exit | held_too_long | unknown`
- `risk_management` ∈ `correct | oversize | undersize | sl_too_tight | sl_too_wide | unknown`

Use `unknown` honestly when the diag bundle lacked context — **do not
fabricate**. With many decisions: grade all closes + ≥1 representative
per rejection cluster; if >20, surface the low-grade cohort (C/D/F)
first and aggregate the A/B cohort in one entry listing the
`order_package_id`s.

**Append discipline:** the jsonl is append-only. Before appending,
skip any `order_package_id` already present so re-runs don't
double-write. Append; never rewrite prior rows. Routine runs only
append packages decided since the last review.

The retroactive backfiller for historical windows is
`scripts/ops/score_order_packages.py` — re-use it, do not reinvent.

**Closed trades are graded per TRADE, on a schedule (JC-SA-01, 2026-09-29).**
`.github/workflows/grade-closed-trades.yml` runs daily and appends one row per
closed, non-backtest trade, keyed on `linked_trade_id` (= that trade's
`trades.id`), via `score_order_packages.py --emit-delta-only --by-trade` — the
same `_grade_package` rubric, no new one. The skip-set for closed trades is
therefore the set of `linked_trade_id`s already present, not the
`order_package_id`s: a package that fans out to several accounts names only one
trade in `order_packages.linked_trade_id`, and a package graded `orphaned`
before its trades existed would otherwise keep that stale row forever
(measured 2026-09-29: 54 of 486 recent closes fell in those two shapes). The
stale package-level rows stay (append-only); the trade rows sit beside them.
`scripts/ci/check_grading_freshness.py` is ALERT-ONLY (2026-09-29): it warns on
a PR when `max(reviewed_at)` is older than 3 days and a daily
`grading-freshness-alert.yml` pings Telegram. A review session no longer needs
to run the grading pass for closed trades — it checks the guard emits no
warning and reads the rows.

**Web / PM session (no DB file):** dispatch the **`grade-closed-trades`**
system-action (Tier-1, `docs/claude/system-actions.md`) instead of pulling the
whole `trades` table through the diag relay. It runs
`score_order_packages.py --emit-delta-only` on the VM (where the DB lives) and
returns only the ungraded delta as NDJSON — bounded and small, unlike a full
`~650KB` table dump against the relay's `~55KB` comment budget. Append the
returned rows to `comms/claude_strategy_scores.jsonl` and commit; a truncated
delta always carries an explicit trailing `{"_delta_summary": ...,
"truncated": true}` marker, never a silent drop. `scripts/ops/
grade_closed_trades_from_diag.py` (feed it a `/api/diag/journal?table=trades`
pull) remains as a documented fallback for when the system-action path itself
is unavailable.

### Blind-then-reveal grade (CJ-3, operator-approved design 2026-10-25)

The rubric rows above are a deterministic Python function, not Claude's judgement
(`docs/plans/ml-claude-distillation-DESIGN.md` § 1.2), so they cannot teach a model. The
**blind-then-reveal grade** is the producer that can: Claude grades a closed trade from a
MASKED packet first (no outcome, nothing after the decision, no symbol, no date, no absolute
price), and only then sees the outcome and grades again. Both grades are recorded. The blind
half is the teacher target for the CJ-2 `claude_judgments` family; the reveal half is a T1
label only; the gap between them is the hindsight-bias diagnostic. The rubric stays as the
cheap fallback for every package.

⚠️ **The reviewing session never writes a blind grade itself.** It has already pulled the
outcomes, so nothing it writes is blind. The grades are written by fresh grader sessions that
are shown only the packet file.

**The run** (tool: `scripts/ops/blind_grade.py`; first run and its numbers:
`comms/claude_judgments/pilot/cj3-pilot-r1/`):

1. Pull `journal?table=trades` and `journal?table=order_packages` with
   `scripts/ops/diag_fetch.sh` (pages of 1000, saved as `trades_<off>.json` / `pk_<off>.json`).
2. `blind_grade.py select --journal DIR --since <date> --n <N> --seed <seed> --out sel.json`:
   one trade per closed package (fan-out siblings counted, not graded), every exclusion
   counted by reason. Report its population line verbatim.
3. `blind_grade.py packets ... --salt <random> --private-out <scratch>`: builds the masked
   packets and **refuses** any packet `find_leaks` flags (symbol, date or epoch, the trade's own
   prices, a raw bar row, an outcome key, a bar at or after the decision). Keep the
   `--private-out` file (the packet-id map and the outcomes) out of the grader's reach until the
   blind pass is pushed.
4. Push an **orphan** branch holding only `BLIND-GRADE-BRIEF.md` and `blind_packets.jsonl`, then
   `create_session` with `source_url` = this repo, `source_revision` = `outcome_branch` = that
   branch, `clone_depth: 1`, model Sonnet. The orphan branch is the blinding: the grader's
   checkout holds no journal, no scores file and no outcome.
5. When `blind_grades.jsonl` lands, add `REVEAL-GRADE-BRIEF.md` + `reveal_packets.jsonl` (the
   blind grade and the outcome per packet) and start a second session the same way.
6. `blind_grade.py ingest --run-dir ... --private ... --run-meta run.json` appends to
   `comms/claude_judgments/blind_grades.jsonl` / `revealed_grades.jsonl` (append-only,
   idempotent by `judgment_id`; schema `comms/schema/claude_judgments.schema.json`). The stores
   hold the judgement and its journal keys only; the family joins the outcome from the journal.
7. Read each grader session's `usage.cost_usd` with `get_session` once it is idle and record
   it in `run.json`: **cost per grade is MEASURED this way, never estimated.**

**Report** (in `anomalies[]`/the PR body until CJ-6 adds a field): n blind and n revealed this
run, cost per grade with its n, the blind-vs-revealed grade shift, and the blind
`expected_r` / `p_win` rank correlation with net R next to the strategy `confidence`'s on the
same trades. At pilot n these are diagnostics only; the pre-registered validation is CJ-4
(n ≥ 150, design § 3.3).

## Verification

The whole point of this skill is that scores match reality:

- For each filled, closed decision in the window, compare the grade
  to the realized outcome:
  - `A`/`B` graded decisions should skew positive on PnL over enough
    samples. An `A`/`B` cohort with negative aggregate PnL → flag as
    `grade_drift` in `anomalies`.
  - `D`/`F` graded decisions that consistently made money → flag the
    same; the grading rubric or the strategy is mis-aligned.
- Cross-check against the M13 analyst's notes for the same trades —
  where the analyst disagrees with the grade, prefer the data over
  either, and note the disagreement in `insights_review[]`.

## M13 insights review

The M13 AI analyst writes cached summaries to
`runtime_logs/insights/*.json` (regenerated every 10 min by
`ict-insights-generator.timer`). Read all four endpoints (or `cache_present:
false` if the generator hasn't run yet) and:

- Verify the analyst's claims against the same trade data you just
  pulled — does it cite a real `trade_id` / `order_package_id`? do
  its win-rate numbers match the aggregates? does it flag the same
  outliers?
- Record disagreements in `insights_review[]` with severity
  `nit | drift | contradiction`.
- If the cache is stale (>1h `cache_age_seconds` during active
  hours), note it as `insights_staleness: watch`. The generator is
  the responsible owner — not this skill — but staleness affects the
  dashboard users see.

## The research pipeline — is anyone READING it? (check C10)

**Operator directive, 2026-08-30:** the review owns *"ensuring there is a healthy pipeline of
backtests, monitoring that they are running properly, reviewing and validating results, running
analyses to infer decisions, and then creating and implementing action items based on the
findings."* Since 2026-10-10 stages 1–3 run 4×/day as `.claude/skills/research-ops/SKILL.md`; this
review **reads its newest record** (`ls -1 comms/research/ops/*.json | sort | tail -1`) and re-derives
nothing it already covers. What stays here:

- **Stage 1 healthy?** `scripts/research/research_queue.py` states (`cleared / underpowered /
  undeclared / unverifiable / not_applicable`) and routes. `not_applicable` is NOT `cleared`; **an
  EMPTY queue is a finding.**
- **Stage 2 running?** `last_dispatched_at` per job against its cadence; a landing check must be
  scoped to the run's OWN stamp (a cumulative store passes vacuously,
  `BL-20260830-E35-LANDING-ASSERTION-IS-VACUOUS-ON-A-CUMULATIVE-CORPUS`).
- **Stage 3 read and validated?** `python3 scripts/research/research_disposition.py --report` and
  `--unread-only`. `superseded_unread` is not a finding; `corpus_unreadable` is *we could not look*.
  **Power first:** a unit below the `n_oos` floor its own job declared (α=0.05, power 0.80, d=0.4 →
  49.06) is `underpowered`, a read whose answer is "this cannot answer the question".
- **Stages 4–5 decide and record** — ANALYSIS-layer work: use the tool
  `docs/research/RESEARCH-CAPABILITY-INDEX.md` routes to the question, then
  `scripts.research.research_disposition.append({...verdict, reason, actions})` (it refuses a vacuous
  reason; `actioned` must name what was done).

## Underperformance → diagnose, don't demote (BINDING — operator directive 2026-07-30)

**A red number is a trigger to diagnose and robustly re-test, NEVER an
instruction to demote.** Reflexively flipping a strategy to `shadow` because
this window looks bad is the failure mode this section exists to kill —
it turns a strategy off at a regime bottom, discards a real edge, and (worst)
learns nothing about *why* it underperformed, so the same mistake recurs. This
is the strategy-level analogue of the `drift-remediation` skill's one rule;
follow it before ANY demote/kill enters `proposed_tweaks[]`.

**Step 0 — always first (operator, 2026-10-15: "that should be a first step for any
underperforming strategy"):** run `python3 scripts/research/live_vs_backtest.py --leg <leg>`
and record its verdict beside the leg. It says whether the live cumulative R is inside the
p5-p95 band the leg's own committed backtest predicts for the same number of trades.
`CONSISTENT` → the result is luck-sized: keep accruing, no tune, no demote proposal (R4
decides at its threshold). `BELOW_BACKTEST` → fidelity/regime problem, proceed to 1-3 and file
the investigation unit. `NO_BACKTEST` → file a backtest unit. `INSUFFICIENT_N` /
`NO_LIVE_TRADES` → say so; do not grade on it.

When a live strategy underperforms in the window, the mandatory next step is a
**root-cause diagnosis + robust re-test**, not a proposal to turn it off:

1. **Robustly re-test the edge** — a walk-forward with **exact live params**
   over the full reconstructable history (the `backtesting` / `exit-refinement`
   harnesses: `scripts/backtest_*.py --emit-trades` →
   `scripts/research/direction_walkforward.py`, contiguous OOS time-folds).
   Answer: did it **ever** have a durable net-of-cost edge, or was it overfit
   from the start? A real multi-fold edge that is negative only in recent folds
   is **regime**, not death.
2. **Attribute the WHY** to one of four causes — the disposition depends on it:
   - **Regime (transient)** — edge is real across history, negative only in the
     current regime slice → **KEEP / regime-tune** (a vol/chop/adx gate to skip
     the adverse regime), do NOT demote. Self-heals when the regime turns.
   - **Cost** — the backtest was net-of-fee only but the live venue adds
     **funding** (perp holds) and **slippage** (tight-stop scalps) the gate never
     modelled → the fix is a **cost/sizing/venue** change (or re-gate net of the
     full cost stack), not a kill. See `docs/research/research-to-results-gap-2026-07-30.md`.
   - **Execution divergence** — live behaviour differs from the idealized
     backtest (a bracket bug, partial fills, a monitor gap) → **fix the bug**;
     the strategy edge was never the problem.
   - **Genuine capability loss / overfit** — no durable edge in the robust
     re-test → *now* a demote is on the table, **as the last resort**.
3. **Ask whether it is STRUCTURAL, not per-strategy.** If the diagnosed cause is
   a **tools/methodology gap** (the cost model omits funding/slippage; the
   graduation gate is net-of-fee only; the paper-mirror signal isn't gated on;
   an offline metric over-selects) then it almost certainly affects **multiple**
   strategies — the fix is to the **tooling/methodology**, filed as its own
   backlog item (health backlog for a tool/CI bug, performance backlog for a
   gate-methodology change), NOT a one-off demote that leaves the structural
   hole open for the next strategy to fall into. **A pattern of demote proposals
   across several strategies is itself the tell that the tooling — not the
   strategies — is what's broken.**

**Fine-tune is the default remediation; demote is interim safety only** — used
only when a leg is *actively harmful now* AND no fine-tune/replacement is ready,
and even then it is a stopgap while the fix is built, never the endpoint. **Every
`proposed_tweaks[]` entry that is a demote/kill MUST carry the completed
diagnosis** (`diagnosis: {reidentified_edge_R, cause ∈ regime|cost|execution|overfit,
robust_retest_ref, why_finetune_insufficient, structural_finding?}`); a demote
proposed without that block is an incomplete review — do not emit it. This
composes with `drift-remediation` (the model analog), `backtesting` /
`exit-refinement` (the re-test harnesses), and the `research-to-results-gap`
memo (the standing structural findings).

## Proposed tweaks

This is the highest-value output of the skill. For each finding that
suggests a concrete parameter change, emit a `proposed_tweaks[]`
entry:

```
{
  "scope": "config/strategies.yaml::<strategy>.<param>",
  "current_value": ...,
  "proposed_value": ...,
  "evidence": "<= 240 chars — what in the window evidence supports this; cite trade_ids / order_package_ids / sweep summaries",
  "tier": 3,
  "risk_note": "<= 160 chars — what could go wrong, what to watch after applying"
}
```

These are **proposals**, not commits. The operator decides. If the
proposal is too uncertain to recommend, file it as a backlog item
instead (§ "Draining the backlog").

## Draining the backlog — a HARD COMPLETION GATE (not a sample)

Open performance/research follow-ups live in `docs/claude/work/PIPELINE.jsonl` (the old
`docs/claude/performance-review-backlog.json` was retired 2026-09-21 and its open rows migrated),
alongside `docs/claude/strategy-refinement-queue.json` (§ "Draining the strategy-refinement queue").
File and update via `scripts.ops.pipeline.append(item, intent="new"|"update")` (mint ids with
`python3 scripts/ops/pipeline.py --mint-id "<ref>"`; never edit by hand; `due_when` and `origin.rerun`
are required).

**A performance-review is NOT complete until every open (non-terminal) pipeline
item whose `origin.ref` traces to a performance-review/research finding —
practically, everything tagged `[performance]` or `[research]` in `what`, plus
any item this session itself filed on a prior run — has been re-checked THIS
run.** Triaging a sample / "the recent few" is a review failure. (Health/ML
findings in the same pipeline are not this skill's to drain — each review
owns re-checking its own population; `state`/`next_action` on the row, not the
tag prefix, decide who acts, but re-reading a health-tagged row you happen to
pass is always fine.)

**Enumerate the FULL open set, then walk it 100%:**

1. **Count first.** `python3 -c "from scripts.ops.pipeline import load; ..."`
   (or `--stats`) over the store, filtered to this skill's population and to
   `state` not in `("done", "killed")`. Record `open_at_start`.
2. **For EACH open item:** re-run `origin.rerun`; then disposition into
   exactly one bucket — **resolved** (append an `update` record with
   `state: "done"` and a `terminal_reason` naming what changed), **fixed_now**
   (an in-scope write — e.g. a proposal filed, this run's own pipeline item),
   **killed** (stale/superseded — `update` with `state: "killed"` and why),
   or **kept_open** (still needs more evidence / a Tier-3 decision — append
   an `update` record carrying this run's re-validation and the blocker, so
   it never sits stale-and-unlooked; `state`/`due_when` may be unchanged but
   the record itself must be fresh).
3. **Append it** (`intent="update"` — never rewrite the file by hand) and
   record EVERY item's disposition in `backlog_drain[]` (array length ==
   `open_at_start`).

**Coverage assertion (the gate).** Emit `backlog_coverage:
{open_at_start, triaged, resolved, fixed_now, closed_stale, kept_open,
count_untriaged}`. **`count_untriaged` MUST be 0.** A review with
`count_untriaged > 0` is INCOMPLETE — do not post the ping or report it
done. The ping cites `X/Y backlog items triaged`.

New backlog items added by this skill are for **performance
follow-ups only** (not system bugs — those go to the health backlog).
Each item carries `id`, `opened_at`, `opened_by`, `source`, `title`,
`description`, `tier` (typically 3), `trigger_condition`,
`resolution_criteria`, `status` ∈ `open | resolved | invalid |
snoozed`.

### Draining the strategy-refinement queue

Also drain **`docs/claude/strategy-refinement-queue.json`** — the active
pipeline for **`paper_ready`** cells (`docs/strategy-readiness-ladder.md`):
backtested edges that are net-of-fee positive but **not yet fold-robust**, so
they run on demo for soak AND are queued for *refinement* rather than shelved.
For each open item:

1. Triage: has its refinement hypothesis been tested yet? did a fresh
   backtest / k-fold land?
2. **Act on what you can** — if a re-sweep exists, re-tier with
   `scripts/ops/classify_strategy_tier.py` and either advance the cell
   (a `paper_ready → live_money_ready` Tier-3 proposal in `proposed_tweaks[]`,
   with the gate evidence), iterate the hypothesis, or mark it `rejected`
   with the evidence. If the refinement still needs a backtest, that's the
   `backtesting` skill — note it and leave the item `open`.
3. Edit the queue file: update `tier` / `status` / append evidence. Record
   each action in `backlog_drain[]` (tag the item id `SRQ-…`).

This is the onboarding half of the lifecycle; the M7 review gate
(`/api/bot/strategies/{name}/review`) handles already-live strategies. A
`paper_ready` cell is a **work item**, not a dead backtest — the whole point
is to refine the marginal-but-real edges instead of only ever shipping the
absolute winners.

## Diversified paper-book tracker

The 10-cell diversified alt book
(`config/research/diversified_paper_book.yaml`) was banked 2026-06-18 as
robustly +OOS in backtest, with one blemish: 2026-YTD was flat in
backtest. All 10 cells run **enabled + `execution: live` on the
`bybit_1` PAPER account**, so the live paper trade book is the standing
evidence for whether that flatness is **alpha-decay or noise**. This
step keeps that watch alive across reviews.

Every run:

1. **Fetch the cohort's closed trades** — the `account_id=bybit_1` pull
   above (full book, no `since`).
2. **Append a snapshot + read the delta** — pipe the rows to the
   tracker:
   ```
   python3 scripts/ops/paper_book_tracker.py --trades-json <rows.json>
   ```
   It filters to the 10 cohort cells, computes book + per-cell +
   per-family + recency-split aggregates, appends one snapshot line to
   `docs/research/paper-book-tracker.jsonl`, and prints the Δ vs the
   previous snapshot + a `decay_flag`. (Pass `--no-append` only for a
   dry read.)
3. **Review what's new** — judge the live paper trajectory:
   - Is the **book net-positive** and is the **recent window** holding
     up vs prior (decay watch)? A `decay_flag` (recent window
     net-negative + mean below floor over ≥10 trades) is a **caution**
     signal, not proof — note it and keep watching.
   - **Per-cell / per-family**: any cell that's a sustained net loser on
     live paper (not just a flat week) is a candidate for a pipeline
     item (`docs/claude/work/PIPELINE.jsonl`) — a future tweak or a
     `DEMOTE_SHADOW`/`KILL` proposal (Tier-3, *proposed* not enacted).
   - Cross-check against the backtest expectation (the families were
     complementary: trend wants low-moderate ADX, pullback wants high
     ADX). A family inverting its expected sign on live paper is a real
     finding.
4. **Record it** in the response under `paper_book_tracker` (§ Output)
   and, if a cell/family warrants follow-up, add a `SRQ-…` item to the
   backlog.

The append is part of the run, not optional.

The tracker file is append-only history — **never rewrite prior
snapshot lines** (same discipline as the scores jsonl). Updating the
cohort itself (adding/removing a cell) is a Tier-3 config change to
`accounts.yaml`/`strategies.yaml` — propose it, don't edit the yaml
here; the cohort yaml is kept in sync *after* that lands.

## Real-money allocation benchmark (RECURRING)

**Operator directive (2026-07-15, set when `alpaca_live` was shelved to
`dry_run`):** the bar for putting a strategy on a **live real-money**
account is not "is it profitable in paper" — it's **"does adding it
actually improve the live real-money book's *risk-adjusted* outcome,
including via diversification across changing regimes, or is the capital
better left where it is (today: bybit-only)?"** A strategy that's
paper-green but adds nothing over the incumbent book — or worse, just
correlates with it — does not earn real-money capital. Run this every
review while any real-money account is shelved or any candidate is
queued for live promotion.

**The benchmark:**

1. **Incumbent book** = the current live real-money allocation (today
   `bybit_2`; `alpaca_live` is `dry_run` as of 2026-07-15). Pull its
   closed trades (`account_id=bybit_2`, real-money) over the window +
   the longer trailing window, risk-normalized to **R** so it compares
   across instruments.
2. **Candidate portfolio** = the ready-for-live strategies not currently
   on live real money — principally the shelved `alpaca_live` ETF sleeve.
   Its **paper-equivalent** record is the proxy: `alpaca_live` in
   `dry_run` still logs order-packages but does **not** fill, so use
   `alpaca_paper` fills for the same strategies as the realistic
   execution proxy (state this explicitly — it's a paper proxy, not live
   fills). Health-review's soak-surfacing (§ its "Soak decisions due")
   is the readiness signal for *which* candidates are eligible.
3. **Compare on risk-adjusted terms, not raw $** — expectancy-R, profit
   factor, and **max drawdown**, since paper $ notionals are inflated
   and not comparable to real-money $.
4. **Weigh the diversification benefit explicitly** — the operator's key
   question. Estimate the **correlation / co-drawdown** between the
   candidate sleeve's equity curve and the incumbent's across the
   window's regime shifts. A *decorrelated* sleeve can earn its place
   even with lower standalone expectancy if it **reduces blended
   drawdown / smooths equity** when the incumbent's regime turns
   unfavorable. Conversely a high-correlation sleeve that just tracks
   bybit adds risk without diversification — it does not clear the bar.
5. **Verdict (proposed, never enacted here):**
   - **Improves the blended book** (higher expectancy-R at equal-or-lower
     drawdown, OR materially lower drawdown via decorrelation) → surface
     a **Tier-3 re-arm / promotion proposal** with the evidence (the
     `mode: live` flip is operator-gated, shipped as a PR like the
     shelve — never flipped here).
   - **Doesn't clear the bar** → keep it shelved; capital stays where it
     is. Say so plainly with the numbers.

Record the verdict each run under `real_money_allocation_benchmark`
(§ Output), and add/refresh a `SRQ-…` backlog item so the decision is
tracked between reviews. This is **analysis + a proposed Tier-3 change**
only — it never edits `accounts.yaml`/`strategies.yaml`.

## Posting to the Claude channel

Every performance-review run ends with a one-line update to
`@claude_ict_comms_bot`. Primary path:

```
action: send-ping
target: claude
priority: normal      # 'high' only if a strategy is consistently F-grading on live capital
message: /performance-review — <window>: <total decisions>, <win_rate>% WR, $<pnl>. <N> low-grade (D/F). <K> tweaks proposed. Top mover: <strategy>.
```

≤200 chars. Cite numbers. Point at the response JSON for detail.
Fallback path: append to `docs/claude/pending-pings.jsonl` and commit.
Full contract: `docs/claude/telegram-pings.md`.

## Live review (LTR-5, operator 2026-10-25 — every review grades the reviewer too)

`/live-trade-review` records one row per open package per review in
`comms/live_review/reviews.jsonl`. Nothing about those calls is graded until their trade closes, so this
section does it. **Run it every review:**

```bash
python3 scripts/ops/live_review_grade.py --live --since <window_start>            # the markdown section
python3 scripts/ops/live_review_grade.py --live --since <window_start> --json     # paste into live_review{}
python3 scripts/ops/live_review_grade.py --live --write-outcomes                  # append computed rows for newly CLOSED trades
```

It projects over the canonical records (reviews joined to the journal on `order_package_id`/`trade_id`) and
prices each call through `scripts/research/live_review_counterfactual.py`: the package's bracket and trail
replayed on real exchange candles from the review time, with and without the call, **net of the full cost
stack** (`execution_costs.resolve_cost_policy` slippage + the trade's recorded fee/funding legs). It keeps no
store of its own; `--write-outcomes` appends to `comms/live_review/outcomes.jsonl` (idempotent by `review_id`),
the file the CJ-2 dataset joins on.

**State the population first, in this order:** `n reviews on n packages → n altering calls → n priced →
n could_not_price (by reason)`. The reasons are named, not collapsed: `trade_open`, `no_candles`,
`replay_mismatch` (the replay could not reproduce the trade's own exit within 0.15 R, so its counterfactual is
not trusted), `hold_replay_unresolved`, `no_package_row`. A hold / no_recommendation / flag_mechanics review
changes no path: its `delta_r` is 0 by construction, never a measurement, and it is graded only as an outcome
row once its trade closes. **n=0 priced is a finding to report as n=0**, never as "0 R".

Report, from the generator's output (do not hand-compute):

1. **Per action class** — n, applied vs recommended-only, mean and worst `delta_r` (positive = the call beat
   holding), hit rate.
2. **The reviewer's grade** — calibration of `judgement_confidence` (Brier + reliability by bucket) **stratified
   by `evidence_source`** (`table` vs `judgement`), so the models learn how much weight a thin-cell judgement
   deserves. Below 10 priced calls a stratum reads `INDETERMINATE`; say so, do not narrate a trend. Also apply
   the A–F rubric to the review row, keyed by `review_id` in `comms/claude_strategy_scores.jsonl`.
3. **Q1 — live 0.25 R policy vs the shadow 0.5 R policy**, on the same reviews: n, paired `dR`, and a verdict
   that is `INDETERMINATE` unless at least 10 reviews are discordant and the 95% interval excludes 0 (rule
   registered in the generator before any run). A judgement-basis tighten carries no ex-ante cost, so neither
   policy flag is decided for it: it is counted as `policy_undefined`, not forced into the comparison.
4. **Touched vs untouched** — the generator lists `touched_packages` (a call was applied). Live-vs-backtest
   verdicts and every Gate-2 demotion read must **split touched from untouched**: a mandate-tightened exit is
   no longer the exit Stage 0 validated.
5. **The loop's alarm** — if applied actions net `delta_r < 0` over 20 or more priced applies, propose
   `apply_mode: recommend` in `proposed_tweaks[]` (a proposal; never a flip).

A tighten that is `priced` on a `replay_matches_realised` row is solid; one on an `unvalidated` row (an applied
call has no untouched realised path to check) is flagged as such. Say which you are quoting.

**CLAUDE-GRADE-LOOP additions (operator 2026-10-26: "grading of Claude decisions … should be part of the
performance review").** The same generator also reports, and you quote each with its n:

6. **Hold vs close-at-review** (`hold_vs_close`): a hold changes no path, so it is graded against what it
   rejected, closing at the review's mark. ESTIMATED and conservative against the reviewer (the close side
   carries no cost).
7. **Calibration by action class** (`calibration`, rules in `scripts/ops/claude_calibration.py`): per
   `tighten_sl/…` and `hold/…` stratum, Brier vs the base-rate reference, skill, the over-confidence gap,
   and a verdict `CALIBRATED | OVERCONFIDENT | UNDERCONFIDENT | NO_SKILL | INDETERMINATE`. An
   `OVERCONFIDENT` stratum is a weakness row for `/perf-followup` Track 2 (it becomes a brief amendment).
8. **By contract version** (`by_skill_sha`): every figure split by the `skill_sha` the reviewer recorded.
   Never quote a pooled figure across versions when two versions each have priced calls.
9. **Use rules** (`use_rules`, the generalised alarm): per altering action class, `PROPOSE_NARROW` /
   `PROPOSE_WIDEN` / `HOLD_SCOPE`. A `PROPOSE_*` goes in `proposed_tweaks[]` as a mandate-scope proposal for
   the operator (rule (a) in `docs/plans/ml-claude-distillation-DESIGN.md` § 3.7); never a flip.

## Desk (CLAUDE-GRADE-LOOP — the desk is graded like the reviewer)

Every desk decision (`comms/desk/decisions.jsonl`) is graded against its own priced outcome, against a
random-entry baseline from its own packet, and against what the **system** traded in the same window.
**Run it every review:**

```bash
python3 scripts/ops/desk_grade.py --live --since <window_start>            # the markdown section
python3 scripts/ops/desk_grade.py --live --since <window_start> --json     # paste into desk{}
```

It projects over the canonical records (decisions ⨝ `comms/desk/outcomes.jsonl` on `decision_id` ⨝ the
decision's packet); it keeps no store. `--live` adds the system leg read (the journal via diag); without it
the system row reads `not_requested`, and a failed read reads `could_not_look`, never 0.

**State the population first:** `n decisions by role/action → n proposals → n priced / expired unfilled /
awaiting → n out-of-sample and gate-eligible → n no_trade (not computable until DESK-20)`. Then report, from
the generator's output (do not hand-compute):

1. **The three comparisons**, each with n, mean, CI95 and verdict: desk proposals net of cost; desk minus the
   packet's random-entry baseline (paired, nearest horizon; state the R-unit limit the generator prints);
   desk minus the system legs on the same universe and window (unpaired). `EDGE` needs n ≥ 30 and a 95%
   interval excluding 0, out of sample.
2. **Calibration**: `p_hit` vs TP hit (Brier, reference, gap, verdict); the `confidence` category vs net R
   (`MONOTONE` / `NOT_MONOTONE` / `INDETERMINATE`); the optimism gap `expected_r_net − realised`.
3. **By brief version** (`skill_sha` = the DESK-BRIEF.md blob): never pooled.
4. **Promotion gate (rule (b))**: `NOT_YET (failing …)` or `ELIGIBLE_TO_PROPOSE`. Eligible is a proposal in
   `proposed_tweaks[]` for the operator, never a stage change.

n=0 priced is reported as n=0. A `no_trade`-only window is graded by the roll-up below (the no_trade
counterfactual), not by `desk_grade.py`, which still counts it `not_computable` until DESK-20.

### Per-role roll-up (DESK-9-GRADING) — runs on a schedule, you read it

```bash
python3 scripts/ops/claude_role_grade.py --live            # markdown: one row per (role, action class)
cat comms/desk/role_grade.json                             # the scheduled snapshot (hourly desk-decisions-mirror)
```

The snapshot is written by the existing hourly `desk-decisions-mirror` workflow (and the closed-review pricing by
`live-review-rows-mirror`: `live_review_grade.py --live --write-outcomes`), so grading does **not** wait for a review to
remember it; weekly-audit C13 fails if the snapshot is more than 2 days old. In the review: quote each row's
`n_recorded / n_graded / n_not_yet_graded (+ breakdown) / n_needed / state / eta_earliest` as printed. `state`
is `graded | insufficient_n | no_data | not_gradeable_by_design | could_not_look`: **a class that could not be
graded is never reported as a grade**, and `eta_earliest` assumes every new call prices (say so). The `no_trade`
row is the desk's abstention priced against what entering would have done on the real forward path, net of cost:
its **verdict basis is the desk's own best listed-and-declined candidate** (`abstain_value`, independent 12-bar
windows, n ≥ 20 — it can fail); the random-entry line is ~ the round-trip cost by symmetry and is context only; the
hindsight best cell is an upper bound, never graded. The adopted CLAUDE-GRADE-LOOP rule is applied from the
`use_rules` the Live review section already prints (per class, n ≥ 20 graded): proposals only.

## Output fields (JSON) — the existing fields, kept

Emit a single JSON object conforming to
`comms/schema/performance_review_response.template.json`:

- `reviewed_at`, `reviewer: "claude"`, `window_start`, `window_end`.
- `overall_assessment` ∈ `healthy | caution | investigate`.
- `strategy_performance[]` — per-strategy aggregates (§ above).
- `trade_decision_grades[]` — one entry per scored order package
  (**REQUIRED** when the window held decisions; `[]` only when truly
  empty).
- `insights_review[]` — agreements/disagreements with the M13 cache.
- `proposed_tweaks[]` — Tier-3 proposals with evidence.
- `backlog_drain[]` — actions taken on this skill's open
  `docs/claude/work/PIPELINE.jsonl` items (§ "Draining the backlog").
- `paper_book_tracker` — the diversified paper-book read: this run's
  snapshot summary (book `n`/`net_usd`/`win_rate`, recent-vs-prior,
  per-family net, `decay_flag`), the Δ vs the previous snapshot, and a
  one-line `assessment` (decay / noise / healthy). `null` only if the
  cohort pull failed (note it in `anomalies[]`).
- `real_money_allocation_benchmark` — the recurring benchmark verdict
  (§ "Real-money allocation benchmark"): `{incumbent, candidate,
  incumbent_expectancy_r, candidate_expectancy_r, incumbent_max_dd,
  candidate_max_dd, correlation_estimate, diversifies (bool),
  verdict ∈ improves|neutral|does_not_clear, proposed_action, note}`.
  `note` states the paper-proxy caveat. `null` (with an `anomalies[]`
  line) only when there's no live real-money book AND no queued
  candidate to benchmark.
- `live_review` — the Live review section above (population, per-action
  class, Q1 verdict, calibration by evidence source, applied alarm). `null`
  (with an `anomalies[]` line) only when the grader could not run.
- `anomalies[]` — free-form notable items (grade drift, unexpected
  attribution, etc.).
- `recommended_action`, `operator_attention_required`.

Each `note`/`rationale` ≤240 chars; cite `order_package_id`,
`trade_id`, strategy name, and numbers so the operator can verify
fast.
- **New 2026-10-28:** `checks{}` (C1–C12: `{status: ok | could_not_look, population, result}`),
  `prior_calls_scorecard{n_calls, hit, miss, unresolved, void, brier, series[]}`, `analysis{questions[
  {question, money_at_stake, hypotheses[{name, predicts, test, result: survived | eliminated | untested}],
  conclusion, p}], surprises[]}`, and `calls[]` (`{id, claim, p, money_at_stake, decision, tier, check:
  {command, rule, resolves_when}, ending}`). Layer 0 of the next review reads `calls[]`.

## Hand-off: `/perf-followup` (operator, 2026-10-10)

Once the review's PR is up, say in the PR body and the ping that it **hands off to `/perf-followup`**
(`.claude/skills/perf-followup/SKILL.md`). The manager dispatches it as one lane when this PR merges; you
do not run it here. Its input is this review's `calls[]` and `analysis.questions[]`: it **tests** the
hypotheses this session could not settle (queue units with rules registered before they run), extrapolates
them to other legs, and runs the portfolio track. It does not redo this review's checks or analysis.

## What you DO write (and what you don't)

**Write:**
- Append per-decision scores to `comms/claude_strategy_scores.jsonl`
  (keyed by `order_package_id`, dedup-on-append).
- Append blind-then-reveal grades to `comms/claude_judgments/blind_grades.jsonl` /
  `revealed_grades.jsonl`, only through `scripts/ops/blind_grade.py ingest`
  (§ "Blind-then-reveal grade").
- File/update performance + research follow-ups in
  `docs/claude/work/PIPELINE.jsonl` via `scripts.ops.pipeline.append`
  (never by hand — see § "Draining the backlog", corrected 2026-09-24).
- Append a snapshot line to `docs/research/paper-book-tracker.jsonl`
  (append-only, via `paper_book_tracker.py`; never rewrite prior lines).
- Post the Claude-channel ping (via `send-ping` system-action; fall
  back to `docs/claude/pending-pings.jsonl`).
- The read-only diag-trigger issues (`vm-diag-request`,
  `vm-web-api-recover`) — they auto-close.

**Do NOT:**
- Touch `src/`, `config/`, or any live-path file. **No exceptions** —
  param changes go in `proposed_tweaks[]` for operator approval.
- Edit `docs/claude/work/MANAGER-CHECKLIST.json` — that register is the
  manager's, not a lane's (CLAUDE.md § "How work is organised").
- Touch the M13 insights cache (`runtime_logs/insights/*.json`) —
  that's the generator's territory; this skill only reads it.
- Ask the operator to paste/download/SSH a snapshot — autonomy
  violation. Pull it yourself.
- Ask scoping questions — the scope is fixed (this file).

## If the relays are unreachable

Same rule as `/health-review`: if the live diag relay fails even
after a `vm-web-api-recover` retry, emit a partial review with
`api_errors` in `anomalies[]`, `operator_attention_required: true`,
and a note that the live pull couldn't be performed. Still drain the
backlog and still post the Claude-channel ping (those are repo-local).
Do not synthesize trade data without evidence.
