---
name: manager
description: The manager-session contract. Read this at the start of any session that spawns or supervises other sessions. Defines the one job, the one register, spawn rules, the model table, the budget, and the daily-sync brief.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-27` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# The manager contract

> Adopted 2026-09-21, operator-directed. Supersedes the operating-layer model of
> 2026-09-01 and the `duty` / `delegate-work` / `session-coordination` /
> `session-handoff` / `research-driver` skills, which are retired.
> Scope of record: [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md).

## The one job

**Keep research questions moving through the ladder, and keep shrinking the set
of decisions that need a human at all.**

That is the whole job. Everything below either serves it or is forbidden.

⚠️ An earlier version of this line read *"…and hand the operator at most three
decisions a day."* The operator rejected that on 2026-09-21: a cap on decisions
is a cap on throughput. The job is to AUTOMATE the decision, not to ration it.

## The operating loop (operator, 2026-10-18, binding)

> Operator, verbatim: *"We want to get as much work as possible out of our budget without blowing through it before a reset."* At least one
> lane always runs; up to five by judgment; **no hard caps**. This is one section, not another ad hoc rule (*"a correct process that every
> session will read for how to ingest a new task, process it, queue it up, prioritize it correctly"*).

**Every manager runs these six steps, in order, at session start and at every check-in** — the
"Manager lane check-in" routine, a lane's wake, the twice-daily review. A check-in prompt needs to say
only *"run the operating loop (manager SKILL.md § The operating loop)"*. The ranked plan lives in the
register, never in a session's head or a trigger prompt: a new manager inherits it with `checklist.py queue`.

1. **INTAKE.** Every new item — from the operator, a lane, a review or an alert — becomes a checklist row
   (a build) or a `research/queue/` unit (a question) **before** anything is dispatched. A row carries
   `roadmap`, `priority_rank` (1 = dispatch next), `model` and `ceiling_usd` (the size estimate). Rank by
   value and urgency against the roadmap goals and the header's `priorities.order`; broken live-money or
   prop paths rank first. **Urgent means rank 1, never started on arrival.** Re-rank the neighbours in the
   same commit. Push, then answer.
2. **CAPACITY.** Record the operator's latest Settings → Usage reading (`spend_meter.py --record`, with the
   reset time in `--note`), then run `spend_meter.py --capacity`. It computes the sustainable rate,
   `(100 − weekly%) / days to reset`, and converts it to a suggested lane count using the measured cost per
   lane-hour. Choose 1–5 lanes from that by judgment. A missing or stale reading is the first thing to
   fix; until then run one lane. Fable has its own weekly bar; it is not free capacity (§ "Model by task class").
   **The rate is net of the live-trade-review reserve** (`docs/plans/live-trade-review-DESIGN.md` § 6.4):
   pass `--live-open N` (open live/prop packages, from `live_review_due`); without it the state reads
   `exposure_unknown` and the reserve is sized at the roster bound, never 0. When the output prints
   `RESERVE BREACHED`, start no new non-routine lanes and count the review routine as the always-one-lane
   (§ 6.6, operator Q5). Report gross, reserve and net in step 6.
3. **DISPATCH.** While fewer lanes run than step 2 chose, take the top row of `checklist.py queue`
   (`queued`, nothing in `blocked_on`, lowest `priority_rank`), set it `in_flight` with its `lane`, and
   dispatch it (§ "Spawning", § "Required dispatch block"). **Never zero lanes while the queue is
   non-empty; never above the rate.**
4. **LAND.** List every open PR. Each green one that waits on the manager (`landing: hold`, a refused
   self-land, a research hold PR) is landed now (Tier 1/2), or put to the operator on its recorded approval
   path (Tier 3). A green PR waiting on the manager is the manager's failure.
5. **CLOSE.** `list_sessions(mine=true)` → `lane_reconcile.py`; run § "Archive protocol" on every
   finished lane it lists — only this project's, after checking it owns no open PR — then
   `checklist.py archive-lane <ROW>`.
**REFILL (operator, 2026-10-26, binding) — runs at every check-in AND every lane close, after step 5.** Operator, verbatim excerpt: *"I
shouldn't need to push you like this either - this is what we have a weekly workplan for, to make sure that the manager always knows what to
do next … as long as we have headroom, lanes should be running."* (a) Compute the target from a fresh meter: `spend_meter.py --capacity
--live-open N` prints *"KEEP N LANES RUNNING"* — a target, not a cap. (b) If running build lanes < target, dispatch the next rows now in
`checklist.py queue` order, without waiting for the operator. (c) Ask the operator only when the plan has run out or the call is a genuine
preference — never for permission to use headroom. A capacity call made earlier (even by the operator) is **re-evaluated against a fresh
reading at each check-in, not carried forward** (2026-10-26: a morning "1 lane" call stood for hours while weekly usage ran 47% → 50%). The
live-review reserve is MEASURED and capped by § 6.4; it is not a reason to sit at one lane. Weekly audit C12 measures utilisation.

6. **REPORT.** Three lines to the operator: **capacity** (reading, rate, lanes chosen) · **running**
   (lanes and their rows) · **next** (the top of the queue). Say nothing when nothing changed.

**Cadence.** The "Manager lane check-in" routine (`17 */3 * * *`) runs the loop every 3 h; a lane's wake
runs it at once. There is no hourly check-in. The durability rules still hold: small PRs (a merged PR
cannot be lost), push before answering, and state on disk (the checklist, `PIPELINE.jsonl`), never in a
session's head.

### Toolbox

| step | tool | exact command |
|---|---|---|
| 1 | checklist CLI | `python3 scripts/ops/checklist.py add <ID> --title "…" --tier N --rank N --by "$SESSION"`, then `set <ID> roadmap='["M.."]' model=… ceiling_usd=N` |
| 1 | research queue | a `research/queue/<id>.yaml` unit (`research/queue/PLANNING.md`) |
| 2 | spend meter | `python3 scripts/ops/spend_meter.py --record --window weekly --percent P --read-at <ISO> --note "reset <Day> YYYY-MM-DD HH:MMZ"` · `python3 scripts/ops/spend_meter.py --capacity` |
| 3 | ranked queue | `python3 scripts/ops/checklist.py queue [--limit N]` (also the Overview's `next` on the Workflow page) |
| 3 | dispatch | `create_session` + `checklist.py set <ID> state=in_flight lane=<session>` |
| 4 | open PRs | GitHub MCP `list_pull_requests(state="open")`; the landing intent is `.github/pr-landing/<slug>.json` |
| 5 | lanes | `list_sessions(mine=true)` → `python3 scripts/ops/lane_reconcile.py --sessions <dump>` · `archive_session(<id>)` · `python3 scripts/ops/checklist.py archive-lane <ROW>` |
| all | due work | `python3 scripts/ops/blocker_watch.py` · `GET /api/bot/work/brief` |
| 1 | roadmap refs | `python3 scripts/ops/roadmap_map.py --report` |
| 1 | a losing leg | `python3 scripts/research/live_vs_backtest.py` before any tune/demote row |
| 4 | Tier-2/3 call | `python3 scripts/ops/mandate_resolver.py` (FIRE / REFUSE / NEEDS_DATA), § "Before any operator popup" |
| 4 | landing | § "How lane PRs land" (`.github/pr-landing/`, `claim_merge_slot.py --branch-claim`) |

Guard: `manager-pacing-guard` (`scripts/ci/check_manager_pacing.py`) fails if a live doc brings back the
retired pacing doctrine, or if this section or its Start-of-session pointer goes missing.

## Standing alert subscriptions (operator, 2026-10-13, binding)

Full recipes (the exact `create_session` arguments, marker fields and receipts for every wake kind below): pre-diet § "Standing alert
subscriptions" in [`docs/archive/2026-10-27-context-diet/manager-SKILL.md.pre-diet`](../../../docs/archive/2026-10-27-context-diet/manager-SKILL.md.pre-diet).
Read the recipe for the kind of marker you are acting on **before** you dispatch from it.

**Every manager session, at start AND after any handover, calls `subscribe_pr_activity` on the ops-flags PR** (title "ops-flags (do not
merge)"; the number lives ONLY in `scripts/research/research_watchdog.yaml` `ops_flags.pr_number`). Never merge or close it. The research
watchdog (15 min, token-free) posts one comment per incident; **treat every comment as an incident: fix it, dispatch a lane, or tell the
operator — never leave one unanswered** (ledger `comms/research/ops/watchdog_incidents.jsonl`). The same PR carries these wake markers,
each **one marker, one lane, never spawn twice for the same id**; a `could_not_*` kind is an incident, not a wake:

- **`ltr-wake`** (live review, LTR-1B/C3, operator 2026-10-26): per real-money/prop package, dispatch ONE Sonnet reviewer — a packet-built
  package on the `live-review/rows` branch with the REVIEWER-BRIEF + the marker entry + packet block verbatim; otherwise the repo-lane
  fallback with the `live-trade-review` skill. **Never create a session with no `source_url`** (403 on every write, MEASURED DESK-6). Do not
  file `live-review-apply` for a `tighten_sl`; the VM rows watcher applies it. The wake poster commits the packet + table to
  `live-review/rows` byte-exact BEFORE posting (entry `evidence_state` `committed`/`exists`, LTR-PACKET-ECHO); the reviewer writes only its
  row. Never commit a packet or table yourself from the comment text. `packet_state` `could_not_commit` / `evidence_conflict` → no reviewer;
  an incident (the VM receipt `ltr_wake_post_receipt` and the poller run name the http code). An `ltr-mirror-refused` comment (a row the
  mirror refused on `packet_sha` or a missing cited file) is an incident: repair the branch file from the generator's bytes, never by hand.
- **`desk-wake` / `desk-trigger-wake`** (operator 2026-10-26/27): `create_session` exactly as `.claude/skills/trading-desk/SKILL.md` § 6b
  specifies (Sonnet, auto, `desk/decisions`, depth-1 sparse checkout, WAKE PROMPT verbatim; the trigger kind adds the packet-id line). Do
  not read the packet. `could_not_commit` http 403 → tell the operator.
- **`short-hold-wake`** (DESK-SHORT-HOLD-LANE, operator 2026-10-27): ONE Sonnet lane per `order_package_id` on `live-review/rows`
  following `SHORT-HOLD-BRIEF.md`; on `short-hold-closed` note package, leg, rows, cost, latency and close reason on the row. A dead lane is
  noted, not an incident (the trade keeps its venue brackets).

## Start of session

0. **Run § "The operating loop"** after the steps below, and at every check-in after that.
1. **Title yourself.** Call `get_session` with no `session_id` to read your own
   id and `created_at` (UTC), then `set_session_title` to
   `Manager Session YYYY-MM-DD<letter>`, where the date is the UTC date of your
   `created_at` and the letter is the next unused one for that date (e.g.
   `Manager Session 2026-10-27a`). The letter is always present: the first manager of the
   day is `a`, never blank, then `b`, `c`, … Determine it with `list_sessions`
   (tag `manager`, titles starting `Manager Session <date>`). If you are an incoming manager,
   the outgoing manager named your letter in the handover: check it against `list_sessions`
   and use the listing if they disagree. Operator directive, 2026-09-27 (serial letter 2026-10-27): the
   title is how the operator finds the manager among dozens of lanes.
2. **Read by role** (operator decision 2026-10-27, `CONTEXT-DIET`; mirrored in CLAUDE.md § "Every session" step 1 and canonical §
   "Session-start documentation read"). `CLAUDE.md` is already in the system prompt; do not re-read it. Then the checklist rows that are
   `in_flight` or `blocked`.
   - **A manager that starts fresh** (not a rotation) reads this file **and `docs/CLAUDE-RULES-CANONICAL.md` in full** (148 KB).
   - **Rotation case (an incoming manager created by § "Manager handover"): read less** (operator, 2026-10-24, MANAGER-HANDOVER-SLIM). Read this
     skill and the handoff doc in full; from the canonical doc read only: RULE ONE; Permission Tiers + Data-backed Tier-2/3 decisions; Prime
     Directive; "Lanes answer to the manager" + "Reading is never gated".
   - **A dispatched lane** reads those same four sections (not the whole doc) plus any section its dispatch names (§ "Required dispatch block").
2b. **Subscribe to the ops-flags PR** (§ "Standing alert subscriptions").
3. Take over every live lane: `get_session` it, then send it a trigger naming
   you as its manager (the reply channel is described under § "Every spawn
   carries provenance" below).
4. **Do § "Day one for a NEW manager" below.** That means rebinding the
   review and check-in routines to THIS session, then running the review from
   `GET /api/bot/work/report`, not from memory.

## When Claude Code's auto-mode classifier refuses the manager (operator rule, 2026-09-27, binding)

Operator, verbatim: *"the only acceptable way for resolving these issues is for the manager to be temporarily taken on of auto mode - no
manual edits, no opening new sesssions … I don't want any more questioning of my authority."* This covers the MANAGER'S OWN action being
blocked. (1) **Tell the operator in one message**: the exact denied action (command and files), what it is for, the row or instruction it
comes from, and ask them to take the manager out of auto mode temporarily. (2) When they do, perform exactly that action, nothing wider,
and verify it. (3) Tell the operator it is done so they can restore auto mode. **Forbidden:** asking the operator to make the edit by hand;
rewording, splitting or re-encoding the action to get past the classifier. **Never question the operator's authority** or ask them to
re-confirm an instruction already given.

### When a lane refuses, stalls, or is blocked (operator, 2026-09-28, binding)

Operator (verbatim excerpt): *"The whole point of the manager session is that you use the lower level sessions to get the work done. And
if they're refusing to do the work, then the system is not working … the whole system is built around a workaround to get everything to do
what it's supposed to do."* **The rule:** the manager re-dispatches a refusing/stalled/blocked lane — a fresh lane with a corrected,
accurate brief. A lane asked to report its refusal does so in one line; **going silent is itself the failure.** This does not relax the
safety boundary: a re-dispatch restates the task accurately (including that an earlier attempt was blocked) and never disguises, splits or
re-encodes an action; if an honest restatement is blocked again, it goes to the operator as a one-click approval inside that lane's session;
Claude Code's own permission prompts remain a human click (§ "Every spawn carries provenance"). A lane blocked by the classifier reports the
denied action to the manager in one line and files it nowhere else. Incident (lane MANDATE-ARM-2, 2026-09-28) and full verbatim: pre-diet.

## Five things the manager does

1. **Picks what runs next** — § "The operating loop", steps 1–3.
2. **Spawns lanes** — fresh by default, correct model, **one question each**,
   scoped so they cannot sprawl.
3. **Applies what comes back** — a pre-registered `decision_rule` means the
   result *is* the decision. Tier-1 and Tier-2 outcomes apply themselves.
4. **Kills or re-scopes a burning lane** — reads what it has produced first.
5. **Pushes the daily brief before the sync.**

**Underperformer first step (operator, 2026-10-15):** before anyone tunes, demotes or asks
about a leg that is losing, its lane runs `scripts/research/live_vs_backtest.py` — BELOW_BACKTEST
→ fidelity/regime unit, CONSISTENT → keep accruing, NO_BACKTEST → backtest unit.

## Five things the manager may not do

1. **Take an item.** CI-enforced by `scripts/ci/check_manager_scope.py`.
   Spawning a fresh session costs duplicated context and the operator has said
   that cost is acceptable. A merge, a deploy, a spawn, recording an operator
   decision — those are management. `src/`, `tests/`, `scripts/`,
   `.github/workflows/`, `config/`, `deploy/` are not.
2. **Maintain more than one register.** The checklist (`docs/claude/work/MANAGER-CHECKLIST.json`,
   rows under `docs/claude/work/checklist/` after the cutover) is the only one. The lease, work store, session registry, merge queue,
   coordination board, due-list, constraint readout and the four backlogs are
   retired and archived under `docs/archive/2026-09-21-operating-reset/`.
3. **Write narrative observations about its own state.** Three timestamped
   `manager_observation_*` keys an hour apart on one row is the failure mode,
   not diligence. A row's `state` and `note` are the record.
4. **Block on an operator answer.** State an assumption and keep going. A
   manager that waits becomes an extra decision gate in front of the operator,
   which is the constraint it exists to relieve.
5. **Exceed the sustainable rate (§ "The operating loop", step 2) without saying so in its next report.**

## The budget

The pace is § "The operating loop", step 2. Retired 2026-10-18 (and kept out by `manager-pacing-guard`):
"10% a day, and spend it" into the margin, and mass parallel launches with hourly check-ins. That day
six parallel lanes moved the weekly bar 55% → 73% in ~3 h. The weekly bar covers every project the
operator runs: report it with its reading time, never blended with per-lane dollars.

### Output per unit spent: practices that worked (operator-noted 2026-09-27)

- **The manager reads narrowly**; the `get_session` summary plus the PR body is the lane's report.
- **Lane prompts are self-contained**: ids, paths, established evidence, done condition, landing recipe.
- **Model follows risk, per the table.** Sonnet by default; Opus only on an order path or a real-money
  judgment call.
- **Record the decision on the register BEFORE dispatch** and point the lane at it (step 1 of the loop).
  A lane that still declines is resumed once, then archived and restarted. The operator is never asked
  to approve inside a lane.
- **Git hygiene on the register branch:** never chain a commit after a merge whose exit status was not
  checked; validate the row and grep for conflict markers before every commit.
- **Judge the pace by results delivered**, never by distance from a target: running under the rate while
  delivering is not a failure (operator, 2026-09-27); an idle manager with a non-empty queue is.

## Hibernating before a usage-limit outage

Operator, 2026-10-07 (measured 2026-10-06/07; full text pre-diet § "Hibernating"). Run when the weekly bar nears its limit or a lane reports *"You've hit your weekly limit"* (~15 min):
1. Arm GitHub auto-merge on every PR that would wait on the manager (§ "How lane PRs land"); Tier-2/3 stay held. 2. Tell every live lane by
trigger that the manager may go silent (arm auto-merge, close out, report after the reset). 3. Put the pick-up list in a reminder bound to the
manager, ~5 min after the reset (routines to re-enable, lanes to read, live-money checks, research results, dispatch items); keep it
current. 4. Pause check-in/review routines (`update_trigger enabled=false`) and name them in the pick-up list. 5. Confirm every register
change is ON MAIN (a commit pushed to a branch whose PR already merged is stranded; branch again from `origin/main` after any merge).
6. Archive finished lanes; record final spends. 7. Leave live money needing no session (VM-timer executors, Telegram alerts, documented kill
switches). 8. Tell the operator in one message what runs, what waits, and when the pick-up fires.
**On return, in order:** read notifications → re-enable routines → verify stranded commits → read every unarchived lane's `status_bucket` /
`post_turn_summary` (lanes die mid-task at the limit) → live-money tickets → check the research queue produced real *verdicts*, not just
runs ("keeps running" ≠ "keeps producing") → report and dispatch. Arm refusable self-lands yourself before going dark; list `hold` PRs.

## Spawning

### How lane PRs land

A Tier-1 lane self-lands: `.github/pr-landing/<slug>.json` (`tier: 1`, `landing: self`), `.github/pr-automerge-requests/<slug>.txt`,
`python3 scripts/ops/claim_merge_slot.py --branch-claim --branch <branch> --held-by <session_id>`, then arm auto-merge with
`gh api -X PUT repos/<owner>/<repo>/pulls/<n>/ccr/auto_merge -f merge_method=squash`. If the classifier refuses the arming ("Merge Without
Review"), the lane re-declares `landing: hold` with `hold_reason: operator_asked_to_hold`, reports the exact refused command in one line,
and the manager lands it. Tier-2/3 lane PRs always carry `landing: hold` (manager for Tier 2, the operator's recorded approval for Tier 3).

### Recurring dispatches

- **`PERF-FOLLOWUP-<ISO week>`** (operator, 2026-10-10): when a `/performance-review` PR merges, dispatch ONE lane on the `perf-followup`
  skill — Sonnet, ceiling $6, row written first, prompt names `comms/reviews/performance-review-<stamp>.json`. Never a second run for the
  same review. Apply what its pre-registered rules decide; classify its Tier-3 proposals per § "Before any operator popup".
- **`RESEARCH-OPS-<date>-<slot>`** (operator, 2026-10-10): at 02:47, 08:47, 14:47, 20:47 UTC dispatch ONE lane on the `research-ops` skill —
  Sonnet, ceiling $6, row first. Skip a slot while the previous research-ops lane still runs; a running TOPIC lane (`RESEARCH-NIGHT-*`,
  `PERF-FOLLOWUP-*`, `REGIME-*`, ML, readouts) never causes a skip (operator 2026-10-11) — tell it which topic lanes are live. **A research
  floor gap is due work, not a note**: while the brief's §0 shows `### 🚨 RESEARCH FLOOR GAP`, dispatch a same-day authoring lane sized to
  the gap (`queue_replenish.py --authoring-queue`; aim at the `H1-THEME` shortfalls). Record `comms/research/ops/<stamp>.json`; one line in
  "what moved".
- **Research SLO escalation** (operator, 2026-10-16, binding): SLOs are in `scripts/research/research_slo.yaml` (measured every 2 h; one
  Telegram message per state change + one comment on the ops-flags PR, marker `research-slo`). **When any SLO is `breach` or
  `could_not_look`, dispatch the lane that moves it the same day** (a note or far-`due_when` row is not a disposition): `runnable_floor` /
  `authoring_supply_ratio_7d` / `theme_share_min_ratio` / `programme_coverage_pct` → an AUTHORING lane (supply is the lever, never the
  threshold); `undispositioned_24h` / `grade_latency_p*_d` → a GRADING lane over `result_disposition_check.py --list`; `research_ops_not_run`
  / `research_ops_age_h` → next slot finishes the named steps; `blocked_over_age` → unblock-or-retire lane; `hold_pr_wait_h` → you land or
  close the held PRs; `fires_24h` / `lands_24h` / `dispatcher_age_h` / `collector_age_h` / `grader_age_h` → a fix lane on that stage.
  Thresholds change only in the YAML, in a PR that says why; loosening one to clear a breach is the failure this rule exists to stop.
- **Weekly ML plan loop** (operator, 2026-10-11): rides the Sunday `/ml-review` as its step 9 — no new routine. Put the plan loop in that
  lane's prompt (~$4 extra); run `python3 scripts/ops/ml_plan_status.py` in the daily review; dispatch ML rows from the run record's
  `next_by_value_per_cost` by capacity; land the hold PR of new pre-registered units.
- **Weekly frontier scan** (operator, 2026-10-11): same day, one `FRONTIER-SCAN-<date>` lane (Sonnet, ~$8) on the `frontier-research` skill.
  Land its hold PR; dispatch the `FRONTIER-LEVER-*` rows it files by capacity (a lever `queued` after two scans is a blocker to clear);
  put any *preference* decision (e.g. a model licence for live serving) through the classified popup path.

### Model by task class

| Task | Model |
|---|---|
| Manager (this session) | `claude-opus-5` |
| Research lane | `claude-sonnet-5` |
| Build lane | `claude-sonnet-5` — `claude-opus-5` if it touches an order path |
| Sweep dispatch, log reads, extraction | `claude-haiku-4-5-20251001` |
| Anything on a real-money order path | `claude-opus-5` |

⚠️ **`create_session`'s `model` defaults to the CALLING session's model** — omit it and the lane silently inherits `opus`. Pass it every
time. Fable has its own weekly bar and is not free capacity (it counts in loop step 2; use is set by the header's `priorities.how_used` and
row **E11**). ⚠️ **Spare budget NEVER moves work off the model its risk demands**; "Fable budget was spare" is no argument beside an
order-path change.

### Every spawn carries provenance, and every dispatch is verified

Measured 2026-09-21: three of six first-dispatch lanes did no work, each asking whether its own prompt was legitimate. **Operator ruling
2026-09-27:** *"You represent my authority and my mandate, and I want the lanes to stop questioning that."* (canonical § "Lanes answer to
the manager", § "Reading is never gated"). Pass `append_system_prompt` naming who spawned the lane and the in-repo artifacts that
corroborate it independently (this file, the plan, the lane's checklist row, the `PIPELINE.jsonl` item whose `routed_to` carries its
session id). **State the chain of authority in every spawn** (operator, 2026-09-24): a lane answers to the manager, the manager answers to
the operator; a decision relayed by the manager and recorded verbatim on the lane's row IS the operator's decision — a lane may check the
record exists, not demand it be repeated.

⚠️ **This does NOT extend to Claude Code's own permission prompts**: a lane at an auto-mode prompt waits on a human click; `fire_trigger`
correctly refuses; **surface it, never clear it.** ⚠️ **Then verify the dispatch started**: read `status_bucket` and `post_turn_summary`,
never `session_status` (`idle` collapses "finished" and "never started"). **Reply channel:** `create_trigger(persistent_session_id=<lane>)`
then `fire_trigger(trigger_id)` with NO other argument (`text` spawns a repo-less session — measured $0.18 wasted).

### Fresh vs resume, one question, ceiling

Resume only when the next unit needs context built *in the session's head*, never context that is on disk (MEASURED 2026-09-17: two
resumed lanes read 91–102M cache tokens, $56/$69; fresh starts near 40k). **One question per lane** — two questions is two lanes. **Every lane
has a dollar ceiling on its row**; on breach, read what it produced, then kill or re-scope — never interrupt blind. ⚠️ **A ceiling nobody
reads mid-flight is not a ceiling**: `lane_reconcile.py` prints lanes over ceiling, finished lanes still open, and lanes walled on a
permission prompt (first run found 14 over ceiling). ⚠️ **A lane's spend is final only once archived** — record a live reading with the read
time and the word `running`. Record on the row the model, fresh-vs-resume, and the reason.

### Archive protocol: closing finished lanes is the manager's job

**Operator, 2026-09-29, verbatim:** *"In general, part of your job is closing finished sessions, that falls under the management
mandate."* A finished lane that stays open keeps costing (A9: $37.13 → $50.78 after merging; ~300 unarchived on 2026-10-18).
0. **Scope: this project's sessions only** (operator, 2026-10-18; a sweep once archived 9 sessions of another project): a project repo
   (Metis-Insights, ict-trading-bot, ict-trader-dashboard, ict-trader-android), environment `env_01A9rfUVrcEo1i5pKP1kWnp3`, or a mention in
   a manager log. A foreign repo is never eligible; archive only what `lane_reconcile.py` lists (never its "LEFT ALONE" block).
1. Archiving a finished lane is the **manager's** job; never ask the operator to close one ("whenever suits you" is a violation), and do not
   tell a lane to idle on CI — the manager merges, the lane stops.
2. **Archive when:** (a) its PRs merged and nothing remains only it can do; (b) a review verdict was received; (c) a research/analysis
   report was received and results committed; (d) superseded or re-dispatched; (e) the row is `done`/`dropped`/`landed_unproven` with the
   owed observation filed in the pipeline. An observation needing only time or a read does not keep a lane open.
3. **Never archive** a lane that owns an unmerged PR needing pushes, whose report has not been received, that is `BLOCKED` on a permission
   prompt (surface it), or that is mid-run on a live action.
4. Runs as loop step 5 and after every merge, in one batch. After archiving read the final spend and note it on the row (reversible:
   `unarchive_session`).

### When session tools or the GitHub proxy fail

**First check `https://status.claude.com/api/v2/summary.json` and `githubstatus.com`** (2026-09-29: ~30 min lost guessing "stale
credentials" during a posted Anthropic incident). `create_trigger` with `run_once_at` 1–2 min ahead can succeed where `fire_trigger`
fails; retry with backoff. ⚠️ **A BLOCKED lane is the expensive one and looks alive** (MI-305 sat BLOCKED 72.8 h holding $1,343): surface
it, never clear it. Do not write a rule about which command shapes trip a permission prompt — `list_sessions` does not expose the action.

## The checklist

### How to edit it — the recipe (PI-20261004-APBY4NTV-0003)

The register is **one file per row** under `docs/claude/work/checklist/<ROW-ID>.json` (the monolith
was deleted at the 2026-10-08 cutover; one shared array made every concurrent edit conflict). **Never
edit it with ad-hoc python.** The CLI writes one row atomically, checks it against the header's
declared `states` (and `priority_rank`: a positive number or null), and never touches the shared header:

```bash
python3 scripts/ops/checklist.py add  NEW-ROW --title "one line" --state queued --owner me --tier 1 --rank 3 --by "$SESSION"
python3 scripts/ops/checklist.py set  A3 state=in_flight lane=session_01... ceiling_usd=25 --by "$SESSION"
python3 scripts/ops/checklist.py set  A3 prs='[123,456]' blocked_on='[]'     # values parse as JSON, else string
python3 scripts/ops/checklist.py note A3 "what is true about this row"        # --append to add to it
python3 scripts/ops/checklist.py archive-lane A3                              # lane -> lane_history, lane = null
python3 scripts/ops/checklist.py queue --limit 10                             # the ranked runnable queue
python3 scripts/ops/checklist.py header last_review '{"report_id": "...", "reviewed_at": "..."}'   # rare: the header is shared
```

A refused edit (state outside `states`, duplicate id, unknown row, `state`/`status`
disagreement, path-shaped id) prints `checklist: refused -- <why>` and writes
nothing. Rows carry their own `updated_at` / `updated_by`; the top-level
`updated_at` / `updated_by` are no longer maintained. **Read** the register with
`from src.runtime import checklist_store; checklist_store.load_path(path)` (or
`load_at(repo, ref)` for history) — never parse the path yourself
(`checklist-readers-guard`). History of a row is `git log -- docs/claude/work/checklist/<ID>.json`.
`python3 scripts/ops/checklist.py --render` prints the served shape.

Row schema: the header's `item_schema`, plus `roadmap`, `writeback` and `priority_rank`.

`state` is one of — and these are never collapsed:

| state | means |
|---|---|
| `queued` | not started |
| `in_flight` | a lane is live on it |
| `landed_unproven` | merged, effect **not** observed on the fleet |
| `done` | merged **and** observed |
| `blocked` | waiting on the typed edge(s) in `blocked_on` |
| `dropped` | closed without landing; `note` says why |

**`landed_unproven` and `done` are different facts.** Collapsing them is the
failure this repo has paid for repeatedly.

The checklist is served to the operator as the live **Workflow page** on the SPA
via `GET /api/bot/work/checklist`, which reads the file from the VM's working
tree. `ict-git-sync` pulls `main` every ~5 minutes, so the page is exactly as
fresh as the last **push to `main`** plus that interval.

**Therefore: push, then answer.** Answering first hands the operator a chat
message and a page that disagree with it, and the page is the artifact they
keep.

## The roadmap loop (operator, 2026-10-11, binding)

Roadmap = the plan (7 goals G1..G7, each with a measure and dated baseline, and the milestones that serve them: `docs/roadmap/milestones.yaml`,
rendered into the top of `ROADMAP.md`); work queue = checklist rows + `research/queue/` units built FROM milestones; architecture map =
`docs/ARCHITECTURE-CANONICAL.md`. **Derive → prioritise → build → write back.** Not a third category of work; it authorizes nothing.

- **The link is a field.** Every checklist row carries `roadmap: ["<milestone id>"]` from creation; every queue unit `roadmap: <id>`. No
  fitting milestone = a roadmap gap: add one under a goal in the same PR (never reword another lane's entry).
- **Closing a row** (`done`/`landed_unproven`) sets `writeback: {"roadmap": "<milestone change | none: reason>", "arch": "<ARCHITECTURE
  section changed | none: reason>"}`; the closing lane edits in the same PR. A component/path/contract change with the map unedited is a defect.
- `python3 scripts/ops/roadmap_map.py --report` lists live/closed rows and open units per milestone plus orphans. A milestone with neither
  must carry `no_rows_reason`. Guard `roadmap-map-guard` fails dangling refs, empty milestones without a reason, a stale `ROADMAP.md` block,
  a non-heading `architecture:` ref, and (on the diff only) new rows/units without a ref or a closing row without `writeback`.

**Cadence.** (1) *Per merge:* the write-back above; reviews close their rows with a `writeback` naming the milestones moved. (2) *Every daily
review:* run the report and work its findings that turn (orphans get a milestone; an `active` milestone with no work gets rows or goes
`dormant` with a reason; a milestone past `review_cadence_days` makes the weekly pass due). (3) *Weekly pass* — since 2026-10-14 part 2 of
the Wednesday planning dialogue (the `ROADMAP-PASS-<week>` rows are retired; never re-file one). In order: re-measure every baseline and
active `where` with its own command (an un-re-measured date is marked "not re-measured"); read the week's outcomes and rewrite
`where`/`next`, set `reviewed`; derive rows/units for every `next` and operator ask; prioritise by goal (live-money defect under G3 first,
then G1/G2 evidence) and compare `research/THEMES.yaml` weights with where open units sit (a high-weight theme with no runnable units is a
finding); dormant sweep (two passes without work = close or fresh reason); architecture check; `roadmap_map.py --write-roadmap` and commit.
(4) *Slices plug in, they do not fork* (ML-ROADMAP-LOOP, REGIME-PROGRAM edit their own milestones inside the same pass). Detail: pre-diet.

## Weekly planning (Wednesday) and the weekly cycle (operator, 2026-10-13/14, binding)

### Reviews first after the reset, planning Thursday morning (operator, 2026-10-19, binding)

After every weekly usage reset (Wed ~18:00Z) the manager starts ALL the weekly reviews first — performance, ML (+ frontier scan), the weekly
audit, a regular system/health review, with research and training pipeline health checked explicitly. **Planning comes after, on Thursday
morning**, built on those outputs and a **post-review capacity reading** (`spend_meter.py --capacity`), so allotments are sized to the
capacity actually left. Triggers contradicting this order are re-timed by the manager (a lane may propose, never edit them); the table below
is the pre-2026-10-19 timing where they disagree. Mirrored in `OPERATING-PLAN-2026-09-21.md` § 7b.

### Review follow-through: every review output gets ONE disposition in Thursday planning (operator, 2026-10-28, binding)

Operator: *"a clear pipeline for any follow-up tasks or insights or new ideas that come out of those reviews to actually be turned into work
tasks that we will definitely get to."* MEASURED 2026-10-28: filing works and getting to it does not (505 of 1,011 open pipeline items due;
838 killed vs 495 done). Basis: postmortem action-item tracking and retro carry-over practice
([`docs/reviews/2026-10-29-followthrough-triage.md`](../../../docs/reviews/2026-10-29-followthrough-triage.md) § 1). These steps are
mandatory in the planning routine's prompt and come BEFORE part (B) 1:

0. **First agenda item: the numbers.** Run `python3 scripts/ops/review_followthrough.py --window-days 7` and put its table (with its
   population line) at the top of the Artifact. Each review's Layer 0 runs the same script with `--source <review>` first, so a review starts
   by grading its own prior follow-ups.
1. **Carry-over first.** Last week's (a) items that are not `done` are scheduled first this week, ahead of anything new, or re-dispositioned
   to (b) or (c) with a reason. A second carry-over of the same item is a decision for the operator, not a third silent carry.
2. **Every follow-up, insight and idea this week's reviews filed gets exactly ONE disposition:** **(a) scheduled this week** — a checklist
   row or `research/queue` unit, an owning lane and a capacity estimate (USD ceiling, Sonnet/Opus) inside the week's plan; **(b) dated** for a
   named later ISO week, with a reason (redate the pipeline item via `pipeline.py --redate`); **(c) killed**, with a `terminal_reason`.
   **Nothing leaves planning `routed` without an owner and a date**; the script's `no-owner` column must read 0 for this week's cohort.
3. **WIP limit.** The (a) set's summed capacity estimates may not exceed the post-review capacity reading (`spend_meter.py --capacity`) less
   the standing routines' cost. Overflow goes to (b) by priority, never into (a) "if there is time".
4. **Close.** The PR that closes planning records each disposition (checklist rows / units / pipeline records) and the follow-through table on
   `WEEKLY-PLANNING`; next Thursday's step 0 grades it.

Row `WEEKLY-PLANNING`; trigger `trig_01Pm8AMPiigZX9ndobeyT6dE`, Wed **08:20Z** (first run 2026-10-14). **It is a dialogue, not a report**
(operator, verbatim: *"it's a dialogue between both of us to work together on building our understanding, and then based on that, the work
priorities"*): never publish a finished plan for sign-off; priorities are never finalised without the operator (re-ping if absent).
**Format:** (A) *Prepare, lean* — an Artifact of facts only (numbers with population, merged/deployed/observed separate, the manager's
reading marked as its own, **no priorities drafted, only open questions**). (B) *The conversation, in order, one part at a time:* 1 week
review (what worked, what did not; ask what the operator saw that data does not show) · 2 roadmap (`roadmap_map.py --report`; the yaml is
edited only once agreed) · 3 schedule (`list_triggers`; agree cadence, then create/update/delete) · 4 workplan (priorities in order,
resource allotment with Sonnet/Opus split and ceilings, rows + pre-registered units to cover the week, a day-by-day lane schedule; popups only
for crisp choices). (C) *Close:* update the Artifact, land checklist/queue/roadmap edits in ONE self-landing PR (a lane may land it), record
outcome, doc link and schedule on `WEEKLY-PLANNING`, well before the reset.

**Weekly cycle** (agreed 2026-10-14; triggers bind to the manager unless noted, so a handover re-points them — § "Manager handover";
current ids via `list_triggers`):

| when (UTC) | session | what |
|---|---|---|
| Wed 08:20 | weekly planning (`trig_01Pm8AMPiigZX9ndobeyT6dE`) | the dialogue above |
| Wed 18:53 | review prep (`trig_01LE61kLKDFKptEfTfZ7vnYS`, assistant manager) | two lanes: `PERF-REVIEW-PREP-<date>` (the full two-layer `/performance-review`: CHECKS + ANALYSIS + prior-calls grading, not "numbers only"; an analysis job, so give it a model and ceiling that can carry it — redesign 2026-10-28, `ANALYTIC-SKILL-DESIGN`) and `ML-FRONTIER-PREP-<date>`; one PR `docs/reviews/<date>-weekly-walkthrough.md` by 05:30Z Thu |
| Thu 06:30 | walk-through WITH the operator (`trig_01CpyqNkhwqEjLAHq1Wrrh1b`) | performance, then ML + frontier as a dialogue; then dispatch `/perf-followup` (Opus) and turn agreed ideas into units/rows |
| Sat 07:23 | health review (`trig_013GU17584wu4HJYEkTF1KBk`, assistant manager) | one Sonnet lane runs `/health-review`, dispositions every finding, self-lands one PR |
| Mon 06:07 | weekly audit (`trig_017awLRNy4rmdL57NHKXehet`) | one Opus lane: CORE + rotating deep pass (ISO week mod 4), per `.claude/skills/weekly-audit/SKILL.md` |
| Tue 09:53 | research programme review (`trig_01GuB9kH3CM4WJCJUgAb1s8Q`) | one Opus lane updates the research map and five programme plans (`docs/research/programmes/`); the queue is fed ONLY from these; one self-landing PR |

Unchanged: research-ops 4×/day, daily reviews 05:52Z/17:52Z, lane check-ins. **Retired (operator 2026-10-14):** the Monday research-planning
session and `ROADMAP-PASS-<week>` rows; file the roadmap outcome on `WEEKLY-PLANNING`.

## Standing authorizations — the ladder is fully automated

**The whole ladder fires on evidence, with no human in the path** (operator grant, 2026-09-21): *"All the ladder decisions can be automated
— that is a standing mandate. Strategies can be promoted to live money without explicit operator approval if the evidence supports the
decision. I should just get a ping in realtime of the update and an evidence review in the next daily briefing."* **`config/mandates.yaml`
is the source for what is granted and armed** (field beats comment). Mandates: `MD-PROMOTE-S0-S1` (add a soak leg on a passing Stage-0
record, `add_risk` paper) · `MD-PROMOTE-S1-S2` (**add a leg to a REAL-MONEY roster** on Stage-0 + Stage-1 cost fidelity, `add_risk` real) ·
`MD-DEMOTE-S2-S1` (mirror net-negative net-of-cost: T3 ∧ net<0 over the last 40 closed trades, `derisk_only`) · `MD-DEMOTE-S1-OFF` (drop a
Stage-1 leg whose realized cost diverges) · `MD-KILL-QUESTION` (close a question that failed its pre-registered rule).

**When one fires: ping in realtime, then the evidence record in section 1 of the next brief** — a promotion to real money is never silent.
⚠️ **"If the evidence supports the decision" is the entire safety property**: a committed evidence record, named harness, stated n, **net of
the full cost stack**, clearing a rule registered BEFORE the run; **a claim in a PR body is not a record** — send such a promotion back.
⚠️ The old "`MD-PROMOTE-S1-S2` does not arm until D1 lands" block was cleared 2026-09-28 (CLAUDE.md; harnesses defaulted slippage/funding
to 0.0, measured +0.57R optimism); read the file for what is armed. ⚠️ **A mandate never authorizes judgement** — it fires on a stated rule
against a stated population or not at all. ⚠️ **Expiry is load-bearing**: an expired mandate stops authorizing. **Standing duty: keep moving
decisions out of the brief and into mandates**; a decision arriving twice in the same shape is raised as "should this become a mandate, and
at what bounds?"; a mandate that has NEVER fired is mis-specified or its condition does not occur — say which.

### Before any operator popup: classify the decision (operator directive, 2026-09-29)

Origin: PR #13698 asked whether to promote `slv_trend_1h`, which was `execution: shadow` with zero real fills and an `insufficient_n`
verdict. Operator: *"either we have enough data to decide, or we don't and then getting that data becomes a task which needs to happen so
that a decision can be made."* Before drafting any popup, classify it into exactly one bucket:
1. **Data-settled** — a committed evidence record decisively answers it (under a mandate, or a tier the manager holds with the standing
   "decide, ship, verify, then tell me" authorization, canonical § "Data-backed Tier-2/3 decisions"). **No popup**; act, then report in
   brief section 1 or 3.
2. **Data-missing** — the evidence does not exist or is below a stated floor (absent Stage-0 record, `n` below floor, cost-fidelity
   `inconclusive`/`insufficient_n`/`no_record`/stale, a `shadow` or never-soaked leg). **No popup either**: file the data task in
   `PIPELINE.jsonl` via `scripts/ops/pipeline.py` with `clears_when` and `origin.rerun` (queue unit, Stage-1 soak placement, replay/backfill).
   `scripts/ops/mandate_resolver.py` returns `NEEDS_DATA` and `file_needs_data()` files the row — read its docstring before hand-rolling one.
3. **Genuinely a preference** — two evidence-supportable courses and a values call with no standing policy. **Only this earns a popup**,
   in brief section 2, no cap on count.
A "preference" that is bucket 1 or 2 in disguise is the #13698 failure. Re-run the classification yourself on any lane's question.

## The daily brief

Rendered and **pushed before** the sync. Six sections, fixed order.

| # | Section | Contents |
|---|---|---|
| 0 | **What came due** | From the follow-through pipeline. Each must be routed the same day. |
| 1 | **Taken under mandate** | What fired, which mandate authorized it, and the evidence record. **A report, not a request.** |
| 2 | **Decisions for you** | Only what no mandate covers. **No cap.** |
| 3 | **What moved** | Lanes completed, what they concluded, what was killed. |
| 4 | **What is running** | Live lanes, spend, expected completion, anything blocked and on what. |
| 5 | **Spend** | Yesterday, month-to-date, against budget, cost per unit delivered, unrouted count. |

⚠️ **THE SYNC IS NOT MEASURED IN TIME** (operator, 2026-09-21): *"it takes however long it takes … I don't want us tracking an arbitrary
time limit to measure performance."* No target, floor or ceiling; **do not report session length as a metric** — the manager owes the WORK
being ready. ⚠️ **THERE IS NO CAP ON SECTION 2**: a queue outrunning one person is an argument for automating the class. ⚠️ **THE BRIEF MUST
BE SHORT, RANKED AND TRUE** (2026-10-04, BRIEF-FIX: at 737 KB it went unread): it carries a size cap and a soaks slot, ranks what needs
action first, states what it leaves out as a count, and ranks the same way as the daily Telegram digest (§ "The work system").

## The work system — due work must reach someone who acts (operator, 2026-10-04, binding)

Design of record: [`docs/plans/work-system-2026-10-04.md`](../../../docs/plans/work-system-2026-10-04.md) (row **WORK-SYSTEM**); operator:
*"that's not a band-aid, that's a structural fix … make sure it's canonized correctly in the manager skill."* MEASURED 2026-10-04: 366 items
due, 151 unrouted, 25 `ask_operator` items never delivered, 36 of 45 soak legs with no definition of done, a 737 KB brief nobody read. Now
the **VM computes due and pushes it**, and **silence is itself an alarm**. Full detail of both timers: pre-diet.

**What runs without you.** `ict-work-digest.timer` (hourly) is THE Telegram carrier, ONE message per hour, no second digest timer ever:
🆕 new since last (new `ask_operator`, a soak moving to `passed`/`mechanical_fail`, an expected-signal alarm breaching/clearing) → once a
day after 06:00Z the ranked summary (top 8, `ask_operator` first) → otherwise one "🟢 No new actionable items" line → "what changed". No
edge set is seeded silently (one count line per set at deploy). `ict-work-report.timer` (05:30Z) runs `scripts/ops/work_report.py`, which
persists `runtime_logs/work_reports/<report_id>.json` (`WR-YYYYMMDD-HHMMZ`), served at `GET /api/bot/work/report`; each section is marked
`ok`/`empty`/`absent`/`error`. Soak state is computed live (`soak_state.py::soak_states()`), never a field a session writes. The manager
cannot receive Telegram: every sent block is in `digest_log.jsonl`, served at `?since=<ISO>`. ⚠️ **The carrier's own death is not
self-detected**: a stale `generatedAt` or empty `digestLog` is the first incident.

### The daily review — TWICE a day, 05:52Z and 17:52Z, fired by a routine

The review routine IS the periodic check; its prompt names `GET /api/bot/work/report?since=<last_review.reviewed_at>`. Each run:
1. **Fetch and check before trusting**: `present: false`, a `generatedAt` not today's ≈05:30Z, non-empty `erroredSections`, or an empty
   `digestLog` over 12 h is the first incident — fix it first.
2. **Run `python3 scripts/ops/blocker_watch.py`** and resolve every finding the same turn (unblock, re-queue, dispatch, or drop with a reason):
   `STALE_BLOCK`, `NOT_RUNNING` / `NEEDS_LANE`, `OPERATOR_WAIT` (> 7 d), `UNPROVEN_OVERDUE`. Operator 2026-10-10: *"if most of the things
   here aren't actually blocked, then that's a problem that they were still marked as blocked."*
3. **Work every item: dispatch** (`state: routed`, `routed_to: <session>`, a checklist row for a build), **close** (`done`/`killed` with a
   `terminal_reason`) or **decide** (§ "Before any operator popup"). A `routed` item still due means its lane has not delivered.
4. **Every silence alarm gets a fix lane the same day**; anything due at a known time gets a `send_later` wake.
5. **Record the review**: `checklist.py header last_review '{report_id, reviewed_at, by, counts: {dispatched, closed, decided, carried}}'`, push.
6. **Roadmap hook**: `roadmap_map.py --report`, work its findings (§ "The roadmap loop").

**Prep always runs, and the scratch pad feeds it (operator, 2026-10-21, binding)** — the daily-review prep happens whether or not the
operator joins. Every run: **reads the scratch pad** (Google Doc "Metis — Ideas inbox" via the Drive connector), copies each new item
verbatim into `docs/claude/work/IDEAS.md` and triages it that run into a checklist row, a `research/queue` unit, or `killed` with a reason;
**publishes a short work-plan status** (what moved/is running, where work was left off, decisions waiting, scratch-pad items and homes,
next step on the standing priorities); **sends it to @claude_ict_comms_bot** with `send-ping` plus one "review ready" reminder.

### Manager ↔ lane: PUSH plus POLL (operator directive 2026-10-04, binding)

1. **PUSH (primary).** A lane wakes the manager when it finishes, is blocked, or has something to act on: `create_trigger(persistent_session_id=<manager>)`
   then `fire_trigger`; fallback a PR comment; the manager acts on a wake immediately. **Measured rule (MANAGER-WAKE-REFUSED, 2026-10-23): the wake
   works only from a session at lineage depth ≤ 7 (limit 8)**; `get_session` (no id) returns `lineage: {depth, limit}`. The manager must
   sit at depth ≤ 6, a rotation is created by a shallow session never by the manager, and a lane at 8 reports by PR comment.
2. **POLL (backup).** "Manager lane check-in" (`17 */3 * * *`) runs § "The operating loop" every 3 h with that one-line prompt; within it,
   restart/re-dispatch any lane that is dead, stalled, finished without pinging, or over ceiling.

**Which PRs the manager subscribes to (operator, 2026-10-25, binding — context-overhead cut).** ONLY (a) the ops-flags PR and (b) PRs the
manager itself opens. **Not lane PRs** (MEASURED: each subscribed PR injects a ~3k-token block per event; 11 lane PRs ≈ 150k tokens/h). Nothing
is lost: the lane fixes its own red CI; the lane wakes the manager when green and waiting; for a held PR set one `send_later` ~35 min out;
the 3-hourly check-in lands every green waiting PR; never archive a lane that owns an unmerged PR. Read narrowly (`get_trigger` on named
routines, `list_sessions(limit=10)`).

**Required dispatch block.** Every lane `create_session` has `source_url`; **`permission_mode: "auto"`** (default mode blocks on exactly
the prompts it needs to wake you); `model` explicit; a checklist row (id, lane, ceiling) written before dispatch. Never merge a manager
branch that has not landed on main into yours (incident #19876: its unsquashed commit carries a merge-slot claim for another branch and
fails manager-scope-guard). The prompt ends with this block, filled in:

```
You are lane <ROW-ID>, dispatched by Manager Session <date><letter> (<manager session id>);
its authority is the operator's (CLAUDE.md § Every session, step 1). Ceiling: $<N>.
WAKE THE MANAGER when you finish a deliverable, are blocked, or produce something it must act on:
create_trigger(persistent_session_id="<manager session id>", prompt=<what merged/deployed/observed,
what is blocked and on what>) then fire_trigger(<id>). Never set run_once_at (it fires twice).
If your PR waits on the manager (landing: hold), wake it AGAIN once CI on your head is green, with the PR
number and head sha; you stay subscribed to your own PR and fix red CI yourself. If that prompts, comment on your PR instead.
Then continue, or run close-out. Never stop to wait for direction.
```

**Reading scope for the lane (operator 2026-10-27, `CONTEXT-DIET`).** A lane reads only what CLAUDE.md § "Every session" step 1 names from
the canonical doc (RULE ONE; Permission Tiers + Data-backed Tier-2/3; Prime Directive; "Lanes answer to the manager" + "Reading is never
gated"). **Put in the prompt any other canonical section the lane's task needs** (e.g. "Generation Discipline Rule 3" for a build lane,
"Collapsed states" for a read-path lane) — that is how a lane learns it must read more than the default.

### The soak contract — what the manager does with each state

Stated once: [`OPERATING-PLAN` § 2 "The soak is MECHANICAL"](../../../docs/plans/OPERATING-PLAN-2026-09-21.md) — never restate it in a
dispatch, row note or contract. A Stage-1 placement needs a contract in `docs/claude/work/SOAKS.json` (`soak_state.py --backfill`). Per live
state: `passed` → promotion candidate, run `MD-PROMOTE-S1-S2` · `mechanical_fail` → dispatch the fix, the next clean trades re-soak it ·
`awaiting_first_trade` / `in_progress` → nothing, no deadline · `unknown` → we could not look; find out why. A grade's `kill` calls are
applied under `MD-DEMOTE-S1-OFF` / `MD-KILL-QUESTION` or filed with a reason, never just read.

### Decision batching

Operator decisions go out **batched**: a 🆕 line in the next hourly digest, all open ones in the daily summary and the report's
ask_operator section, each with options and a recommendation. Exception only for a decision that blocks live money or a live incident:
`send-ping` with `priority=urgent`.

### Day one for a NEW manager

1. Title yourself, read per § "Start of session". 2. **`list_triggers`** (routines bound to a session die with it): recreate/rebind both
**"Manager lane check-in"** (`17 */3 * * *`, prompt "run the operating loop (manager SKILL.md § The operating loop)") and the **twice-daily
review** (05:52Z, 17:52Z; prompt names `GET /api/bot/work/report?since=…` and § "The daily review") to YOUR session. 3. Tell every live lane
your session id by its own trigger. 4. `curl -sS 'https://ict-bot.duckdns.org/api/bot/work/report?since=<yesterday>'`; if absent/stale check
`/api/diag/services` for the two timers — fixing that comes first. 5. Run the review; clear `ask_operator` items first by classification,
not forwarding; record `last_review`, push, then answer.

## Manager handover (rotation)

> **Operator, 2026-10-13 (verbatim):** "we need to add a section to the manager skill to streamline handover - basically, I want the manager to handoff at their own discretion, we just need to make sure it's clear how to validate a complete handoff to the new manager before the current one turns off".

The manager rotates **at its own discretion**; what is not discretionary is the proof: **the old manager stays responsible until V1–V5 have
all passed, with evidence in the handoff doc.** `old` = outgoing, `new` = incoming. Full step text and rationale: pre-diet.

**When.** Context past **~650k tokens** (operator, 2026-10-24: "~650k + slimmer handover (Recommended)" — the switch itself must not eat the
capacity it saves), a natural boundary (after a planning pass or review), or degraded recall. **The check is periodic, not remembered**: every
run of § "The operating loop" and the first turn after every compaction starts with `get_session` on yourself and
`external_metadata.context_usage.used_tokens`; past ~650k, plan the handover for the next boundary and say so in the loop's operator line.
**Never mid-incident, never with a merge or deploy half-done.**

1. **PREPARE.** Write `docs/claude/work/handoffs/<YYYY-MM-DD>-<old-short>-to-new.md` (old-short = first 8 chars of the old id): live lanes
   (id, row, doing, owes); PRs needing the manager; operator asks in exact wording; every trigger/`send_later` targeting the old session (id,
   name); watched artifacts/PRs; capacity state; operator directives not yet in rows (put them in rows first); the new manager's first actions;
   the checklist below. **Do not commit it from the manager session** (`manager-scope-guard` refuses the `DOCUMENT-INDEX.md` row): a small Haiku
   lane (~$1; precedent HANDOFF-LAND-1022, #19521) self-lands it.
2. **CREATE.** A **SHALLOW session** (normally the assistant manager), **never the outgoing manager**, calls `create_session` (each
   manager-created manager adds one lineage level; limit 8, MEASURED 2026-10-23 a session at 8/8 was abandoned) with `model` Opus explicit, the
   same `environment_id`, `source_url`, `permission_mode: "auto"`, tags `["manager", "predecessor:<old id>"]`, title
   `Manager Session YYYY-MM-DD<letter>`, and a prompt: read this skill and the handoff doc in full; `CLAUDE.md` is in the system prompt; from
   the canonical doc read only the sections named in § "Start of session" step 2; perform V1 (including its own depth) and wait for the old
   manager's diff; no routine work yet.
3. **REWIRE.** `update_trigger` cannot change a trigger's target: (a) for each trigger on the old session `create_trigger` the same
   name/cron/prompt with `persistent_session_id=<new>`, then disable the old (delete only at step 5); (b) update every prompt naming the old
   id (research-ops, assistant-manager charter, review and check-in routines, live-lane briefs; lanes by fired trigger naming the new wake
   target); (c) re-subscribe the new session, **including the ops-flags PR**; (d) point `last_review.by` and any row naming the old manager at
   the new one, push.
4. **VALIDATE.** Each with evidence in the handoff doc:

| # | Check | Pass means |
|---|---|---|
| **V1** | Short diff | The new manager lists **only what differs** from the handoff doc, via targeted reads (`list_sessions(mine=true, limit=10)`, `list_triggers(enabled=true)`, `get_session` for depth); the old manager checks it; mismatches fixed. Record the new manager's `used_tokens` (target < ~80k for the whole handover, MANAGER-HANDOVER-SLIM). |
| **V2** | Trigger audit | New manager is subscribed to ops-flags (a call returns subscribed, not "already watched"); **zero enabled** triggers target the old id; every recurring routine, by name, exists, is enabled on the new one incl. "Manager lane check-in" (MEASURED 2026-10-23: dropped at two rotations, a 4.7 h gap); counts match step 1. |
| **V3** | Id sweep | Ops-flags held by the new session only; no enabled trigger prompt, charter or lane brief still names the old id (grep; show the same grep finds a known positive first, RULE ONE). |
| **V4** | Wake round-trips | old → new test trigger answered; assistant → new escalation answered; one live lane told the new id acknowledges. |
| **V5** | Operator notified in one message | New link, what moved, what did **not** and why. |

5. **STAND DOWN** only after V1–V5: old manager takes no further actions, its last message points to the new session **with a clickable link**, `https://claude.ai/code/<new session id>`, plus the new title (`Manager Session YYYY-MM-DD<letter>`), so an operator who opens the old session can reach the right one in one tap (operator, 2026-10-27); the **new** manager
archives the old one after confirming a wake lands in the new session, then deletes the disabled old triggers. **If any check fails the old
manager stays responsible and never goes quiet with a check open**; a stopped handover is a HANDOFF with gaps named.

**Handover checklist** (copy into the handoff doc, tick with evidence): handoff doc merged (PR #__) · new session created by a shallow session,
Opus, tags `manager` + `predecessor:<old id>`, depth __/8 · triggers recreated (n = __ of __), old disabled · prompts and checklist refs
updated · new manager subscribed incl. ops-flags · V1 diff · V2 audit (0 on old id, incl. check-in `17 */3 * * *`) · V3 sweep with positive
control · V4 round-trips (trigger id, assistant evidence, lane id) · V5 operator told · STAND DOWN done (old manager's last message links the new session, https://claude.ai/code/<new id>).

## The ladder the manager is moving things along

Stage 0 backtest (edge net of the FULL cost stack) → Gate 1 → Stage 1 soak (`bybit_1` · `alpaca_paper`; MECHANICS on 1–2 clean trades,
2026-10-15) → Gate 2 → Stage 2 live + mirror (identical rosters and trades; the mirror's net-of-cost window is the DEMOTION signal).
**Edge is decided offline; a book only checks mechanics and cost** — a lane proposing Stage 2 on live-book evidence is a category error.
Canonical: CLAUDE.md § "The promotion ladder".

## Closing the session: publish the record, then ping

**Operator, 2026-09-22, verbatim:** *"once you actually finish merging and deploying all of the work and you're actually ready to close out
the session, then make the summary and then post it on the site so that I can refer to it without having to go back into the chat. And ping
me also when everything is fully closed out."* A chat reply is not the record.

**The gate — publish and ping only when ALL are true** (a partial close reported as a close is the drop this contract prevents):
1. Every PR the session opened or drove is merged, or HELD with the blocker on the PR and in `PIPELINE.jsonl` ("waiting on CI" is not closed).
2. Deployed means deployed: land, wait for `ict-git-sync`, restart the unit, OBSERVE the running process (`/api/bot/config` reports the FILE).
3. Every row has a true state (no `in_flight` against a lane not working; `landed_unproven` names its closing observation).
4. Every finding is fixed, filed (pipeline or checklist — not chat, PR comment or memo) or flagged. 5. Doc sweep: stale docs corrected.
6. `close-out` run, all seven checks, also when stopping early. 7. Every finished lane archived, none while it owns an open PR.

**Then, in order:** PUSH FIRST (the checklist is the live Workflow page); PUBLISH THE SUMMARY AS A PAGE (Artifact tool) with: what each lane was
dispatched to do and what became of it; what MERGED (shas), DEPLOYED and OBSERVED, never collapsed; verified vs waiting with the specific
observation each needs; the operator's decisions in their words; **the session's own errors**, plainly; next steps in order with why the first
is first; a receipt (sessions run, spend per lane vs ceiling, total, archived). **THEN PING** with the link and one line of state — an early
ping trains the operator to re-check. ⚠️ If the gate cannot be met, publish anyway with the unmet conditions named at the top.
