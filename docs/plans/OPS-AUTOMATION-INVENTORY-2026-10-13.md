# Ops automation inventory — 2026-10-13

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · nobody has verified this document's status.
> **Authorizes nothing and builds nothing.** Inventory and plan only; every build below is a checklist row `AUTO-*`.

**Goal (operator, 2026-10-13, verbatim from `STRATEGY-REALIGN`):** move ongoing ops off Claude so Claude effort goes to research, and plan *"any and all functions that could be automated to take the pressure off the claude budget"*. Accepted starting split: ~10% ops / ~20% builds / ~70% research.

## 0. Read this first — what is measured and what is not

| Fact | Status |
|---|---|
| Manager session `session_01G16FfyYSmDPQuuW55BuTmK`: **$153 over ~38 h on Opus** (as of 07:42Z 2026-10-13) = **$4.03/h** | MEASURED (dispatch brief; session metadata) |
| Lane `spend_usd` on checklist rows | MEASURED, but on a **minority of rows** (§B) |
| Everything labelled *est.* — per-function manager cost shares, savings per automation | **ESTIMATED by this lane.** No per-function instrumentation exists. Treat as ±50%. |
| Dollars are **API-equivalent**, not plan allowance. The $200 Max allowance is a model-weighted **percent** (`A1` notes); tokens-per-percent moves with the Opus/Sonnet mix. Dollars compare functions; they do not convert to allowance percent. | Caveat from `A1` |
| Weekly allowance in dollars | **Unknown / not readable from the repo** (A1: "do not invent a denominator"). Shares below are shares of *recorded spend*. |

Nothing here was verified against the live VM or Actions run history (read-only repo lane): cadences come from `cron:` lines, `.timer` files and the trigger list; "does it still fire" was not checked.

## A. Inventory of recurring operational functions

### A1. Claude routines (list_triggers, 5 enabled recurring) — **all spend Claude**

| # | Function | Cadence | Runs as | Model | Cost/wk |
|---|---|---|---|---|---|
| R1 | **Manager review**: fetch the daily work report, disposition every digest item, ask_operator, due items, soaks; record `last_review` | 05:52Z, 17:52Z (14/wk) | fires into the **manager session** | Opus | est. $120–170 (≈25% of manager anchor) |
| R2 | **Manager lane check-in**: list sessions, read each lane's status, handle blocked/idle/over-ceiling, arm auto-merge, archive finished, record spend | every 6 h (28/wk; was 3 h) | manager session | Opus | est. $100–140 (≈20%) |
| R3 | **Research-ops dispatch**: register row, `create_session` Sonnet lane running the `research-ops` skill, archive it, record spend | 02:47/08:47/14:47/20:47Z (28/wk) | manager session (cheap) + a Sonnet lane | Opus (dispatch) + Sonnet (lane) | lane **MEASURED avg $3.36** over 5 recorded passes (2.50–4.32) → **$94/wk**; dispatch overhead is inside the manager anchor |
| R4 | **Weekly research-planning** (`PLANNING.md` §4: throughput, grade landed results, re-weight themes, draft units, retire stale, one-page plan) | Mon 06:57Z | fresh session | n/a (prompt budget "~$15") | ≤ $15 (budget stated, not measured) |
| R5 | **Weekly planning dialogue** (Wed 09:44Z, week review / roadmap / schedule / workplan) | weekly | manager session | Opus | est. $20–40 (prep + dialogue) |

**Not scheduled:** `/health-review`, `/performance-review` (+ `/perf-followup`), `/ml-review`, the frontier scan. None appears among the 5 enabled recurring triggers; rows show them dispatched by hand (e.g. `PERF-REVIEW-W41` $3, `ML-REVIEW-20261004` $16 Fable, `ML-REVIEW` $8.17). The skills say Sunday for ml-review and the frontier scan. Estimate for the lot: **$30–60/wk**, runs only when the manager remembers (see Missing, M1).

### A2. Manager manual acts — the babysitting (all Opus, all inside the $4.03/h anchor)

Source: `PACE-W40` notes, `manager` SKILL § lane check-in / daily review, `STRATEGY-REALIGN`. Shares are **est.**; the only measured number is the total.

| # | Act | Evidence it is manual today | Est. share of manager spend |
|---|---|---|---|
| M-a | Merge `main` into stale/behind open PRs ("Manager merged main into 24 open PRs: 21 clean via GitHub update-branch…", 10-08) | PACE-W40 10-08 | 8% |
| M-b | Re-run cancelled/dead `pytest-run` jobs; diagnose red CI (e.g. 10-13: main pytest red 02:01Z–04:58Z from a hard-coded date vs `now()` in `tests/test_prop_tracking.py`) | PACE-W40 10-13 | 7% |
| M-c | Write/repair landing + automerge + merge-slot files (three files per PR; wrong slug is "the commonest R11 failure" per `.github/pr-landing/README.md`) | pr-landing README; PACE 10-08 (three guards rejected inherited landing files; PR rebuilt) | 4% |
| M-d | Acknowledge per-PR GitHub activity events (reviews, CI, merges) for subscribed PRs | system prompt: every subscribed PR event wakes the session | 8% (low confidence) |
| M-e | Nudge/recover lanes that missed their wake-up (10-13 02:14Z: "Wake contract FAILED for both lanes … ~2h lag") | PACE-W40 | 4% |
| M-f | Record spend on PACE rows, archive finished lanes (one note line per lane, 13+ lanes/day on 10-12) | PACE-W40 10-12 12:25Z / 17:55Z | 6% |
| M-g | Manager-side checklist edits/pushes after every event (`checklist.py set`, push to main so the Workflow page is current) | CLAUDE.md "Push, then answer" | 6% |
| M-h | Reading digests/report items and dispositioning each (part of R1) | manager SKILL "daily review" | in R1 |
| M-i | Supervising `landed_unproven` rows (115 on main) — no mechanism closes them | checklist state counts: 261 done, 115 landed_unproven, 85 queued, 8 in_flight | 5% |
| M-j | Operator dialogue, dispatch decisions, priority calls | the part that **should** stay Opus | ~15% |
| | **Sum of mechanical acts (M-a…M-i incl. R1/R2 mechanical parts)** | | **~85% ≈ $575/wk** if the anchor is sustained |

Anchor arithmetic: $153 / 38 h = $4.03/h → ×168 h = **$676/wk** if the manager runs continuously (extrapolation; the session may be idle part of the time, so this is an upper estimate).

### A3. GitHub Actions — scheduled (36 workflows with cron, 169 workflow files in all) — **$0 Claude**

Model: none. Only `llm-delegate.yml` calls an LLM (external, $0 by design).

| Group | Workflows | Cadence |
|---|---|---|
| Reconcile / broker truth | `account-broker-reconcile`, `broker-bracket-reconcile`, `broker-truth-freshness`, `mirror-orphan-watch`, `alpaca-settlement-soak-watch` | 6-hourly; daily; weekdays 14:30Z |
| Health / watch | `health-snapshot` (6h), `main-tree-watch` (hourly :37), `dashboard-edge-watch` (hourly :12), `stale-automation-sweep` (2h), `schedule-keeper` (hourly + 6h paging run), `trainer-capture-watch` (6h), `macro-producer-liveness`, `grading-freshness-alert`, `diag-relay-sweep` (daily) |
| Grading / gates | `grade-closed-trades`, `r4-demotion-gate`, `exit-cell-mandate`, `live-replay-parity`, `replay-pregate-nightly`, `strategy-review-packets`, `soak-book-grade-weekly` | daily; weekly Sun |
| Research queue | `research-queue-dispatch` (hourly :20), `research-queue-grade` (6h), `research-queue-replenish` (daily 05:50Z), `research-loss-detector` (12h), `research-backtest-augment` (Mon) | |
| Data producers | `econ-calendar-produce`, `econ-event-study`, `macro-valuation-snapshot` | daily/weekly |
| Hygiene | `purge-artifacts` (daily), `gitleaks-history-weekly`, `doc-audit-weekly` (Mon), `oci-inventory` (Mon) | |

Event-driven (label/PR/`workflow_dispatch`, 113 files reference issues/labels, 31 reference `pull_request`): `claude-pr-automerge`, `pr-opener`, `pytest-run`/`guards`, `system-actions` (label-dispatched tiered mutations), `ci-settled`, the diag/trainer relays, `delete-merged-branches`, `prune-landed-branches`, `pr-landing-hold-merge-alarm`, `armed-branch-push-watch`, `external-issue-alert`, `external-comment-alert`. Several coordination workflows were **retired 2026-09-21** (`session-reaper`, `pr-queue-watch`, `reconcile-open-prs`, `due-list`, `work-decision-commit`, `merge-claim-audit`) — crons commented out. **What no workflow does** is anything that needs a Claude session's metadata (spend, session state, archive): Actions cannot call the session MCP tools, which bounds §C.

### A4. VM timers (deploy/*.timer, 24 live-VM + 9 trainer-VM) — **$0 Claude**

Live VM (examples; cadence from `OnCalendar`): fills pulls (Bybit `:20` hourly, Alpaca `:23`, IB `:17`, Bybit funding 00:35, MES IBKR 23:30), `ict-work-digest` (hourly, Telegram), `ict-hourly-snapshot` (hourly), `ict-work-report` (05:30Z daily — the report R1 reads), `ict-heartbeat` (13:00Z), `ict-prop-feed` (every 5 min), `ict-research-results-gate` (07:12Z), `ict-ib-gateway-reset` (06:05Z) + watchdog, `ict-liveness-watchdog`, `ict-web-api-watchdog`, `ict-db-integrity`, `ict-devnull-guard`, `ict-git-sync` (~5 min), `ict-insights-generator(-strategies)` (cache refresh), `ict-shadow-log-rotate`.
Trainer VM: `ict-trainer` (daily), `ict-trainer-catchup` (05:00Z), `ict-drift-retrain` (hourly), `ict-promotion-readiness` (04:00Z), `ict-candle-refresh` (03:20Z), `ict-pm-snapshot` (6-hourly), `ict-offload-drain` (20 min, unarmed), `ict-trainer-disk-alarm` (hourly), `ict-trainer-git-sync`, `ict-trainer-forecast`, `ict-trainer-publish`.

### A5. Lane-run ops, recorded in checklist rows (14-day window, §B)

Sonnet lanes dispatched for backlog drains, reconcile rescues, small fixes (`BACKLOG-BURNDOWN-2` $38, `A8` backlog rescue $75.83, `DECIDE-AUTO` $11.52, `ROADMAP-LOOP` $9.85, `TEST-DATEBOMB-PROP-TRACKING` $1.07, …).

## B. Spend split, last 14 days (2026-09-29 → 2026-10-13)

**Population (stated first).** Checklist rows: **492** parsed files; **256** have `updated_at` ≥ 2026-09-29 (a row *touched* in the window, not necessarily *spent* in it — a recorded `spend_usd` has no timestamp of its own, so this is a proxy). Of those 256, **67 (26%) carry a numeric `spend_usd`; 189 (74%) carry none.** Recorded total on those 67 rows: **$922.08**. All-time recorded: 170 rows, $2,989.21 (largest, B1 $435 and B2 $229, were last updated before the window and are excluded). The manager session is **not a row**: it is added separately from the measured anchor.

**Bucketing method.** Keyword rule on row id + title + phase (script run in this lane; ops = pace/research-ops/triage/reconcile/burn-down/test-fix/ci rows; research = research/backtest/queue/strategy/regime/exit-lever rows; builds = infra/feature phases W6/E/A/B/C/CA/…; unknown = rest). It is a heuristic; a handful of rows are arguable (`A8` backlog rescue counted ops).

| Bucket | Rows touched | Rows with spend | Recorded lane $ (14 d) | + manager (est.) | **Total** | **Share** |
|---|---|---|---|---|---|---|
| ops | 41 | 10 | $118.92 | $1,150 | **$1,269** | **55.8%** |
| builds | 79 | 28 | $416.06 | — | **$416** | **18.3%** |
| research | 111 | 24 | $371.24 | — | **$371** | **16.3%** |
| unknown | 25 | 5 | $15.86 | $203 | **$219** | **9.6%** |
| **total** | 256 | 67 | $922.08 | $1,353 | **$2,275** | 100% |

Manager line = $4.03/h × 336 h (14 d) = $1,353 **extrapolated from a 38 h measurement, upper estimate**; 85% put in ops (A2 sum), 15% in unknown (decisions/dispatch that could be research- or build-directed). Arithmetic check: 1,269 + 416 + 371 + 219 = 2,275 ✓.

Model mix of the recorded lane dollars: Sonnet $388, Opus $269, Fable $221, none-recorded $44. Fable has its own weekly limit and is excluded from the pool question here.

**Reading.** On this basis **ops is ~56% of Claude spend, research ~16%** — the inverse of the accepted 10/20/70. Two things drive it: the Opus manager session (~$675/wk, about 60% of all spend if sustained) and the 74% of lane rows with no recorded spend (so research and builds are *under*-counted; the true ops share is probably lower than 56%, possibly 40–50%). The conclusion that ops is the largest bucket survives that bias; the exact number does not.

**Weekly capacity left for research if ops → ~10%, builds → ~20%** (operator-accepted split):

| Case | ops | builds | research | basis |
|---|---|---|---|---|
| Today (recorded basis, est.) | ~56% | ~18% | ~16% | table above (population: 256 rows touched since 2026-09-29, 67 with spend, plus manager anchor) |
| Target | 10% | 20% | **70%** | operator-accepted split; assumes the weekly allowance is held fixed (population: n/a, a target) |
| After wave 1 (S items + assistant manager), est. | ~34% | ~20% | ~46% | §C |
| After wave 2 (all 15), est. | ~10% | ~20% | ~70% | §C, optimistic |

In dollars where measured: research lanes recorded **$371 / 14 d ≈ $186/wk**; at the target share of a fixed ~$1,140/wk recorded-basis total, research would be **~$800/wk** (≈4.3× today). The $1,140 is this document's total (§B, ÷2), **not** a known allowance; do not read it as the plan cap.

## C. Automation backlog — ranked by (est. $ saved/wk) ÷ effort

Effort units: S=1, M=3, L=8. Savings are **est., API-equivalent $/wk** against §A, gross (overlaps exist: sum is discounted ~25% below). "Replaces with" is a repo mechanism or the Sonnet assistant-manager; nothing here is built.

Constraint worth stating: **a GitHub workflow cannot wake or read a Claude session** (no session MCP in Actions). So Actions can *detect and act on repo state* (PRs, CI, rows, branches) and *write exceptions into the repo*; anything needing session list/archive/spend/`fire_trigger` stays with a Claude lane, preferably the Sonnet assistant.

| Rank | Row | Replaces (today → proposed) | Est. save $/wk | Size | Risk | Proof it works |
|---|---|---|---|---|---|---|
| 1 | `ASSISTANT-MANAGER` (existing workstream, not duplicated here) | R2, M-e, M-f, M-g, the mechanical half of R1 → Sonnet lane, manager stays Opus | ~280 gross | M | Medium: drops a decision that needed Opus; mitigate with a short "escalate" list | 7 days of check-ins by the lane; manager session $/h falls vs the 4.03/h anchor; no missed blocked lane |
| 2 | `AUTO-BRANCH-SYNC` | M-a → workflow on push to `main`: `update-branch` for open `claude/*` PRs that are behind and clean; comment on conflicts only | 45 | S | Low–med: churns CI on every PR per main push (cost: runner minutes, not Claude); skip auto-merge-armed PRs whose base already moved only for CI-fix reasons | A forced test: leave a PR behind, push main, PR head advances within one workflow run |
| 3 | `AUTO-NOTIF-POLICY` | M-d → manager stops subscribing to PRs that have auto-merge armed and only subscribes on red; workflow comments on failure | 40 (low confidence) | S | Low | Count of PR-event wakes/day before vs after (session log) |
| 4 | `AUTO-PYTEST-RERUN` | M-b (cancelled half) → `workflow_run` on `pytest-run` conclusion `cancelled`, or failed with zero tests collected: rerun **once** (`run_attempt == 1`) | 25 | S | Low: bounded to one rerun, never masks a real red | Cancel a run on a scratch PR → exactly one rerun, then stays red/green on its own result |
| 5 | `AUTO-LANDING-FILES` | M-c → `scripts/ops/land_pr.py <branch>` writes the three files with the right slug, tier and merge-slot claim | 20 | S | Low: guard `pr-landing-guard` still checks | A scratch branch passes `pr-landing-guard` with only the script's output |
| 6 | `AUTO-EXCEPTION-FEED` | R2/M-e → Actions cron (30 min) computes exceptions from repo state (green+unmerged >1 h, red lane PR, in_flight row with no push in N h, over-ceiling) into a committed `EXCEPTIONS` file + Telegram; check-in routine reads it and ends silently when empty | 60 | M | Medium: false "all clear" (an empty feed that is just blind) → ship with a self-check that injects a known exception | Injected stale PR appears in the feed within the next run; manager check-in cost per fire drops |
| 7 | `AUTO-REVIEW-PRECLASS` | R1/M-h → a script pre-classifies the day's `digestLog` items into ack / act / ask-operator with the reason; manager reads only act/ask | 50 | M | Medium: mis-classified act as ack; classifier shows its rule and sample-audited weekly | Sample 30 items against manual disposition; ≥95% agreement on ack |
| 8 | `AUTO-RESEARCH-OPS-GATE` | R3 → `research_ops_precheck.py` (exists in part: replenish, dispatch, grade workflows) writes pipeline health + runnable floor + blocked list; the Sonnet lane fires **once a day**, or sooner only if the precheck finds exceptions | 65 | M | Medium: floor drops without anyone noticing; the precheck gets a "runnable floor < N" exception | Week with 1 lane/day: floor stays ≥ target; lane count and $ halve |
| 9 | `AUTO-ROW-ONMERGE` | M-f, M-g → on PR merge of a lane branch, workflow sets the row's PR/merged fields, `landed_unproven`/`done` per the row's own rule, deletes the branch | 30 | M | Medium: wrong state transition on a row that needs a human read; restrict to rows whose `observation` is present | Merge a scratch PR → row updated, branch gone, no other row touched |
| 10 | `AUTO-CI-TRIAGE` | M-b (red half) → on red `pytest-run` of main or a lane PR, classify (known flake signatures, date-bomb, missing deps) and comment a one-line diagnosis and owner row | 35 | M | Medium: wrong diagnosis anchors the fixer; label as `heuristic` | Replay the 10-13 date-bomb failure log → "date-dependent test" |
| 11 | `AUTO-OBS-CHECK` | M-i → rows get a structured `check_cmd` beside the free-text `how_to_check`; a workflow runs the runnable ones on `due_by` and writes pass/fail (the 115 `landed_unproven` rows are the backlog) | 35 + closes the unproven backlog | M | Medium–high: a check that passes vacuously (`echo ok`); require each `check_cmd` to be run against a known-failing fixture first (RULE ONE) | Run on 10 rows; compare with manual disposition |
| 12 | `AUTO-DUE-ROUTE` | due-item routing (`unrouted_count` growing per JC-SA-06) → rule-based router: stale → kill with reason, mechanical → checklist row, rest → ask list | 30 | M | Medium: wrongly killed item; kills require a stated reason and are reversible (append-only pipeline) | Dry-run over the open queue; review 20 decisions |
| 13 | `AUTO-SPEND-LEDGER` | M-f → the assistant manager runs a script that reads `list_sessions` metadata and writes `spend_usd` to rows when a lane archives | 15 + fixes the 74% unrecorded gap | M | Low | Share of lane rows with spend rises from 26% to ~100% for new lanes |
| 14 | `AUTO-GRADE-DRAFT` | grading + follow-up unit drafting (research-ops, perf-followup) → extend `queue_grade.py` to draft follow-up `research/queue` units from templates for template-generated results | 25 | M | Medium: template drafts accepted without scrutiny; units still carry pre-registered rules | Draft units for 5 landed results; compare with the lane's manual drafts |
| 15 | `AUTO-DATEBOMB-GUARD` | M-b root cause → CI guard that flags tests comparing a hard-coded date to `now()`/`utcnow()` (the 10-13 main-red incident) | 5 (prevents ~3 h red main) | S | Low | Guard fails on the `test_prop_tracking.py` pattern at its pre-fix commit |

Also filed as a row (missing function, not a saving): `AUTO-REVIEW-SCHEDULE` — see M1.

**Sum of gross savings (rows 2–15) ≈ $480/wk**; discounted ~25% for overlap ≈ **$360/wk net**, plus the assistant manager on what is left.

### C2. Where this lands (all est.)

| Stage | Built | Weekly ops $ (est.) | Ops share of ~$1,140/wk |
|---|---|---|---|
| Now | — | ~$680 (manager mechanical $575 + research-ops $94, plus small lanes) | ~60% on the manager-heavy basis, ~56% on §B |
| Wave 1 | rows 2–5 (all S) + `ASSISTANT-MANAGER` | ~$385 | ~34% |
| Wave 2 | rows 6–15 | ~$110 | ~10% |

Wave 1 is cheap (four S rows ≈ $3–6 of lane cost each) and carries ~half the saving, so it goes first. Wave 2 is where the target is reached on paper; treat the 10% as a hypothesis to measure, not a forecast.

## M. Ops functions that are MISSING (should exist; nobody does them)

| # | Missing function | Evidence |
|---|---|---|
| M1 | **Scheduled health/performance/ml reviews and the frontier scan.** Skills define them; no recurring trigger exists; they run when remembered | 5 enabled triggers, none for them; filed as `AUTO-REVIEW-SCHEDULE` (a decision on cadence + Sonnet routing, not a cost saving) |
| M2 | **Automatic reading of plan usage %.** The weekly bar is read from operator screenshots (`A1` notes, PACE-W40 "operator screenshot") | Pacing decisions rest on a manual number |
| M3 | **A lane-wake that does not depend on the lane remembering `fire_trigger`.** Wake contract failed 10-13 02:14Z for two lanes (~2 h lag, caught by the 6 h check-in) | PACE-W40 10-13 |
| M4 | **Closing `landed_unproven` rows** — 115 rows, no mechanism | state count above; `AUTO-OBS-CHECK` |
| M5 | **Spend recorded for new lanes** — 74% of rows touched in the window have no `spend_usd` | §B population |
| M6 | **Date-bomb test lint** | 10-13 main-red incident |
| M7 | **Per-function cost instrumentation for the manager** — shares in §A2 are guesses because nothing tags manager spend by routine | §0 |

## What this lane did not do

No automation built; no triggers created or changed; no live VM or Actions-run reads. All weekly-$ figures for the manager and for every saving are estimates from one measured anchor and the §A2 shares. The first thing any wave should do is measure: `AUTO-SPEND-LEDGER` plus a routine-tagged manager spend split would replace most of the guesswork above.
