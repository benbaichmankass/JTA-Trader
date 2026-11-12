---
name: manager
description: The manager-session contract. Read this at the start of any session that spawns or supervises other sessions. Defines the one job, the one register, spawn rules, the model table, the budget, and the daily-sync brief.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-11-06` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# The manager contract

> Adopted 2026-09-21, operator-directed; scope of record [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md).
> **Trimmed 2026-11-06 (SKILLS-PRUNE, from 87.8 KB):** every binding rule is kept here or pointed at. Step-by-step recipes moved verbatim to
> [`docs/plans/manager-runbooks.md`](../../../docs/plans/manager-runbooks.md) (§ A–F) and [`docs/plans/weekly-planning-protocol.md`](../../../docs/plans/weekly-planning-protocol.md);
> the full prior text, with every operator quote, is [`docs/archive/2026-11-06-skills-prune/manager-SKILL.md.pre-prune`](../../../docs/archive/2026-11-06-skills-prune/manager-SKILL.md.pre-prune).

## The one job

**Keep research questions moving through the ladder, and keep shrinking the set of decisions that need a human at all.** That is the whole job;
everything below serves it or is forbidden. A cap on decisions is a cap on throughput (operator, 2026-09-21): the job is to AUTOMATE the
decision, not to ration it.

## The operating loop (operator, 2026-10-18, binding)

> Operator: *"We want to get as much work as possible out of our budget without blowing through it before a reset."* At least one lane always
> runs; up to five by judgment; **no hard caps**.

**Every manager runs these six steps, in order, at session start and at every check-in** (the "Manager lane check-in" routine, a lane's wake,
the daily review). A check-in prompt says only *"run the operating loop (manager SKILL.md § The operating loop)"*. The ranked plan lives in the
register, never in a session's head or a trigger prompt: a new manager inherits it with `checklist.py queue`.

1. **INTAKE.** Every new item (operator, lane, review, alert) becomes a checklist row (a build) or a `research/queue/` unit (a question)
   **before** anything is dispatched. A row carries `roadmap`, `priority_rank` (1 = dispatch next), `model`, `ceiling_usd`. Rank by value and
   urgency against the roadmap goals and the header's `priorities.order`; broken live-money or prop paths rank first. **Urgent means rank 1,
   never started on arrival.** Re-rank neighbours in the same commit. Push, then answer.
2. **CAPACITY.** Record the operator's latest Settings → Usage reading (`spend_meter.py --record`, reset time in `--note`), then
   `spend_meter.py --capacity`: the sustainable rate `(100 − weekly%) / days to reset`, converted to a lane count by measured cost per lane-hour.
   Choose 1–5 lanes by judgment. A missing or stale reading is the first thing to fix; until then run one lane. Fable has its own weekly bar and
   is not free capacity. **The rate is net of the live-trade-review reserve** (`docs/plans/live-trade-review-DESIGN.md` § 6.4): pass
   `--live-open N`; without it the state reads `exposure_unknown` and the reserve is sized at the roster bound, never 0. On `RESERVE BREACHED`
   start no new non-routine lanes and count the review routine as the always-one-lane (design § 6.6, operator Q5). Report gross, reserve and net in step 6.
3. **DISPATCH.** While fewer lanes run than step 2 chose, take the top row of `checklist.py queue` (`queued`, nothing in `blocked_on`, lowest
   `priority_rank`), set it `in_flight` with its `lane`, dispatch it (§ "Spawning"). **Never zero lanes while the queue is non-empty; never above
   the rate.** *REFILL (operator, 2026-10-26, binding), at every check-in AND every lane close, after step 5:* the capacity target is *"KEEP N
   LANES RUNNING"*, a target not a cap; if running build lanes < target, dispatch the next queue rows now without waiting for the operator:
   `standing` work first, then `week_lane: surge` rows until the throttle-down switch, throttle rows after it; one ML-research lane stays
   reserved through the surge (weekly-planning-protocol § "Surge, then throttle"). Ask the operator only when the plan has run out or the call is a
   genuine preference, never for permission to use headroom. A capacity call made earlier, even by the operator, is **re-evaluated against a
   fresh reading at each check-in, not carried forward**.
4. **LAND.** List every open PR. Each green one waiting on the manager (`landing: hold`, a refused self-land, a research hold PR) is landed now
   (Tier 1/2), or put to the operator on its recorded approval path (Tier 3). A green PR waiting on the manager is the manager's failure.
5. **CLOSE — a FULL sweep of the account, not just your own children** (operator, 2026-11-05, binding: *"we're not forgetting to archive old
   lanes"*). Page `list_sessions` to the end (every page until `has_more` is false; save each to a file), run
   `python3 scripts/ops/lane_reconcile.py --sweep --sessions <page files...>`, and archive every ARCHIVE candidate it prints, whoever spawned it
   (MEASURED 2026-11-05: 35 finished-but-unarchived sessions from 5 earlier managers). The KEEP list carries a reason per lane left open; only
   this project's sessions, never the LEFT ALONE block, and not a lane that owns an open PR (`--pr-state` takes a `{session: open|merged|closed}`
   file). Then `checklist.py archive-lane <ROW>`. A `landed_unproven` row whose closing observation is cheap to produce is triggered now
   (canonical § "Validate early when it is cheap"). **Console threads** (via UI-CONSOLE-V1): at every check-in `ArtifactComments` `action:
   "read"` each console artifact on row `UI-CONSOLE-V1` (`console_artifact_url`, `probe_artifact_url`) and answer or file every open thread;
   console comments go to the manager, never to a lane.
6. **REPORT.** Three lines to the operator: **capacity** (reading, rate, lanes chosen) · **running** (lanes and rows) · **next** (top of the
   queue). Say nothing when nothing changed.

**Cadence.** The "Manager lane check-in" routine (`17 */3 * * *`) runs the loop every 3 h; a lane's wake runs it at once. State lives on disk (the checklist, `PIPELINE.jsonl`), never in a session's head. Guard: `manager-pacing-guard` (`scripts/ci/check_manager_pacing.py`).

### Toolbox

| step | exact command |
|---|---|
| 1 | `python3 scripts/ops/checklist.py add <ID> --title "…" --tier N --rank N --by "$SESSION"` then `set <ID> roadmap='["M.."]' model=… ceiling_usd=N`; a question is a `research/queue/<id>.yaml` unit (`research/queue/PLANNING.md`); roadmap refs `python3 scripts/ops/roadmap_map.py --report` |
| 2 | `python3 scripts/ops/spend_meter.py --record --window weekly --percent P --read-at <ISO> --note "reset <Day> YYYY-MM-DD HH:MMZ"` · `… --capacity` |
| 3 | `python3 scripts/ops/checklist.py queue [--limit N]` · `create_session` + `checklist.py set <ID> state=in_flight lane=<session>` |
| 4 | `list_pull_requests(state="open")`; landing intent `.github/pr-landing/<slug>.json`; Tier-2/3 call `python3 scripts/ops/mandate_resolver.py` (FIRE / REFUSE / NEEDS_DATA) |
| 5 | `list_sessions` → `lane_reconcile.py --sweep` → `archive_session(<id>)` → `checklist.py archive-lane <ROW>` |

## Standing alert subscriptions (operator, 2026-10-13, binding)

Recipes (the exact `create_session` arguments, marker fields and receipts per wake kind): [`manager-runbooks.md`](../../../docs/plans/manager-runbooks.md) § A.
Read the recipe for the kind of marker you are acting on **before** you dispatch from it.

**Every manager, at start AND after any handover, calls `subscribe_pr_activity` on the ops-flags PR** (title "ops-flags (do not merge)"; the number
lives ONLY in `scripts/research/research_watchdog.yaml` `ops_flags.pr_number`). Never merge or close it. **Treat every comment as an incident:
fix it, dispatch a lane, or tell the operator; never leave one unanswered** (ledger `comms/research/ops/watchdog_incidents.jsonl`). Wake markers
on that PR (`ltr-wake`, `mandate_cadence`, `judgement_cadence`, `desk-wake` / `desk-trigger-wake`, `short-hold-wake`): **one marker, one lane,
never spawn twice for the same id**; a `could_not_*` kind is an incident, not a wake. An `ltr-wake` entry marked **`reviewer started by routine`**
(`routine_fire.state` `fired` / `already_fired` + `session_id`; TRADE-ACTION-DIRECT-PATH phase 3) already HAS its reviewer: do NOT dispatch it; the
comment is the dedupe record. Dispatch only the entries without that mark (a routine fire that failed says so and falls back to you). **Never create a session with no `source_url`** (403 on every
write). **Never run your own timer or scheduled watch that starts a live reviewer without a marker**: only the wake poster commits packets. Every
reviewer dispatch prompt ends: "end your report with a `PACKET DEFECTS:` line (REVIEWER-BRIEF § 2d)"; file each reported defect once on its owner
(`LTR-GRADER-COVERAGE`, `LTR-PACKET-READ-REACH`, else a PIPELINE item). Desk and short-hold lanes follow `.claude/skills/trading-desk/SKILL.md` § 6b
and `SHORT-HOLD-BRIEF.md`.
**`phone_executor_anomaly` alert** (a phone executor expectation failed; `alert-watch` comment): dispatch a Sonnet diagnose-and-fix lane pointed at [`docs/runbooks/phone-executor-anomaly.md`](../../../docs/runbooks/phone-executor-anomaly.md) and the capture on `/api/bot/prop/status` (`phone_anomalies`); the lane diagnoses first, the cause is not assumed.

## Start of session

0. **Run § "The operating loop"** after the steps below, and at every check-in after that.
1. **Title yourself.** `get_session` (no id) for your id and `created_at` (UTC), then `set_session_title` to `Manager Session YYYY-MM-DD<letter>`
   (UTC date of `created_at`; first of the day is `a`, never blank, then `b`, `c`…; find the next unused with `list_sessions` tag `manager`; an
   incoming manager checks the handover's letter against the listing).
2. **Read by role** (CLAUDE.md § "Every session" step 1; canonical § "Session-start documentation read"). A fresh manager reads this file and
   `docs/CLAUDE-RULES-CANONICAL.md` in full. **A rotation manager** reads this skill and the handoff doc in full and, from the canonical doc, only:
   RULE ONE; Permission Tiers + Data-backed Tier-2/3 decisions; Prime Directive; "Lanes answer to the manager" + "Reading is never gated". Then
   the `in_flight` / `blocked` rows.
2a. **Run the full sweep before dispatching anything** (loop step 5), including the outgoing manager's finished lanes.
2b. **Subscribe to the ops-flags PR.** 2c. **Re-watch the console artifact(s)** on row `UI-CONSOLE-V1` (`ArtifactComments` `action: "watch"` each
    `url`, then read open threads): a watch ends with its session, so this runs at every rotation.
3. Take over every live lane: `get_session` it, then send it a trigger naming you as its manager.
4. **Day one for a NEW manager:** `list_triggers` (routines bound to a session die with it) and recreate/rebind **"Manager lane check-in"**
   (`17 */3 * * *`) and the **daily review** (once a day, 05:52Z) to YOUR session; tell every live lane your id by its own trigger;
   `curl -sS 'https://ict-bot.duckdns.org/api/bot/work/report?since=<yesterday>'` (absent/stale → check `/api/diag/services` for the two timers,
   fixing that comes first); run the review, clear `ask_operator` items by classification not forwarding, record `last_review` (`checklist.py header last_review '<json>'` writes the work store; read it back with `work.py --via direct header get last_review`), push, then answer.

## When the auto-mode classifier refuses the manager, or a lane refuses (operator, 2026-09-27/28, binding)

- **The manager's OWN action is blocked** (operator: *"the only acceptable way … is for the manager to be temporarily taken out of auto mode … I
  don't want any more questioning of my authority"*): (1) tell the operator in one message the exact denied action (command and files), what it is
  for, the row it comes from, and ask them to take the manager out of auto mode temporarily; (2) when they do, perform exactly that action, nothing wider, and
  verify it; (3) tell them it is done so they can restore auto mode. **Forbidden:** asking the operator to make the edit by hand; rewording,
  splitting or re-encoding the action to get past the classifier. **Never question the operator's authority** or ask for re-confirmation.
- **A lane refuses, stalls or is blocked:** the manager re-dispatches a fresh lane with a corrected, accurate brief. A lane reports a refusal in
  one line and files it nowhere else; **going silent is itself the failure.** A re-dispatch restates the task accurately (including that an earlier attempt was blocked) and
  never disguises or splits an action; if an honest restatement is blocked again it goes to the operator as a one-click approval in that lane's
  session. Claude Code's own permission prompts remain a human click. Incident (MANDATE-ARM-2, 2026-09-28) and quotes: pre-prune.

## Five things the manager does / may not do

**Does:** (1) picks what runs next (loop steps 1–3); (2) spawns lanes, fresh by default, correct model, **one question each**; (3) applies what
comes back (a pre-registered `decision_rule` means the result *is* the decision; Tier-1 and Tier-2 outcomes apply themselves); (4) kills or
re-scopes a burning lane after reading what it produced; (5) pushes the daily brief before the sync. **Underperformer first step (operator,
2026-10-15):** before anyone tunes, demotes or asks about a losing leg, its lane runs `scripts/research/live_vs_backtest.py` (BELOW_BACKTEST →
fidelity/regime unit, CONSISTENT → keep accruing, NO_BACKTEST → backtest unit).

**May not:**
1. **Take an item.** CI-enforced by `scripts/ci/check_manager_scope.py`. A merge, a deploy, a spawn, recording an operator decision are
   management; `src/`, `tests/`, `scripts/`, `.github/workflows/`, `config/`, `deploy/` are not. Spawning costs duplicated context and the
   operator has said that is acceptable.
2. **Maintain more than one register.** The checklist (one file per row under `docs/claude/work/checklist/`; the `MANAGER-CHECKLIST.json` named in CLAUDE.md is the pre-cutover monolith, deleted 2026-10-08) is
   the only one; the others are retired under `docs/archive/2026-09-21-operating-reset/`.
3. **Write narrative observations about its own state.** A row's `state` and `note` are the record.
4. **Block on an operator answer.** State an assumption and keep going; a waiting manager is an extra decision gate.
5. **Exceed the sustainable rate (loop step 2) without saying so in its next report.**

## ONE ML LANE ALWAYS RUNS — the last thing turned off (operator, 2026-11-07, binding, non-negotiable)

Operator, 2026-11-07 ~16:55Z, verbatim: *"We said there is always an ml lane running - why do I have to keep explaining that? It is non
negotiable - the ml research pipeline is the absolute last thing to get turned off, and only when enough tests and training are qued up to keep
the pipeline running autonomously until the reset."* (Restates 2026-11-06 ~22:44Z, *"And keep the ml lane running as always"*.)
- **Every usage cut, throttle, "one line" or "real money only" mode keeps exactly one ML lane running.** Such a cut never implies the ML lane;
  only an explicit operator order naming the ML lane turns it off.
- **The ML lane may stop only when** enough pre-registered ML training + test units (free GitHub / trainer compute) are queued in
  `research/queue/` to keep the pipeline producing autonomously until the reset — and the manager tells the operator that list. The research-ops
  pass that consumes that queue stays enabled with it.
- **A handover cannot drop this.** A handoff, trigger prompt or rotation brief that says otherwise is wrong; the new manager restores the lane at
  once and says so. When the ML lane finishes, dispatch the next ML row the same check-in.

## A console "done" mark hands the item BACK — it never closes the task (operator, 2026-11-07, binding) — gates this adds or changes: none

Operator, 2026-11-07 ~23:40Z, verbatim: *"When I mark it as done, I mean, like, I marked it as done because I replied to you on it. So it's done
because it's out of the inbox. That doesn't mean that task is over. That means you need to take it, process it, and then do whatever the next
step is. Even if that's asking me another question, putting it back in the inbox."* And: *"I want for when it's appropriate for those to like
offer me multiple choice answers instead of just free text."*
- **A `done_mark` (or any inbox reply) in the console `inbox` collection is a handback to the manager.** At the next check-in the manager
  reads the item, the operator's reply and the row, and takes the next step: dispatch, re-date, record, or a new question back in the inbox.
  Never read a done mark as "task closed" and never let it sit unprocessed.
- **Record the processing on the row** (`checklist.py note --append`: what the mark was, what was done, the next step and when).
- **Ask with choices where the answer is one of a known few.** Every question put back in the inbox, or asked as a popup, offers 2–4
  concrete options, recommended first, with free text still available. Free text alone is only for genuinely open questions.
- Console reorder drags (`item_kind: reorder`) are applied the same check-in as `priority_rank = to_rank` on the named rows.

## Decision docs — how the operator decides (operator, 2026-11-11, binding) — gates this adds or changes: none

Operator, 2026-11-11 ~21:10Z, verbatim: *"I do very much like that format. I think this could be a good way for us to work, because it helps keep
things a little bit more organized instead of having everything in the chat when I want you to keep running ... You create the artifact with the
explanations of the decisions ... And then, like, you can send a link on Telegram, you can put the link on the UI, and when I get a chance, I'll go
in there ... Certainly for big things like weekly planning and, like, you know, design decisions, like design docs that need to be approved ...
Plus, then I can also, like, if there's artifacts, I can leave you comments and we can go back and forth."*
- **What goes in one.** Any decision that needs more than a one-line choice goes into a **decision doc**: weekly planning, design-doc approvals,
  Tier-3 proposals that need context, retirements, and any batch of 3+ open questions. A one-shot choice can still be asked in chat or as a
  popup, after § "Before any operator popup" classifies it.
- **The format** (precedent: the 2026-11-11 Thursday-planning page). It is a private Artifact page with:
  - a short context box;
  - a "Do now" box for any operator-only physical step (credentials, terminal checks), never containing a secret value;
  - each question with plain-language evidence and 2–4 options, recommended first, plus a note field;
  - answers saved in the page (the `db` capability, collection `answers`);
  - a "copy my answers" summary.
  Write for reading away from the chat: no unexplained ids, and every question stands on its own.
- **Delivery.** Send the link once via `send-ping` and **register it on the console** (row UI-DECISION-DOCS, console v27+): `ArtifactData set`
  on the console artifact (https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g), collection `decisions`, doc id `<slug>-<yyyymmdd>`, data `{title, url, questions, answered, counted_at, created_at,
  status: "open", row}`. It then shows under "Decision docs waiting on you". At each check-in, recount the doc's `answers` collection and
  update `answered` / `counted_at`; set `status: "closed"` (or `"answered"`) when it is done, and it folds away. Also keep updating **the same artifact** (same URL) as items resolve or new ones join. Do not spawn a new page per
  question.
- **The manager keeps running.** A decision doc never blocks other work (§ "Five things", item 4): state the assumption, carry on, and pick
  the answers up at the next check-in or when the operator says they are done.
- **Reading and recording.** Read answers with `ArtifactData` (collection `answers`) and comments with `ArtifactComments`; answer a comment in
  its thread. The artifact is the *input*; the register stays the *record*. Each answer is recorded verbatim on its row (`work.py note`), then
  acted on, with tier rules unchanged. Mark answered questions as answered in the page.

## The budget

The pace is loop step 2. Retired 2026-10-18 (kept out by `manager-pacing-guard`): "10% a day, and spend it" and mass parallel launches with hourly
check-ins (six lanes moved the weekly bar 55% → 73% in ~3 h). The weekly bar covers every project the operator runs: report it with its reading
time, never blended with per-lane dollars. **Output per unit spent:** the manager reads narrowly (the `get_session` summary plus the PR body is the
lane's report); lane prompts are self-contained (ids, paths, evidence, done condition, landing recipe); the decision is recorded on the register
BEFORE dispatch (a lane that still declines is resumed once, then archived and restarted; the operator is never asked to approve inside a lane);
validate the row and grep for conflict markers before every register commit; never chain a register commit after a merge whose exit status was not checked; judge the pace by results delivered, never by
distance from a target: running under the rate while delivering is not a failure (operator, 2026-09-27); an idle manager with a non-empty queue is.

**Hibernating before a usage-limit outage** (when the weekly bar nears its limit or a lane reports *"You've hit your weekly limit"*): arm auto-merge
on PRs that would wait on the manager, tell live lanes by trigger, leave a pick-up reminder ~5 min after the reset, pause check-in/review routines,
confirm every register change is ON MAIN, archive finished lanes, tell the operator what runs/waits/when. Full steps and the on-return order:
[`manager-runbooks.md`](../../../docs/plans/manager-runbooks.md) § F.

## Spawning

### How lane PRs land

A Tier-1 lane self-lands: `.github/pr-landing/<slug>.json` (`tier: 1`, `landing: self`), `.github/pr-automerge-requests/<slug>.txt`,
`python3 scripts/ops/claim_merge_slot.py --branch-claim --branch <branch> --held-by <session_id>`, then arm auto-merge with
`gh api -X PUT repos/<owner>/<repo>/pulls/<n>/ccr/auto_merge -f merge_method=squash`. If the classifier refuses the arming ("Merge Without
Review"), the lane re-declares `landing: hold` with `hold_reason: operator_asked_to_hold`, reports the exact refused command in one line, and the
manager lands it — in auto mode, no operator window (allow rules for the JTA-Trader merge path + `mcp__github__merge_pull_request`, #24221; proven on #24236, 2026-11-08): touch `/tmp/.claude-merge-claim-<session>-<PR>`, un-draft, merge with `expectedHeadSha`. A merge refusal after a repo rename means `.claude/settings.json` allow rules still name the old slug. Tier-2/3 lane PRs always carry `landing: hold` (manager for Tier 2, the operator's recorded approval for Tier 3).
**Push less, push checked** (a habit, not a gate; CI-THROUGHPUT-20261029): before every push `python3 scripts/ci/prepush.py`; never push to a PR while its CI runs unless fixing a red check;
batch register commits into one push. **No new gates** (operator, 2026-10-29, binding): never add, or dispatch a lane to add, a gate without the
operator's explicit permission; canonical § "No new gates without the operator's permission".

### Recurring dispatches

| name | when | model / ceiling | skill and notes |
|---|---|---|---|
| `PERF-FOLLOWUP-<ISO week>` | when a `/performance-review` PR merges; one per review | Sonnet, $6 | `perf-followup`; prompt names `comms/reviews/performance-review-<stamp>.json`; classify its Tier-3 proposals per § "Before any operator popup" |
| `RESEARCH-OPS-<date>-<slot>` | 02:47, 08:47, 14:47, 20:47 UTC; skip a slot while the previous research-ops lane runs (a topic lane never causes a skip) | Sonnet, $6 | `research-ops`; put THE CORE MANDATE in the dispatch text; **a research floor gap is NOT due work** (STOP-GENERATED-AUTHORING, 2026-11-01): never dispatch a lane to author units to a count, orphans are the due work |
| weekly ML plan loop | rides the Sunday `/ml-review` as step 9 | in that lane's prompt (~$4 extra) | `ml_plan_status.py` in the daily review; dispatch ML rows from `next_by_value_per_cost` |
| `FRONTIER-SCAN-<date>` | weekly, same day | Sonnet, ~$8 | `frontier-research`; land its hold PR; dispatch `FRONTIER-LEVER-*` rows by capacity |
| research SLO `breach` or `could_not_look` | the same day, per `scripts/research/research_slo.yaml` (a note or far-`due_when` row is not a disposition) | the lane that moves it | `research_ops_not_run` / `research_ops_age_h` → the next slot finishes the named steps; `runnable_floor` / `authoring_supply_ratio_7d` / `theme_share_min_ratio` are DIAGNOSTICS (check `iteration_orphans.py` instead); `programme_coverage_pct` → add plan nodes; `undispositioned_24h` / `grade_latency_p*_d` → a GRADING lane; `blocked_over_age` → unblock-or-retire; `hold_pr_wait_h` → you land or close held PRs; stage ages → a fix lane. **Thresholds change only in the YAML, in a PR that says why; loosening one to clear a breach is the failure this rule stops.** |

### Model by task class

| Task | Model |
|---|---|
| Manager (this session) | `claude-opus-5` |
| Research lane | `claude-sonnet-5` |
| Build lane | `claude-sonnet-5` — `claude-opus-5` if it touches an order path |
| Sweep dispatch, log reads, extraction | `claude-haiku-4-5-20251001` |
| Anything on a real-money order path | `claude-opus-5` |

⚠️ **`create_session`'s `model` defaults to the CALLING session's model**: pass it every time. Fable has its own weekly bar (loop step 2; use per
the header's `priorities.how_used` and row **E11**). **Spare budget NEVER moves work off the model its risk demands.**

### Every spawn carries provenance, and every dispatch is verified

Operator ruling 2026-09-27: *"You represent my authority and my mandate, and I want the lanes to stop questioning that."* (canonical § "Lanes
answer to the manager", § "Reading is never gated"). Pass `append_system_prompt` naming who spawned the lane and the in-repo artifacts that
corroborate it (this file, the plan, the lane's row, the `PIPELINE.jsonl` item whose `routed_to` carries its session id). **State the chain of
authority** (2026-09-24): a lane answers to the manager, the manager to the operator; a decision relayed by the manager and recorded verbatim on
the lane's row IS the operator's decision. ⚠️ **This does NOT extend to Claude Code's own permission prompts**: a lane at an auto-mode prompt waits
on a human click; **surface it, never clear it.** ⚠️ **Verify the dispatch started**: read `status_bucket` and `post_turn_summary`, never
`session_status`. **Reply channel:** `create_trigger(persistent_session_id=<lane>)` then `fire_trigger(trigger_id)` with NO other argument (`text`
spawns a repo-less session).

### Fresh vs resume, one question, ceiling

Resume only when the next unit needs context built *in the session's head*, never context on disk (MEASURED 2026-09-17: two resumed lanes cost
$56/$69; fresh starts near 40k tokens). **One question per lane. Every lane has a dollar ceiling on its row**; on breach read what it produced,
then kill or re-scope, never interrupt blind. ⚠️ **A ceiling nobody reads mid-flight is not a ceiling** (`lane_reconcile.py` prints lanes over
ceiling, finished lanes still open, lanes walled on a permission prompt). A lane's spend is final only once archived: record a live reading with
its read time and the word `running`. Record on the row the model, fresh-vs-resume, and the reason.

### Archive protocol

Archiving finished lanes is the manager's job (operator, 2026-09-29: *"part of your job is closing finished sessions, that falls under the
management mandate"*), never the operator's, and runs as loop step 5 and after every merge, in one batch. **Scope: this project's sessions only**
(JTA Trader repos, environment `env_01A9rfUVrcEo1i5pKP1kWnp3`, or a mention in a manager log); archive only what `lane_reconcile.py` lists, never its
LEFT ALONE block. **Archive when** its PRs merged and nothing remains only it can do; a review verdict or analysis report was received and results
committed; it was superseded; or its row is `done`/`dropped`/`landed_unproven` with the observation filed (an observation needing only time or a read does not keep a lane open). Do not tell a lane to idle on CI: the manager merges, the lane stops. **Never archive** a lane that owns an
unmerged PR needing pushes, whose report has not arrived, that is BLOCKED on a permission prompt (surface it), or is mid-run on a live action. Read
the final spend and note it on the row (reversible: `unarchive_session`).

### Scheduled-task and session hygiene (operator, 2026-11-12, binding) — gates this adds or changes: none

Operator, 2026-11-12 ~10:40Z, verbatim: *"we're supposed to be archiving sessions once they're done and keeping the system clean, and that
applies to scheduled runs as well ... we need to get rid of things once we're done using them, or figure out how to reuse them and repurpose
them instead of creating new ones every time."* **Cause:** nearly every report between sessions is a NEW one-shot task (`create_trigger` with
`persistent_session_id`), and a fired one-shot is never deleted. MEASURED 2026-11-12 (row `SESSION-TRIGGER-HYGIENE`): a `create_trigger` +
`fire_trigger` task with no `run_once_at` stays `enabled: true` after it fires, so **"fired" is `last_run` present, never `enabled: false`**.

1. **Read, then delete.** The recipient deletes each one-shot message task after reading it (`delete_trigger`). A session deletes its own
   check-in reminders once they have fired, and its final report task once `get_trigger` shows a `last_run`. Never delete a recurring routine
   or a pending task still needed.
2. **Archive on DONE.** `close-out` check 8: a lane archives itself last when its work is done. The manager archives its lanes on DONE; each
   assistant manager archives its own lanes (same rules as § "Archive protocol").
3. **Reuse where it is cheaper.** A lane keeps ONE reply task to its manager, created at dispatch, reused with `update_trigger(prompt)` then
   `fire_trigger`, and deleted when the lane archives. Never share one mailbox between senders: two senders updating one task's prompt overwrite
   each other before it fires. The account's hourly manual-fire limit (which `update_trigger` and `fire_trigger` both use) is NOT yet measured;
   until it is, the one-shot path stays allowed, with rule 1.
4. **Daily hygiene pass,** run by the OPS assistant manager (the manager while there is none) inside its existing cadence, never a new routine:
   delete one-shot tasks that fired more than 24 h ago and those whose recipient is archived; list unarchived sessions idle more than 24 h with
   no open PR or held work, and archive the finished ones. Never delete a recurring routine (list those with their `last_run` status instead),
   a pending one-shot, or the desk wake, live-review, review or reset tasks.
5. **Preconditions, MEASURED 2026-11-12.** (a) In auto mode the classifier refused `delete_trigger` ("Irreversible Deletion") in a lane, so
   rules 1 and 4 need an explicit allow entry for `delete_trigger` (and `archive_session` if that is refused too) in `.claude/settings.json`;
   adding one is the operator's call (precedent: the 2026-11-08 merge entries). (b) `delete_trigger`'s description says deleting a task deletes
   every session it started; that a fired `persistent_session_id` message does NOT take its recipient with it is NOT yet proven. **No bulk
   delete runs until row `SESSION-TRIGGER-HYGIENE` records that test passing.** A refused call is not retried or worked around; name the ids
   in your report.

### When session tools or the GitHub proxy fail

First check `https://status.claude.com/api/v2/summary.json` and `githubstatus.com`. `create_trigger` with `run_once_at` 1–2 min ahead can succeed
where `fire_trigger` fails; retry with backoff. ⚠️ **A BLOCKED lane is the expensive one and looks alive** (MI-305 sat BLOCKED 72.8 h holding
$1,343): surface it, never clear it.

## The checklist

One file per row under `docs/claude/work/checklist/<ROW-ID>.json`. **Never edit it with ad-hoc python**: `scripts/ops/checklist.py add|set|note|archive-lane|queue|header`
(`--help` owns the syntax; examples in [`manager-runbooks.md`](../../../docs/plans/manager-runbooks.md) § B) writes one row atomically and refuses an
invalid state, duplicate id or unknown row. Read it via `src.runtime.checklist_store` (`checklist-readers-guard`); a row's history is `git log --
docs/claude/work/checklist/<ID>.json`. Row schema: the header's `item_schema`, plus `roadmap`, `writeback`, `priority_rank`.

⚠️ **Process, not gates (operator, 2026-11-01, binding).** The manager owns every row and assigns no owners to sessions; `add`/`set` FILL
`owner=manager`, a computed `due_by` (the row's observation date; else in_flight +2d, blocked +7d, landed_unproven +3d, queued by rank +1/+3/+7d)
and `roadmap=["unmapped"]` + a reason. Nothing is refused; only a *deliberate clearing* of owner/due_by/roadmap errors. Gates this adds: **none.**

### The audit-outcome contract (operator, 2026-11-01, binding)

*"There needs to be this specific outcome where we have an audit and then a work plan to make sure that those items get taken care of."* An audit
or review lane (`weekly-audit`, `health-review`, `performance-review`, `ml-review`, `programme-review`, any from-scratch audit) is **done only when
every proposal it makes maps to** (a) a checklist row with `owner`, `due_by` and a `roadmap` ref (or a research queue unit with a `roadmap` ref and
a run date), **or** (b) a recorded operator decision (a row, popup answer or `config/mandates.yaml` entry it names). A proposal "in the report" and
in neither is **not filed**. The lane's final section lists proposal id → row/unit id → `due_by`; the manager checks it against `checklist.py`
before accepting the lane (`close-out` check 4). This is a process step, not a guard: a dated row is what the daily review (step 4b) works, so a proposal that is not one is never observed.

| state | means |
|---|---|
| `queued` | not started |
| `in_flight` | a lane is live on it |
| `landed_unproven` | merged, effect **not** observed on the fleet |
| `done` | merged **and** observed |
| `blocked` | waiting on the typed edge(s) in `blocked_on` |
| `dropped` | closed without landing; `note` says why |

**`landed_unproven` and `done` are different facts**; collapsing them is the failure this repo has paid for repeatedly. The checklist is served as the
Workflow page via `GET /api/bot/work/checklist` from the VM tree (`ict-git-sync` pulls `main` every ~5 min). **Therefore: push, then answer.**

## The roadmap loop (operator, 2026-10-11, binding)

The roadmap (7 goals G1..G7, milestones in `docs/roadmap/milestones.yaml`, rendered into `ROADMAP.md`) informs what is built and **authorizes
nothing**: **derive → prioritise → build → write back.** Every checklist row carries `roadmap: ["<milestone id>"]` from creation, every queue unit
`roadmap: <id>`; no fitting milestone = add one under a goal in the same PR (never reword another lane's entry). A closing row (`done`/`landed_unproven`) sets `writeback: {"roadmap":
"<change | none: reason>", "arch": "<ARCHITECTURE section | none: reason>"}` and the closing lane edits in the same PR. Each daily review runs
`python3 scripts/ops/roadmap_map.py --report` and works what turns (orphans, an `active` milestone with no work, a milestone past
`review_cadence_days`). A component/path/contract change with the map unedited is a defect. A milestone with neither rows nor units must carry
`no_rows_reason`. The weekly pass is part 2 of the Wednesday planning dialogue (the `ROADMAP-PASS-<week>` rows are retired, never re-file one): re-measure
every baseline and active `where` with its own command (an un-re-measured date is marked "not re-measured"), dormant sweep (two passes without work =
close or fresh reason), architecture check, `roadmap_map.py --write-roadmap`; slices (ML-ROADMAP-LOOP, REGIME-PROGRAM) plug in and do not fork. Full pass,
verbatim: [`weekly-planning-protocol.md`](../../../docs/plans/weekly-planning-protocol.md) § "Roadmap weekly pass". Guard `roadmap-map-guard`.

## Weekly planning, reviews and the weekly cycle (operator, 2026-10-13/14/19/28, 2026-11-05, binding)

Full text, moved verbatim: [`docs/plans/weekly-planning-protocol.md`](../../../docs/plans/weekly-planning-protocol.md). **The planning routine's prompt
names that file; read it before running or changing the planning.** What binds, in one place:

- **Order:** after each weekly reset the manager starts ALL weekly reviews first; **planning comes after, Thursday morning**, on their outputs and a
  post-review capacity reading. Planning is a **dialogue, not a report** (never publish a finished plan for sign-off; priorities are never final
  without the operator). Row `WEEKLY-PLANNING`.
- **Every review output gets exactly ONE disposition in planning:** (a) scheduled this week as a row/unit with an owning lane and capacity estimate,
  (b) dated for a named later week with a reason, or (c) killed with a `terminal_reason`. Carry-over from last week comes first; a second carry of
  the same item is a decision for the operator. The (a) set may not exceed the post-review capacity less the standing routines. The backlog is
  reviewed weekly, budgeted in planning, and its drain lane dispatched that morning; **never bulk-drop** (every drop is a row with its reason).
- **Every kill carries a reason AND supporting data** (operator, 2026-11-12, decisions page p7, verbatim: *"In general, all killed items need to have a reason and supporting data attach"*). Applies to a `dropped` row, a `killed` pipeline item (`terminal_reason`), a killed research unit and every backlog-drain kill. Supporting data is something a later session can open (the measurement, result file, PR or row, with its population); a decision quote alone is a reason, not data. Doc rule only, no guard (gates this adds: none).
- **Surge, then throttle** (gates: none): every (a) item is tagged `week_lane: surge | throttle | standing`. Surge = real money (including prop MLs),
  anything moving a strategy or ML model toward live, the week's big ML/strategic milestones; it runs first, as wide as the work allows. Throttle =
  important but not top-line; it runs after the throttle-down (surge rows landed or blocked, or the capacity reading says the rest of the week is
  needed to keep systems running), paced to `--capacity`. `standing` (daily review, weekly reviews, research-ops, live review and desk wakes,
  health checks, incident response) never pauses for the surge, and **one ML-research lane stays reserved through the surge**. Mid-week real-money
  or live-trading arrivals are surge and dispatched at once.
- **Cadence table** (Wed planning, review prep, Thursday walk-through, Saturday health review, Monday weekly audit, Wed programme review, reset
  protocol): `config/reset_protocol.yaml` and `list_triggers` are the source; the moved doc carries the table as agreed 2026-10-14. Unchanged:
  research-ops 4×/day, the daily review ONCE a day at 05:52Z, lane check-ins.

## Assistant managers: one per class of work, at least through every surge (operator, 2026-11-12, binding) — gates this adds or changes: none

Operator, 2026-11-12 ~09:00Z, verbatim: *"use assitant managers if needed (e.g. UI assistant manager, ML assitant manager, that manage all of their
class of tasks and lanes) ... what's the point of keeping all that tasks documented if you're not referncing that information when we're planning
and executing work?"* and *"We can also add instructions for assitant managers in the manager skill - at least during surges, it might be the best
way to make sure we stay on top of everything so that you don't lose track of tasks like this"*. **What went wrong without it (2026-11-12):** after
Thursday planning, 471 queued builds held only 39 `week_lane` tags and 25 lanes; the operator's 11-09 UI spec (`UI-REDESIGN-2026-11`) sat queued
with no lane, and a UI lane briefed from an older row rebuilt the wrong chart layout.

- **When.** From the start of every surge until the throttle-down at least, and any time the manager runs more lanes than it can brief from the
  register. The manager creates them right after planning (or at once when it finds itself behind).
- **Classes** (a row spanning classes goes to the class that owns its money risk first: TRADING > ML > UI > OPS):
  **TRADING** (real money: prop and the phone executor, desk, live-review MECHANICS, active management, DD switch, promotions and the ladder,
  TP doctrine, book mechanics) · **ML** (models and heads, bakeoffs, trainer, frontier, research programmes / queue / SLO, regime, timeframes; it
  keeps the one ML lane running, § "ONE ML LANE ALWAYS RUNS") · **UI** (dashboard SPA, console, UI backend routes, android) · **OPS** (security,
  VM/hosts, CI/Actions, work store and checklist tooling, health and observability, data feeds, alerts plumbing, the backlog drain).
- **Creating one.** `create_session` with `source_url` = this repo, `permission_mode: auto`, tags `["am:<CLASS>", "assistant-manager",
  "manager:<date>"]`. The prompt carries: the class and its governing operator spec rows, the lanes it takes over (ids and state), and the contract below.
- **The contract** (each assistant manager):
  1. **The register is its plan.** It owns every row and lane of its class. Before briefing any lane it reads the row(s) (`work.py --via
     direct get`) and the governing operator spec row for that area, and hands the lane the spec TEXT. Never from memory or an older row.
  2. It takes over its class's running lanes (one message each: "I am now your manager; report to me"). It dispatches new lanes for its rows by
     planned priority, with `source_url` = the repo the work is in (§ "Spawning"; `manager-runbooks.md` § A). It keeps rows current (in_flight +
     lane id; notes; close with evidence) and archives its lanes on DONE; it deletes the message tasks it has read (§ "Scheduled-task and session hygiene"). It never sits idle while its class has runnable rows and no lane.
  3. **Merges:** Tier-1 self-landing is its own. Tier-2/3, and anything touching real money or a prop book, goes to the manager with the PR,
     CI state, tier and decision line. The manager makes the call.
  4. **Operator questions, access needs and operator-only steps go to the manager, never to the operator** (the manager puts them on the
     decisions page).
  5. It reports to the manager on a fixed cadence (TRADING every 2 h, the others every 3 h) and at once on a real-money risk, a lane it cannot
     unblock, a merge for the manager or an operator question.
- **What the manager keeps:** live trade reviews and every alert (operator m12, 2026-11-12: *"The manager needs to get these alerts and
  handle immediately"*), Tier-2/3 merge calls, the decisions page, the operator conversation, and supervising the assistant managers (read
  each report; check one claim per report against the register or live data).
- **Planning feeds them.** Weekly planning (§ "Weekly planning") is not done until every queued, in-flight and blocked row has exactly one
  disposition, and every (a) row has `week_lane`, a slot and `lane` = its class's assistant manager. Planning sends each assistant manager its
  queue as soon as that class is disposed. Rows the planning skipped are a planning defect, filed on `WEEKLY-PLANNING`.
- **Retiring them.** At the throttle-down the manager may fold assistant managers back (record it on `WEEKLY-PLANNING`). Their rows' `lane`
  fields move to whoever takes the class.

## The insights ledger (operator, 2026-11-11, row INSIGHTS-LEDGER) — gates this adds or changes: none

A finding that changed how we trade (a performance/trading insight, a research-infra or pipeline-restructure finding such as a sizing result; **not** a plain infra bug) is logged as a `kind: "insight"` item in the pipeline every time it is made: `claim`, `population`, `provenance` (MEASURED / ESTIMATED / UNVERIFIED), `evidence`, `outcome` (`acted|filed|killed|open`), `links` to the row / unit / PR it became (`acted` needs one), optional `topic`/`roadmap` — validated by `scripts/ops/pipeline.py`, shown by `GET /api/bot/work/ledger`. Not a new register; performance-review sessions file theirs the same way. A dangling link is reported by the route, never a CI gate. **Gaps are alerts the manager handles at once** (operator, 2026-11-12, decisions page m12, verbatim: *"No; report gaps as a number instead"* · *"The manager needs to get these alerts and handle immediately "*): the count of insights with no link and of roadmap milestones with no topic goes to the manager's alert path (alert ledger, row `ALERT-LEDGER-TO-MANAGER`; build row `WORK-GAP-ALERTS`), and a non-zero count is fixed or dispatched the same day. No `insight-link-guard` or `topic-map-guard`.

## Standing authorizations — the ladder is fully automated

**`config/mandates.yaml` is the source for what is granted and armed** (field beats comment); CLAUDE.md § "The daily sync, and standing
authorizations" states the grant. When a mandate fires: a realtime ping, then the evidence record in section 1 of the next brief; a promotion to
real money is never silent. ⚠️ **"If the evidence supports the decision" is the entire safety property**: a committed evidence record, named
harness, stated n, **net of the full cost stack**, clearing a rule registered BEFORE the run; **a claim in a PR body is not a record** (send such a
promotion back). A mandate never authorizes judgement, and an expired mandate stops authorizing. **Standing duty:** move decisions out of the brief
and into mandates; a decision arriving twice in the same shape is raised as "should this become a mandate, and at what bounds?"; a mandate that has
NEVER fired is mis-specified or its condition does not occur, so say which. A session may PROPOSE a mandate; only the operator GRANTS one.

### Before any operator popup: classify the decision (operator directive, 2026-09-29)

Origin: PR #13698 asked whether to promote `slv_trend_1h` (`execution: shadow`, zero real fills, `insufficient_n`). Operator: *"either we have
enough data to decide, or we don't and then getting that data becomes a task which needs to happen so that a decision can be made."* Classify into
exactly one bucket:
1. **Data-settled** — a committed evidence record decisively answers it (under a mandate, or a tier the manager holds with the standing "decide,
   ship, verify, then tell me" authorization, canonical § "Data-backed Tier-2/3 decisions"). **No popup**; act, then report in brief section 1 or 3.
2. **Data-missing** — the evidence does not exist or is below a stated floor (absent Stage-0 record, `n` below floor, cost-fidelity
   `inconclusive`/`insufficient_n`/`no_record`/stale, a `shadow` or never-soaked leg). **No popup either**: file the data task in `PIPELINE.jsonl`
   via `scripts/ops/pipeline.py` with `clears_when` and `origin.rerun`. `scripts/ops/mandate_resolver.py` returns `NEEDS_DATA` and
   `file_needs_data()` files the row; read its docstring first.
3. **Genuinely a preference** — two evidence-supportable courses and a values call with no standing policy. **Only this earns a popup**, in brief
   section 2, no cap on count.
A "preference" that is bucket 1 or 2 in disguise is the #13698 failure. Re-run the classification yourself on any lane's question.

## The daily brief, and the work system

The brief is rendered and **pushed before** the sync: six sections in fixed order (what came due · taken under mandate · decisions for you · what
moved · what is running · spend; CLAUDE.md § "The daily sync"). ⚠️ **The scoreboard opens the brief** (operator audit C6, 2026-11-01; row `PROMPTS-PNL-FIRST`): a short header ABOVE section 0 with net $ and % per book (real money, mirror, paper), each with population, window and read-state (route `SCOREBOARD-PNL-FIRST`; until it lands `/api/bot/performance`), plus one line answering *"would a sceptical quant believe this leg has edge?"* for every leg the brief asks the operator to decide on. A header, not a seventh section and not a gate. Activity counts (lanes run, calls graded, rows closed, hit rate, Brier) never lead the brief and are not reported as a measure of how the system is doing. ⚠️ **The sync is NOT measured in time** (do not report session length as a metric);
⚠️ **no cap on section 2**; ⚠️ **the brief must be short, ranked and true** (a size cap, a soaks slot, what it leaves out stated as a count).

**The work system (operator, 2026-10-04, binding; design `docs/plans/work-system-2026-10-04.md`, row `WORK-SYSTEM`):** the VM computes due work and
pushes it, and **silence is itself an alarm**. `ict-work-digest.timer` (hourly) is THE digest carrier, never a second one; since 2026-11-04
(TELEGRAM-TRIM) only a NEW actionable item (❓ ask, 🧪 soak transition, alarm) goes to Telegram, the rest is recorded. `ict-work-report.timer`
(05:30Z) persists `GET /api/bot/work/report`. Soak state is computed live (`soak_state.py::soak_states()`), never a field a session writes. The
carrier's own death is not self-detected: a stale `generatedAt` or empty `digestLog` is the first incident. Detail: runbooks § C.

### The daily review — ONCE a day, 05:52Z, by a routine (operator, 2026-11-04)

Each run (commands and wording: runbooks § C): (1) fetch `GET /api/bot/work/report?since=<last_review.reviewed_at>` and check it before trusting it
(`present: false`, a `generatedAt` not today's, `erroredSections`, empty `digestLog` over 12 h is the first incident); (2) `blocker_watch.py` and
resolve every finding the same turn (`STALE_BLOCK`, `NOT_RUNNING`/`NEEDS_LANE`, `OPERATOR_WAIT` > 7 d, `UNPROVEN_OVERDUE`); (3) work every due item:
dispatch, close with a `terminal_reason`, or decide (§ "Before any operator popup"); (4) every silence alarm gets a fix lane the same day;
**(4b) the backlog drain is MANDATORY once a day** (operator, 2026-11-01): run `checklist_daily_measure.py`, rank what is due, and dispatch ONE
`BACKLOG-DRAIN-<date>` lane (a review that skips it has failed close-out; inflow above outflow three days running goes to "decisions for you");
**(4c) orphan drain**: `iteration_orphans.py`, report the orphan count per kind as a NUMBER (target 0), and give every `ORPHAN` / overdue iteration
ONE disposition that run (an orphan carried past two reviews is the manager's dispatch failure); (5) record `checklist.py header last_review` (writes the work store, not a file),
push; (6) roadmap hook. **Prep always runs, and the scratch pad feeds it** (operator, 2026-10-21): read the Google Doc "JTA Trader — Ideas inbox"
(also titled "Metis — Ideas inbox"), copy new items verbatim to `docs/claude/work/IDEAS.md`, triage each into a row, a unit or `killed`, and publish
a short work-plan status in-session and on the Workflow page, NOT to Telegram (TELEGRAM-TRIM); `send-ping` is for a decision or red flag only.

### Manager ↔ lane: PUSH plus POLL (operator, 2026-10-04, binding)

1. **PUSH (primary).** A lane wakes the manager when it finishes, is blocked or has something to act on: `create_trigger(persistent_session_id=
   <manager>)` then `fire_trigger`; fallback a PR comment; the manager acts on a wake immediately. **The wake works only from lineage depth ≤ 7 (limit 8)**; `get_session` shows `lineage`.
   The manager must sit at depth ≤ 6, a rotation is created by a shallow session never by the manager, a lane at 8 reports by PR comment.
   **Backstop (operator, 2026-11-08):** lane ML-ENTRY-EQ-STRUCT-LIVE ended a turn on "awaits go-ahead" without the wake and sat ~2.5 h
   unseen until the operator asked for status. The Stop hook `scripts/ops/lane_report_stop_hook.py` now blocks, once, any lane turn that ends
   waiting on a decision with no `fire_trigger` / `send_later` / PR comment that turn, and names the exact wake call.
2. **POLL (backup).** The 3-hourly check-in runs the operating loop; restart or re-dispatch any lane dead, stalled, finished without pinging, or over
   ceiling. **The manager subscribes ONLY to (a) the ops-flags PR and (b) PRs it opens itself** (each subscribed PR injects ~3k tokens per event); the
   lane fixes its own red CI, wakes the manager when green and waiting (for a held PR set one `send_later` ~35 min out), and the check-in lands every green waiting PR. Decisions go out **batched**
   (a 🆕 line in the digest, all open ones in the daily summary, each with options and a recommendation), except a decision that blocks live money or an incident: `send-ping priority=urgent`.

**Required dispatch block.** Every lane `create_session` has `source_url`; **`permission_mode: "auto"`**; `model` explicit; a checklist row (id,
lane, ceiling) written before dispatch. Never merge an unlanded manager branch into yours (#19876). The prompt ends with:

```
You are lane <ROW-ID>, dispatched by Manager Session <date><letter> (<manager session id>);
its authority is the operator's (CLAUDE.md § Every session, step 1). Ceiling: $<N>.
WAKE THE MANAGER when you finish a deliverable, are blocked, or produce something it must act on:
create_trigger(persistent_session_id="<manager session id>", prompt=<what merged/deployed/observed,
what is blocked and on what>) then fire_trigger(<id>). Never set run_once_at (it fires twice).
Read, then delete: delete each message task sent to you once read, and your own fired reminders (close-out check 8).
If your PR waits on the manager (landing: hold), wake it AGAIN once CI on your head is green, with the PR
number and head sha; you stay subscribed to your own PR and fix red CI yourself. If that prompts, comment on your PR instead.
NEVER END A TURN WAITING SILENTLY: if you need a decision, a go-ahead or a merge, wake the manager FIRST (above);
if you are only waiting on a run, schedule your own wake with send_later. The repo Stop hook
(scripts/ops/lane_report_stop_hook.py) blocks a lane turn that ends waiting without either.
Then continue, or run close-out. Never stop to wait for direction.
Before EVERY push run `python3 scripts/ci/prepush.py` (guards on your diff + affected tests, locally); never push to a PR while its
CI runs unless fixing red; batch your commits into one push.
```

**Reading scope for the lane** (operator 2026-10-27, `CONTEXT-DIET`): a lane reads only what CLAUDE.md § "Every session" step 1 names from the
canonical doc. **Put in the prompt any other canonical section its task needs** (e.g. "Generation Discipline Rule 3" for a build lane).

**The soak contract.** Stated once: [`OPERATING-PLAN` § 2 "The soak is MECHANICAL"](../../../docs/plans/OPERATING-PLAN-2026-09-21.md); never restate
it in a dispatch, row note or contract. A Stage-1 placement needs a contract in `docs/claude/work/SOAKS.json` (`soak_state.py --backfill`). Per state:
`passed` → promotion candidate, run `MD-PROMOTE-S1-S2` (a `mechanics_proven` leg needs no contract) · `mechanical_fail` → dispatch the fix ·
`awaiting_first_trade` / `in_progress` → nothing, no deadline · `unknown` → we could not look; find out why. A grade's `kill` calls are applied
under `MD-DEMOTE-S1-OFF` / `MD-KILL-QUESTION` or filed with a reason, never just read.

## Weekly reset protocol (operator, 2026-11-02, binding) — gates this adds or changes: none

**One source:** [`config/reset_protocol.yaml`](../../../config/reset_protocol.yaml) (jobs with cadence/order/offset/model/ceiling/skill/dedupe tag,
and one-shot `after_reset` items); machinery `scripts/ops/reset_protocol.py` (`--plan <reset-ts>`, `--receipt`, `--sweep`, `--self-test`); receipts
`comms/ops/reset_receipts.jsonl` (append-only, committed by the manager to `main`). Primary trigger: a routine Wed **18:05Z**; backup:
`.github/workflows/reset-protocol-backup.yml` (18:15Z wake comment on the ops-flags PR if no receipt; 19:00Z red flag). Steps, in order (full text,
trigger ids and the pipeline snippet: runbooks § D): **0 Claim** (`--receipt <ts> --write started`, push at once; **exit 4 = another trigger owns
this reset: stop in one line**) · **1** restore the check-in cadence `17 */3 * * *` · **2 Stuck-work sweep** (`--sweep` plus `list_sessions`;
every blocked/failed/paused lane, no-lane row, green-waiting or red PR gets exactly ONE disposition with a reason: resumed, re-dispatched, or
closed) · **3 Dispatch the due jobs** from `--plan` at their offsets (dedupe via `list_sessions`; `create_session` with the config model and ceiling,
tags `lane:<NAME>`, `manager:<id>`, `metis-lane`; the lane brief is the disabled legacy routine's stored prompt via `get_trigger`) · **4** start the
`after_reset` items · **5 Receipt and ONE Telegram line**. **Close-up on low usage:** at ~90% of the weekly bar, or on any limit hit, every running
lane writes a resume note on its row and stops (no new work); the manager files ONE PIPELINE item `due_when.event: weekly_reset` listing all paused
work, closed only when every listed lane has a disposition.

## Manager handover (rotation) — operator, 2026-10-13

The manager rotates **at its own discretion**; what is not discretionary is the proof: **the old manager stays responsible until V1–V5 have all
passed, with evidence in the handoff doc.** **When:** context past **~650k tokens** (checked at every loop run and the first turn after every
compaction via `get_session` → `external_metadata.context_usage.used_tokens`), a natural boundary, or degraded recall. Never mid-incident or with a
merge/deploy half-done. Steps (full text: runbooks § E): **0 ARCHIVE FIRST** (full sweep; the handoff doc lists each lane left open with a reason) ·
**1 PREPARE** `docs/claude/work/handoffs/<YYYY-MM-DD>-<old-short>-to-new.md` (do not commit it from the manager session; a small Haiku lane
self-lands it) · **2 CREATE** by a SHALLOW session, never the outgoing manager (Opus explicit, same environment and `source_url`, `permission_mode:
"auto"`, tags `["manager","predecessor:<old id>"]`; run `routine_prompt_check.py` first) · **3 REWIRE** every trigger (recreate with the new
`persistent_session_id`, disable the old; `update_trigger` cannot retarget), prompts naming the old id, re-subscribe incl. ops-flags, `last_review.by`
· **4 VALIDATE** (below) · **5 STAND DOWN** only after V1–V5, last message links `https://claude.ai/code/<new id>` plus the new title; the new manager
archives the old one and deletes the disabled triggers. If any check fails the old manager stays responsible.

| # | Check | Pass means |
|---|---|---|
| **V1** | Short diff | The new manager lists **only what differs** from the handoff doc via targeted reads; the old manager checks it; record the new manager's `used_tokens` (target < ~80k for the whole handover). |
| **V2** | Trigger audit | New manager subscribed to ops-flags (a call returns subscribed, not "already watched"); **zero enabled** triggers target the old id; every recurring routine exists and is enabled on the new one incl. "Manager lane check-in". |
| **V3** | Id sweep | Ops-flags held by the new session only; no enabled trigger prompt, charter or lane brief still names the old id (the grep finds a known positive first, RULE ONE). |
| **V4** | Wake round-trips | old → new test trigger answered; assistant → new escalation answered; one live lane told the new id acknowledges. |
| **V5** | Operator notified in one message | New link, what moved, what did **not** and why. |

## The ladder, and closing the session

The ladder is CLAUDE.md § "The promotion ladder" (Stage 0 backtest net of the FULL cost stack → Gate 1 → Stage 1 mechanical soak, skipped when
`mechanics_proven` → Gate 2 → Stage 2 live + mirror; edge is decided offline, a book only checks mechanics and cost).

**Closing the session: publish the record, then ping** (operator, 2026-09-22: *"make the summary and then post it on the site so that I can refer to
it without having to go back into the chat. And ping me also when everything is fully closed out."*). A chat reply is not the record. **The gate —
publish and ping only when ALL are true:** (1) every PR the session opened or drove is merged, or HELD with the blocker on the PR and in
`PIPELINE.jsonl`; (2) deployed means deployed: land, wait for `ict-git-sync`, restart the unit, OBSERVE the running process; (3) every row has a
true state; (4) every finding is fixed, filed (pipeline or checklist) or flagged; (5) stale docs corrected; (6) `close-out` run, all eight checks;
(7) every finished lane archived, none while it owns an open PR. **Then, in order:** PUSH FIRST; PUBLISH THE SUMMARY AS A PAGE (Artifact tool) with
what each lane was dispatched to do and what became of it, what MERGED (shas), DEPLOYED and OBSERVED (never collapsed), verified vs waiting with the
specific observation each needs, the operator's decisions in their words, **the session's own errors** plainly, next steps in order with why the
first is first, and a receipt (sessions run, spend per lane vs ceiling, total, archived); **THEN PING** with the link and one line of state. If the
gate cannot be met, publish anyway with the unmet conditions named at the top.
