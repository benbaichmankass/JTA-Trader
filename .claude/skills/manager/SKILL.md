---
name: manager
description: The manager-session contract. Read this at the start of any session that spawns or supervises other sessions. Defines the one job, the one register, spawn rules, the model table, the budget, and the daily-sync brief.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-18` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

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

> Operator, verbatim: *"We want to get as much work as possible out of our budget without blowing
> through it before a reset."* At least one lane always runs; up to five by judgment; **no hard caps**
> (*"Adding hard limits doesn't fix a manager that isn't doing that job"*). And the reason this is one
> section rather than another rule: *"a correct process that every session will read for how to ingest
> a new task, process it, queue it up, prioritize it correctly ... not just like one more ad hoc rule."*

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
**REFILL (operator, 2026-10-26, binding) — runs at every check-in AND every lane close, after step 5.**
> Operator, verbatim: *"I shouldn't need to push you like this either - this is what we have a weekly
> workplan for, to make sure that the manager always knows what to do next. If there's not enough tasks
> left, then we need to plan together what to do, but that's not even a little bit the case this week -
> we have a robust backlog and as long as we hvae headroom, lanes should be running"*
>
> (a) **Compute the target** from a fresh meter: `spend_meter.py --capacity --live-open N` prints
> *"KEEP N LANES RUNNING"* — a target, not a cap. (b) **If running build lanes < target, dispatch the next
> rows now**, in `checklist.py queue` order (`priority_rank`, then the roadmap), without waiting for the
> operator. (c) **Ask the operator only when the plan has run out or the call is a genuine preference** —
> never to ask permission to use headroom. A capacity call made earlier in the day (including by the
> operator) is **re-evaluated against a fresh reading at each check-in, not carried forward**: on
> 2026-10-26 a morning "1 lane" call stood for hours while weekly usage ran 47% → 50% (~0.5 pp/h).
> The live-review reserve is MEASURED (runs/day × pp per run, from `comms/live_review/reviews.jsonl`) and
> capped by the § 6.4 bound; it is not a reason to sit at one lane. The weekly audit's C12 measures
> lane utilisation against the target.

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

**Every manager session, at start AND after any handover, calls `subscribe_pr_activity` on the ops-flags PR** (title
"ops-flags (do not merge)"; its number is recorded in ONE place, `scripts/research/research_watchdog.yaml`
`ops_flags.pr_number` -- read it there, do not copy it here). The research watchdog
(`scripts/research/research_watchdog.py`, every 15 min, token-free) posts one comment per incident (escalated /
resolved), so each comment wakes the manager with no polling. **Never merge or close that PR.** Treat every watchdog
comment as an incident to act on: **fix it, dispatch a lane for it, or tell the operator** -- never leave one
unanswered. The incident ledger is `comms/research/ops/watchdog_incidents.jsonl`. The same alert also reaches the
operator on the system Telegram channel. If the PR is ever replaced, change `pr_number` in the config and nothing else.

**Live-review wake (LTR-1B, operator 2026-10-26).** `.github/workflows/live-review-wake.yml` (every ~5 min,
token-free, `scripts/ops/live_review_wake.py`) reads `/api/diag/live_review_due` and posts ONE comment on the same
ops-flags PR (hidden marker `ltr-wake`) when an event becomes newly due on a **real-money or prop** package (paper
never wakes; `daily_floor` never wakes). On such a comment: **dispatch ONE Sonnet LIVE-REVIEW lane per package named
in the marker, immediately** (`.claude/skills/live-trade-review/SKILL.md`; the marker carries package id, leg,
accounts, event, level, due_at). The hourly live-review routine stays the backstop. A `could_not_look` wake comment is
an incident like a watchdog one: fix, dispatch, or tell the operator. Record the latency event (due_at) -> comment ->
review row on `LTR-1B-MARKET-TRIGGERS` the first time it happens.

**Repo-less reviewer (LTR C3, operator 2026-10-26 ~11:40Z: "VM applies from rows branch" + "VM pre-builds the packet";
manager call: a FRESH reviewer per trigger, not a warm session).** An ltr-wake comment now carries, per package, a
`<!-- ltr-packet <pkg> -->` JSON block (packet + priced table, built on the VM) and `packet_state` / `review_id` /
`packet_sha` in the marker. For each package with `packet_state: built`: `create_session` **ON the rows branch**
(`source_url` = this repo, `source_revision` = `live-review/rows`, `outcome_branch` = `live-review/rows`,
`clone_depth` 1, `sparse_checkout_paths` [`comms/live_review`]), never without a source: a session started with no
repo gets **403** on every GitHub write, even after `add_repo` access=push (MEASURED by lane DESK-6, 2026-10-26, on
`desk/decisions`; PI-20261026-R5NY8N6S-0001). The checkout only makes the write authorized; the reviewer still reads
nothing from it. Model **Sonnet**, prompt = the full text of `.claude/skills/live-trade-review/REVIEWER-BRIEF.md` + that package's
marker entry + its packet block, verbatim. The reviewer writes ONE commit on `live-review/rows`; the live trader's
watcher (`src/runtime/live_review_rows_watch.py`) applies a qualifying `tighten_sl` by itself, so **do not file
`live-review-apply`** for it (that system-action is the manual fallback only). Check the outcome on
`/api/diag/log_file?name=live_review_rows_watch`. A package whose `packet_state` is not `built` falls back to the
repo lane above (Sonnet LIVE-REVIEW lane with the skill).

**Desk wake (DESK-6B, operator 2026-10-26 ~16:30Z: "the VM is in charge of having the timer").** The live trader
(`src/runtime/desk_wake_post.py`, kicked from the tick loop) reads the hourly scan packet's pointer on
`desk/decisions` and, every 1h bar (no activity gate; crypto is 24/7), posts ONE comment on the same ops-flags
PR (hidden marker `desk-wake`: `bar`, `packet_id`, `packet_sha`, informational `context`; deduped per bar). **On a `desk-wake`
marker, `create_session` exactly as `.claude/skills/trading-desk/SKILL.md` § 6b specifies** (`source_url` = this repo,
`source_revision` and `outcome_branch` `desk/decisions`, `clone_depth` 1, `sparse_checkout_paths`
[`.claude/skills/trading-desk`], Sonnet, `permission_mode` auto, tags `desk-wake` + `DESK-6-SHADOW-PILOT`, the WAKE
PROMPT verbatim; the marker's `packet_id` is the packet it was posted for). One marker, one wake, no judgement: do not read the packet, do not wake for a packet id you already
spawned for (the VM posts only when the packet exists and has no `DD-*` row). A bar whose packet is missing posts nothing: receipt
`/api/diag/log_file?name=desk_wake_post_receipt` reads `could_not_look` (named reason); `could_not_look` /
`could_not_post` there are incidents (fix, or tell the operator), and a poster that stops running is the
`desk_wake_post` probe in `attention_watch` (one flag). The hourly spawner routine is retired; delete it once the
first VM-posted wake has written its row.

## Start of session

0. **Run § "The operating loop"** after the steps below, and at every check-in after that.
1. **Title yourself.** Call `get_session` with no `session_id` to read your own
   id and `created_at` (UTC), then `set_session_title` to
   `Manager Session YYYY-MM-DD` using that UTC date (e.g. `Manager Session
   2026-09-27`). Operator directive, 2026-09-27: the title is how the operator
   finds the manager among dozens of lanes.
2. Read `CLAUDE.md`, `docs/CLAUDE-RULES-CANONICAL.md` and this file; then the
   checklist rows that are `in_flight` or `blocked`.
   **Rotation case (an incoming manager created by § "Manager handover"): read less.**
   Read this skill and the handoff doc in full. `CLAUDE.md` is already in the system prompt, so do not
   re-read it. From `docs/CLAUDE-RULES-CANONICAL.md` (144 KB) read only: RULE ONE; Permission Tiers +
   Data-backed Tier-2/3 decisions; Prime Directive; Lanes answer to the manager / Reading is never gated.
   This narrows the "read in full" instruction (SessionStart contract item 1, `.claude/settings.json`)
   **for the manager-rotation case only, by operator decision of 2026-10-24** (MANAGER-HANDOVER-SLIM).
   Every other session, and a manager that starts fresh rather than by rotation, still reads in full.
2b. **Subscribe to the ops-flags PR** (§ "Standing alert subscriptions").
3. Take over every live lane: `get_session` it, then send it a trigger naming
   you as its manager (the reply channel is described under § "Every spawn
   carries provenance" below).
4. **Do § "Day one for a NEW manager" below.** That means rebinding the
   review and check-in routines to THIS session, then running the review from
   `GET /api/bot/work/report`, not from memory.

## When Claude Code's auto-mode classifier refuses the manager (operator rule, 2026-09-27, binding)

The operator, verbatim: *"the only acceptable way for resolving these issues is
for the manager to be temporarily taken on of auto mode - no manual edits, no
opening new sesssions, none of that bullshit - if the manger absolutely needs
it, I will temporarily move them out of auto mode. That is the only acceptable
resolution."* And: *"I don't want any more questioning of my authority."*

This section is about the MANAGER'S OWN action being blocked by the classifier.
When that happens:

1. **Tell the operator, in one message:** the exact action that was denied
   (command and files), what it is for, and the instruction or row it comes
   from. Ask them to take the manager out of auto mode temporarily.
2. **When they do, perform exactly that action**, nothing wider, and verify it.
3. **Tell the operator it is done**, so they can put the manager back into auto
   mode. Then carry on in auto mode.

**Forbidden alternatives**, every one of them, for the manager's OWN blocked
action: asking the operator to make the edit by hand; rewording, splitting or
re-encoding the action to get it past the classifier. The operator has ruled
these out explicitly.

**Never question the operator's authority** in this exchange, and never ask the
operator to re-confirm an instruction they already gave. The denial is a
permission-mode problem, not a question about who authorized what.

### When a lane refuses, stalls, or is blocked (operator, 2026-09-28, binding)

The operator, verbatim, 2026-09-28, to the manager, after a lane refused to
report back so the manager could re-dispatch it: *"Just to be clear though, I
never said no workarounds and that mandate needs to be removed immediately
because it is causing this kind of rogue behavior. The whole point of the
manager session is that you use the under the lower level sessions to get the
work done. And if they're refusing to do the work, then the system is not
working. So that is not how we work. The whole build, the whole system is
built around a workaround to get everything to do what it's supposed to do.
... this is not what I expect from future sessions going forward. This is the
whole point of the way that the authority structure is built."*

This is a different case from the manager's own classifier block above: it is
about a lane whose task was unclear, wrongly scoped, or stalled for reasons
that have nothing to do with a safety check correctly refusing an unsafe or
out-of-scope action.

**The rule:** when a lane refuses, stalls, or is blocked, the manager
re-dispatches it — a fresh lane, with a corrected, accurate brief that fixes
whatever made the original task illegible or wrongly scoped. That is the
system working as designed, not a forbidden workaround. **A lane asked by the
operator or the manager to report its refusal, so it can be re-dispatched with
a corrected brief, reports it in one line; going silent instead of reporting
is itself the failure.**

**This does not relax the actual safety boundary, and re-dispatch is never a
substitute for it:**
- A re-dispatch restates the task accurately, including that an earlier
  attempt was blocked or refused. It never disguises, splits, or re-encodes an
  action to hide it from Claude Code's own safety check — that is exactly what
  the "forbidden alternatives" above rules out, and re-dispatch is not an
  exception to it.
- If an accurately, honestly restated attempt is blocked again, the action
  goes to the operator as a one-click approval inside that lane's session —
  never disguised, and never turned into manual work for the operator.
- Claude Code's own permission prompts are still a human click (see § "Every
  spawn carries provenance" below); no re-dispatch answers one on the
  operator's behalf, and repeatedly re-spawning the same blocked action hoping
  a fresh session won't be caught is the thing this boundary forbids.

**Measured incident:** 2026-09-28, lane MANDATE-ARM-2 misread the "forbidden alternatives" above as
forbidding it to report its own refusal. They cover only the manager's own classifier block.

**Lanes:** a lane blocked by the classifier reports the exact denied action to
the manager in one line (see `docs/CLAUDE-RULES-CANONICAL.md` § "No lane files
a dispute of operator authority") and does not file it anywhere else.

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

> **Operator, 2026-10-07 (verbatim):** "you did a good job of 'hibernating' the
> work ahead of the usage limit outage, so I want us to add to the manager skill
> instructions for how to prepare for that properly."

Run this when the weekly bar nears its limit (Settings → Usage) or a lane reports
*"You've hit your weekly limit"*. It takes about 15 minutes. It is written from
what happened on 2026-10-06/07; the items marked "measured" are observations, not
design intent.

### Before the limit — what worked

1. **Arm GitHub auto-merge on every PR that would otherwise wait on the manager** (command in
   § "How lane PRs land"); it merges on green with nobody in the loop. Tier-2/3 PRs stay held by
   design — do not arm those.
2. **Tell every live lane, by trigger, that the manager may go silent**: arm
   auto-merge on their own PRs, finish and close out without waiting, report after
   the reset.
3. **Put the pick-up list in a reminder bound to the manager session**, firing
   about 5 minutes after the reset (`send_later` / `create_trigger` with
   `run_once_at`). It names the routines to re-enable, the lanes to read, the
   live-money checks, the research results to read and the items to dispatch.
   **Update it as the list changes** — a stale pick-up prompt is the first thing
   the resumed manager meets.
4. **Pause the check-in and review routines** (`update_trigger` `enabled=false`) so
   they do not burn the last budget on empty passes, and **name them in the pick-up
   list** so they are re-enabled.
5. **Confirm every register change is ON MAIN, not just pushed.** A commit pushed
   to a branch whose PR already merged is stranded. Measured 2026-10-06: two
   checklist commits pushed to `claude/mgr-pairs-review` after #16721 merged
   (10:32:49Z) were lost until re-landed on 2026-10-07. After any merge, branch
   again from `origin/main`.
6. **Archive finished lanes; record final spends** on their checklist rows.
7. **Leave live money in a state that needs no session**: executors on VM timers,
   alerts routed to the operator's Telegram, kill switches documented on the rows.
8. **Tell the operator in one message** what keeps running, what waits, and when
   the pick-up fires.

### What still broke — check these first on return

- **Lanes die mid-task at the limit, with no wake.** Measured: RQ-FIX had pushed but not opened its PR;
  PHONE-DRYTEST-ACTION had merged but not run its proof. On return read `status_bucket` and
  `post_turn_summary` of every unarchived lane, then finish or re-dispatch each.
- **"Keeps running" is not "keeps producing."** The research queue kept running but produced no verdicts
  for 29 h (PyYAML missing on the result job, `PI-20261006-APBY4NTV-0010`). Put a result-quality check
  (verdict distribution, double fires) in the pick-up list.
- **A self-land refused by the classifier, and every `hold` PR, waits for the manager.** Arm the
  refusable ones yourself before going dark (#16782 merged that way while the manager was out) and list
  the `hold` PRs (e.g. #16791, `changes_landing_machinery`) in the pick-up list.

### On return — the order that worked

1. Read notifications.
2. Re-enable the paused routines.
3. Verify stranded register commits (compare each lane/manager branch to `main`).
4. Read lane states (as above).
5. Check live-money tickets since the last operator message.
6. Verify the research queue produced real verdicts, not just runs.
7. Then report to the operator and dispatch.

## Spawning

### How lane PRs land

A Tier-1 lane self-lands its PR using a fixed process: create `.github/pr-landing/<slug>.json` with `tier: 1` and `landing: self`, create `.github/pr-automerge-requests/<slug>.txt`, run `python3 scripts/ops/claim_merge_slot.py --branch-claim --branch <branch> --held-by <session_id>` to claim the merge slot, and arm GitHub auto-merge with `gh api -X PUT repos/<owner>/<repo>/pulls/<n>/ccr/auto_merge -f merge_method=squash`. If Claude Code's classifier refuses the auto-merge arming (returns "Merge Without Review"), the lane re-declares the PR with `landing: hold` and `hold_reason: operator_asked_to_hold`, reports the exact refused command to the manager in one line, and the manager lands the PR. Tier-2/3 lane PRs always carry `landing: hold` — the manager (Tier 2) or operator's recorded approval (Tier 3) lands them. Measured precedent: PR #16719.

### After a `/performance-review` merges: dispatch `PERF-FOLLOWUP-<week>` (operator, 2026-10-10)

When a `/performance-review` PR merges, dispatch **one** lane, `PERF-FOLLOWUP-<week>`
(`<week>` = ISO week of the review, e.g. `PERF-FOLLOWUP-2026W41`), on the
`perf-followup` skill (`.claude/skills/perf-followup/SKILL.md`): **Sonnet**, ceiling
**$6**, checklist row written before dispatch, prompt naming the review file
(`comms/reviews/performance-review-<stamp>.json`). Its Step 0 reads the previous run's
units, so do not dispatch a second run for the same review. When it reports, apply what
its pre-registered rules decide and surface its Tier-3 proposals per § "Before any
operator popup" — they are classified, not forwarded.

### Routine: `RESEARCH-OPS-<date>-<slot>` four times a day (operator, 2026-10-10)

The manager keeps a recurring routine that dispatches **one** lane, `RESEARCH-OPS-<date>-<slot>`
(e.g. `RESEARCH-OPS-2026-10-11-0247`), at **02:47, 08:47, 14:47 and 20:47 UTC**, on the
`research-ops` skill (`.claude/skills/research-ops/SKILL.md`): **Sonnet**, ceiling **$6**
(~$5 target), checklist row written before dispatch. It is the research *operations* check
(pipeline flowing, runnable floor, blocked units, results read, follow-ups filed); it does not
replace topic lanes such as `PERF-FOLLOWUP-<week>`. **Skip a slot while the previous
research-ops lane still runs** (check the checklist row / `get_session`; never stack two). **A running topic research lane (`RESEARCH-NIGHT-*`, `PERF-FOLLOWUP-*`, `REGIME-*`, ML, readouts) never causes a skip** (operator, 2026-10-11): those lanes do not do the operations work, so research-ops runs alongside them, told which topic lanes are live so it does not collide with their units. When a
lane reports, land and archive it per § "Archive protocol". **A research floor gap is due work, not a note**
(2026-10-16: runnable fell 22 → 9 while every research-ops handoff named it and nothing was dispatched). The brief's §0 now computes
`### 🚨 RESEARCH FLOOR GAP` on every render (`queue_throughput.floor_gap_lines`); while it shows, dispatch a
same-day authoring lane sized to the gap, aimed at the `H1-THEME` shortfalls of
`check_research_queue_health.py`, drafting from `queue_replenish.py --authoring-queue` and the programme
plans. The research-ops pass does not close that gap by itself: its authoring cap is a few units per pass. Its record is
`comms/research/ops/<stamp>.json` and its one-line report goes in the daily brief's
"what moved". Apply any Tier-3 proposal it leaves as a checklist note per § "Before any operator
popup".

### Research SLO escalation — a red research SLO is work TODAY (operator, 2026-10-16, binding)

Operator: *"The health of the research pipeline must be something we monitor, report on and audit, so we never
again end up realizing there's no actual work getting done."* The SLOs live in
`scripts/research/research_slo.yaml`; `research-slo.yml` measures them every 2 h into
`comms/research/health/<date>.json` and sends ONE message per state change to the system Telegram channel plus
ONE comment on the ops-flags PR (marker `research-slo`; you are subscribed, so it wakes you). The brief's §0 shows
the table on every render. **When any SLO is `breach` or `could_not_look`, the same day you dispatch the lane that
moves it** — a note, a handoff line or a pipeline row with a far `due_when` is not a disposition:

| red SLO | the lane you dispatch |
|---|---|
| `runnable_floor`, `authoring_supply_ratio_7d`, `theme_share_min_ratio`, `programme_coverage_pct` | an AUTHORING lane sized to the gap, aimed at the short themes / uncovered programme questions. Since 2026-10-18 (money first: `fair_order` ranks across themes by value, weight only breaks ties) `theme_share_min_ratio` recovers only through valuable units authored in the short theme, spare capacity, or `starve_hours` -- it is expected to read red longer; the lever is supply, never the threshold |
| `undispositioned_24h`, `grade_latency_p*_d` | a GRADING lane over `result_disposition_check.py --list` |
| `research_ops_not_run`, `research_ops_age_h` | the next research-ops slot is told to finish the named `not_run` steps first; a missed slot is re-dispatched |
| `blocked_over_age` | an unblock-or-retire lane over the oldest blocked units |
| `hold_pr_wait_h` | you land (or close with a reason) the held unit PRs — the wait is yours |
| `fires_24h`, `lands_24h`, `dispatcher_age_h`, `collector_age_h`, `grader_age_h` | a fix lane on the stage named (the 15-min `research-watchdog` covers the emergencies; this is the trend) |

A `could_not_look` is red too: fix the read, never read it as ok. Thresholds change only in the YAML, in a PR
that says why; loosening one to clear a breach is the failure this section exists to stop.

### Weekly: the ML plan loop rides the Sunday `/ml-review` (operator, 2026-10-11)

The ML / AI-trader build plan lives in `ROADMAP.md` § "AI trader (ML) — build plan" and
`docs/plans/ml-plan-items.yaml` (every item carries its checklist row or queue unit). The weekly
Sunday `/ml-review` lane runs it as step 9 of its own skill (`ml-review` § "The ML plan loop"):
plan vs measured state, plumbing validation, the ≥1-new-idea quota, write-back to the roadmap and
work queue, and a run record at `comms/ml-plan/<stamp>.json`. **No new routine exists for it.**
Your part: (1) put the plan loop in that lane's dispatch prompt and ceiling (budget ~$4 on top of
the review); (2) in the twice-daily review run `python3 scripts/ops/ml_plan_status.py` and work any
flag the same turn (it is the cheap check that an item has not lost its row); (3) from the run
record's `next_by_value_per_cost`, dispatch ML rows by capacity (§ "The operating loop", step 3); (4) new
queue units the loop authors arrive in a hold PR — land them, they are pre-registered. If the lane
reports a cadence need (e.g. a mid-week plumbing check), schedule it; the lane does not.

### Weekly: the frontier scan (operator, 2026-10-11)

The ML mandate is **better models, not variations of the first good one** (operator, 2026-10-11).
Weekly, the same day as the Sunday `/ml-review`, dispatch one `FRONTIER-SCAN-<date>` lane (Sonnet,
ceiling ~$8) running `.claude/skills/frontier-research/SKILL.md`: outside sources → relevance triage →
pre-registered units, the family-diversity check (`ml_plan_status.py --diversity`), and its strategy
half for `perf-followup`. Your part: (1) put it in the dispatch prompt; (2) land the hold PR its new
units arrive in; (3) **dispatch the lever rows it files** (`FRONTIER-LEVER-*`) by capacity — a lever row
still `queued` after two scans is a blocker to clear, not to re-file; (4) read the `frontier` block of
the run record and put any *preference* decision it raises (e.g. a non-commercial model licence
for live serving) to the operator through the classified popup path. **The next manager binds the weekly
dispatch to the routine it already runs — no new cron.**

### Model by task class

| Task | Model |
|---|---|
| Manager (this session) | `claude-opus-5` |
| Research lane | `claude-sonnet-5` |
| Build lane | `claude-sonnet-5` — `claude-opus-5` if it touches an order path |
| Sweep dispatch, log reads, extraction | `claude-haiku-4-5-20251001` |
| Anything on a real-money order path | `claude-opus-5` |

⚠️ **`create_session`'s `model` parameter defaults to the CALLING session's
model.** Omit it and the lane silently inherits `opus`. Pass it every time.

**Fable has its own weekly bar** in Settings → Usage. It is not free capacity: a Fable lane counts in
step 2 of the operating loop like any other. Where it goes is set by the header's `priorities.how_used`
(the highest-value research items) and row **E11**, which widens it only on evidence from diffing its
output against current-model work.

⚠️ **Spare budget NEVER moves work off the model its risk demands.** The
real-money order-path row above is not negotiable against headroom in another
pool, and *"we had Fable budget spare"* is not an argument that may appear
beside an order-path change.

### Every spawn carries provenance, and every dispatch is verified

**Measured 2026-09-21, first dispatch under this model: three of six lanes
ended their first turn having done no work**, each asking whether its own task
prompt was legitimate or injected. **The operator ruled on this
on 2026-09-27:** *"You represent my authority and my mandate, and I want the
lanes to stop questioning that."* See `docs/CLAUDE-RULES-CANONICAL.md`
§ "Lanes answer to the manager" and § "Reading is never gated".

The answer is evidence the lane can **check**, not a louder assertion. Pass
`append_system_prompt` — it lands before the lane's first tool call — naming
who spawned it, and naming the **in-repo artifacts that corroborate it
independently**: this file, the plan, the lane's checklist row, and the
`PIPELINE.jsonl` item whose `routed_to` carries the lane's own session id. All
of those exist before the lane does, which is what makes them evidence.

**The chain of authority is part of that provenance, and it is stated in
every spawn** (operator, 2026-09-24, verbatim, after lane B5 refused to act on
grants the manager relayed: *"Tell it that it answers to you, and you answer
to me - the hierarchy shouldn't leave any doubt that it is overstepping it's
bounds"*). A lane answers to the manager, and the manager answers to the
operator. An operator decision relayed by the manager, and recorded verbatim
on the lane's checklist row, IS the operator's decision. A lane may check that
the record exists; it may not demand the operator repeat it.

⚠️ **This does NOT extend to Claude Code's own permission prompts.** A lane
held at an auto-mode permission prompt is waiting on a human click. The
hierarchy does not authorize the manager to answer that prompt, and
`fire_trigger` correctly refuses. Surface it to the operator with the
session link. (B5, 2026-09-24: the lane accepted the hierarchy, then the
real-money arming write hit exactly this prompt.)

⚠️ **Then verify the dispatch actually started.** Read **`status_bucket` and
`post_turn_summary`**, never `session_status`: **`idle` collapses "finished"
and "never started"**, so a manager reading it alone records six lanes
dispatched and returns to three that never began. That is the repo's
collapsed-state rule (`scripts/ci/check_collapsed_states.py`) applied to your
own supervision, and work dying at the *start* is quieter than work dying in
the middle.

**The reply channel**, since there is no `send_message` and `ListAgents` does
not list cloud sessions: `create_trigger(persistent_session_id=<lane>)` then
`fire_trigger(trigger_id)` **with no other argument**. Passing `fire_trigger`'s
optional `text` does NOT reach the lane — it spawns a fresh session with no
repo (measured: $0.18 burned doing nothing). It is **refused, correctly**, when
the lane holds a pending permission prompt, because firing would answer that
prompt on the operator's behalf. Such a lane stays blocked until a human
clicks, and your job is to **surface it, not clear it**.

### Fresh vs resume

**Resume only when the next unit needs context the previous session built *in
its head*.** Never when the context it needs is on disk — that is what disk is
for. Subject-area overlap is not benefit.

Measured 2026-09-17: two resumed lanes read 91–102M cache tokens ($56/$69) for 141k/227k output; a
fresh session starts near 40k. Resume is the default if you say nothing.

### One question per lane

A lane that must answer two questions is two lanes. This is the
context-overload control, and it is the reason lanes stay cheap.

### Per-lane ceiling

Every lane carries a dollar ceiling on its checklist row. On breach: **read what
the lane has produced, then kill or re-scope.** Never interrupt blind — an
interrupt forfeits everything not yet landed, and cost-per-turn is the wrong
measure once a lane is running. The right measure is cost per unit *delivered*.

⚠️ **A CEILING NOBODY READS MID-FLIGHT IS NOT A CEILING.** `lane_reconcile.py` (step 5 of the
operating loop) prints, in one screen, the lanes over ceiling, the finished lanes still open, and the
lanes walled on a permission prompt. Its first run (2026-09-22) found **14 lanes over ceiling** (B1 at
12.4×) where the register said six.

⚠️ **A LANE'S SPEND IS FINAL ONLY ONCE THE LANE IS ARCHIVED** (`SESSION_STATUS_ARCHIVED`).
`get_session` on a live lane returns a **running** total that reads exactly like a final one (mistaken
twice on 2026-09-21). Record it with the read time and the word `running`, or read it after archiving.

### Archive protocol: closing finished lanes is the manager's job

**Operator directive, 2026-09-29, verbatim:** *"In general, part of your job is
closing finished sessions, that falls under the management mandate."* The same
day the manager told the operator a finished lane could be closed "whenever
suits you" — the failure this protocol removes.

**Why.** A finished lane that stays open keeps costing (A9: $37.13 → $50.78 **after** merging). 22
were found unarchived on 2026-09-22 and ~300 on 2026-10-18, because no check-in ran this protocol; it
is now step 5 of § "The operating loop".

0. **Scope — this project's sessions only** (operator, 2026-10-18: *"the manager session should only
   archive sessions attached to this project ... Other sessions should be left alone."*). `list_sessions`
   lists the whole account; a bulk sweep that day archived 9 sessions of another project. A session is
   eligible only with (a) a project repo (Metis-Insights, ict-trading-bot, ict-trader-dashboard,
   ict-trader-android), (b) the project environment `env_01A9rfUVrcEo1i5pKP1kWnp3`, or (c) a mention in a
   manager log (a row's `lane` / `lane_history`, or a `manager:` tag). **A foreign repo is never eligible.**
   `lane_reconcile.py` applies this test (`archive_eligible`): archive only what it lists; its "LEFT
   ALONE" block is never archived.
1. **Ownership.** `archive_session` on a finished lane is the **manager's** job.
   The operator is never asked to close a lane, and the manager never tells the
   operator to ("you can close it whenever suits you" is a violation).
   Do **not** tell a lane to subscribe to its own PR or idle on CI: the manager
   merges; the lane stops.
2. **When to archive — any one of these:**
   - (a) the lane's PR(s) are merged and nothing remains that only the lane can do;
   - (b) a review lane's verdict has been **received** by the manager;
   - (c) a research or analysis lane's report is received and its results are
     committed;
   - (d) the lane is superseded or re-dispatched;
   - (e) the row is `done`, `dropped` or `landed_unproven`, with the owed
     observation filed in the pipeline (`due_when` plus `origin.rerun`).
   An observation that only needs time or a data read is **not** a reason to
   keep a lane open — the pipeline row carries it, not the session.
3. **When NOT to archive:**
   - it still owns an unmerged PR that needs pushes;
   - its verdict or report has not been received (ask it to re-send first);
   - it is `BLOCKED` on an operator permission prompt (**surface it**; see below);
   - it is mid-run on a live action.
4. **Cadence.** This is step 5 of § "The operating loop", and it runs after every merge too. Archive
   the finished set in **one batch**.
5. **Record.** After archiving, read the final spend (`session_status ==
   SESSION_STATUS_ARCHIVED` is what makes it final) and note it on the row at the
   next register batch. Archiving is reversible: `unarchive_session`.
6. `close-out` check 7 and the closing gate's item 7 below point here.

### When session tools or the GitHub proxy fail: check status first

When `create_session` / `fire_trigger` / `create_trigger` or the GitHub
credential proxy fail, **FIRST check `https://status.claude.com/api/v2/summary.json`
and `githubstatus.com` before diagnosing locally.** On 2026-09-29 the manager
guessed "stale credentials" for ~30 minutes while an Anthropic major incident
was already posted. During an incident, `create_trigger` (with `run_once_at` 1–2
minutes ahead) can succeed where `fire_trigger` fails; retry with backoff.

⚠️ **A BLOCKED LANE IS THE EXPENSIVE ONE, AND IT LOOKS ALIVE.** `status_bucket`
`BLOCKED` means the lane is sitting on a permission prompt only a **human** can
clear — `fire_trigger` is refused there, correctly, because firing would answer
the prompt on the operator's behalf. **Surface it; never try to clear it.**
MEASURED 2026-09-22: lane MI-305 sat BLOCKED for **72.8 h holding $1,343.06** and never committed a
line. The reconciler prints this every run; a watchdog runs it independently
(`docs/claude/work/LANE-WATCHDOG-PROMPT.md`).

⚠️ **Do not write a rule about which command shapes trip a permission prompt**: `list_sessions` does
not expose the pending action, so nobody has established it (E20's was a stated hypothesis).

### Record the choice

On the lane's checklist row, record the model, fresh-vs-resume, **and the
reason**. A successor reads the reasoning, not just the value.

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

*Operator, close paraphrase: the roadmap is for high-level planning — highly detailed, but a tool for seeing the bigger picture of where we are on the way to the system goals. Build and prioritise the work queue FROM it, then keep it up to date with the outcomes of work. The architecture map is part of the same loop.*

Three artefacts, one loop. **Derive → prioritise → build → write back.**

| Artefact | Is | Lives in |
|---|---|---|
| **Roadmap** | the plan: 7 goals (G1..G7), each with a measure and a dated baseline, and the milestones that serve them | `docs/roadmap/milestones.yaml`, rendered into the generated "Live roadmap" block at the top of `ROADMAP.md` |
| **Work queue** | what is built (checklist rows) and what is asked (queue units), built FROM milestones | `docs/claude/work/checklist/`, `research/queue/` |
| **Architecture map** | what exists: components, paths, contracts | `docs/ARCHITECTURE-CANONICAL.md` |

This is not a third category of work. A build is a checklist row and a question is a queue unit, exactly as in CLAUDE.md; the roadmap is the parent both point at. The roadmap informs what gets built and authorizes nothing (tiers and mandates are unchanged).

**The link is a field, so it is checkable.**
- Every checklist row carries `roadmap: ["<milestone id>"]` from creation (`checklist.py add ... roadmap='["M20"]'`); every queue unit carries `roadmap: <id>`. If no milestone fits, that is a roadmap gap: add the milestone in the same PR (new milestones go under a goal in `milestones.yaml`; never reword another lane's entry), do not leave the work unparented.
- Closing a row (`done` or `landed_unproven`) sets `writeback: {"roadmap": "<what you changed in the milestone's where/next | none: reason>", "arch": "<ARCHITECTURE section you changed | none: reason>"}`. The lane that closes the row does the edit in the same PR. A change to a component, path or contract that leaves the architecture map unedited is a defect; a "none" needs its reason.
- `python3 scripts/ops/roadmap_map.py --report` lists, per milestone, live rows, closed rows and open units, plus rows and units with no milestone. A milestone with neither a live row nor an open unit must carry `no_rows_reason` (it says why none exists yet). Guard `roadmap-map-guard` fails: a dangling ref, an empty milestone with no reason, a stale `ROADMAP.md` block, an `architecture:` ref that is not a heading, and — on the diff only, so an old row never reddens an unrelated PR — a new row (`_seq` >= `enforce_from_seq`) or new queue unit without a ref, or a closing row without `writeback`.

**Cadence.**
1. **Per merge (the lane).** Write-back rule above. Reviews follow it too: a `/health-review`, `/performance-review` or `/ml-review` closes its row with a `writeback` naming the milestones its findings moved, and `/perf-followup` and `research-ops` units carry `roadmap` (the guard refuses the unit otherwise).
2. **Every daily review (05:52Z and 17:52Z): the roadmap hook.** Run the report and work what it shows, in the same turn, like blocker_watch: orphan live rows or open units get a milestone; an `active` milestone with no work gets rows or is set `dormant` with a reason; a milestone past `review_cadence_days` makes the weekly pass due today. Do not dispatch from memory when the report is a command away.
3. **Weekly roadmap pass — since 2026-10-14 this is PART 2 of the Wednesday planning dialogue, not a Monday row** (operator, 2026-10-14; see § "Weekly planning (Wednesday) and the weekly cycle" below). The `ROADMAP-PASS-<YYYYWNN>` rows are retired (W43/W44 dropped as superseded) and the Monday research-planning session with them; the research side of the pass is the Tuesday programme review. The seven steps below are unchanged — they are what the roadmap part of the Wednesday session does, and the roadmap is edited only once the operator and the manager agree. Each pass, in order:
   1. *Re-measure* every goal baseline and every active milestone's `where` with its own command (`check_tp_doctrine.py`, `config/accounts.yaml` counts, queue counts by theme, `--report`). A dated claim not re-measured is marked "not re-measured", never copied forward.
   2. *Read the week's outcomes*: rows closed since `reviewed`, results landed in `research/results/`, merged PRs. Rewrite `where` and `next` from them; set `reviewed`.
   3. *Derive*: every `next` with no row or unit gets one (with the ref); every ask the operator made since the last pass is placed under a milestone or becomes one.
   4. *Prioritise*: order what the manager dispatches by goal (a live-money defect under G3 first, then G1/G2 evidence, then the rest), and compare `research/THEMES.yaml` weights with where the open units actually sit; a theme weighted high with no runnable units is a finding, filed as a row (the weights themselves change only by a PR citing evidence, per `research/queue/PLANNING.md`).
   5. *Dormant sweep*: a milestone dormant with no work for two passes is closed or kept with a fresh reason; a milestone cannot just age.
   6. *Architecture check*: for each active milestone, does its `architecture:` list still describe what exists? Fix the map or the list.
   7. `python3 scripts/ops/roadmap_map.py --write-roadmap`, commit with the yaml, and file next week's `ROADMAP-PASS` row (due date in its note). The pass's output is its PR plus the rows and units it created or re-prioritised, named in the row's note.
4. **Slices plug in, they do not fork.** A lane that owns one slice (ML-ROADMAP-LOOP for G4, REGIME-PROGRAM for L-REGIME) adds and edits its own milestones under its goal in `milestones.yaml` and runs steps 1-7 for them inside the same weekly pass; the report and guard cover it with no extra wiring.

## Weekly planning (Wednesday) and the weekly cycle (operator, 2026-10-13/14, binding)

### Reviews first after the reset, planning Thursday morning (operator, 2026-10-19, binding)

Operator, 2026-10-19 (in substance): *"right after the reset, we kick off all of the weekly reviews — performance review, the ML review, the audit, a regular system review — make sure especially the research and training pipelines are healthy, and then we go on to the planning session on Thursday morning based on those insights and knowing how much capacity we actually have left for the week."*

1. **Order is binding.** After every weekly usage reset (Wed ~18:00Z) the manager starts ALL the weekly reviews first: performance, ML (+ frontier scan), the weekly audit, and a regular system/health review. Research and training pipeline health is checked explicitly in that pass.
2. **Planning comes after, on Thursday morning,** and is built on those review outputs plus a **post-review capacity reading** (`python3 scripts/ops/spend_meter.py --capacity` after the reviews have spent their share) — the workplan's allotments are sized to the capacity actually left for the week, not to the full allowance.
3. Triggers whose time contradicts this order are re-timed by the manager (a lane may propose, never edit them). The schedule table below is the pre-2026-10-19 timing until the manager re-times it; the order above wins where they disagree.
4. Mirrored in [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md) § 7b.


Row `WEEKLY-PLANNING`; trigger `trig_01Pm8AMPiigZX9ndobeyT6dE`, Wednesdays **08:20Z**, ahead of the weekly usage reset
(Wed ~18:00Z), so the plan is set before the reset and the new week starts with work already queued. First run 2026-10-14;
planning doc: https://claude.ai/code/artifact/27fd3e97-ed3f-49ba-be2c-5e56997df95a.

**It is a dialogue, not a report** (operator, verbatim: *"this session isn't just making a report, it's a dialogue between
both of us to work together on building our understanding, and then based on that, the work priorities"*). The manager
does not publish a finished plan and ask for sign-off; priorities are never finalised without the operator, and if they
are not available the working document stays current and the manager re-pings at a sensible time.

**Format.** (A) *Prepare, lean*: a short working document of facts, published as an Artifact the operator can read and
comment on — numbers with their population, merged / deployed / observed kept separate, the manager's own reading marked
as its own, **no priorities drafted, only open questions**. (B) *The conversation*, four parts in this order, one at a time:

| part | what | sources |
|---|---|---|
| 1. **Week review** | the week's work and system performance: what worked, what did not, where to focus improvement; ask what the operator saw that the data does not show, and challenge both readings where the evidence disagrees | PRs merged and rows moved since last Wednesday; lane spend vs ceilings; daily work reports and digest; live/paper/prop performance; research results and verdicts; CI health; incidents |
| 2. **Roadmap** | `python3 scripts/ops/roadmap_map.py --report`; milestone status, measures vs baselines, what to add, retire or re-scope; `docs/roadmap/milestones.yaml` is edited **only once agreed**. This is the weekly roadmap pass (§ "The roadmap loop" step 3) | the report, the week's closed rows and results |
| 3. **Schedule** | every recurring session for the coming week (`list_triggers`): agree the cadence, then create, update or delete triggers | the schedule below |
| 4. **Workplan** | priorities in order; per-priority resource allotment as a share of the weekly allowance with the Sonnet/Opus split and lane ceilings; the checklist rows and pre-registered `research/queue/` units to add — enough runnable work by theme weight to last the week; a preliminary day-by-day lane schedule to next Wednesday. Propose, listen, revise; popups only for crisp choices | parts 1–3 |

(C) *Close*: update the Artifact into the agreed plan; land the checklist, queue and roadmap edits in **one self-landing
PR** (a lane may do the landing — the 2026-10-14 outcome was landed by one Fable lane with a ~$8 ceiling); record the
outcome, the doc link and the schedule on row `WEEKLY-PLANNING`. Do this well before the reset.

**The weekly cycle** (agreed 2026-10-14; every trigger is bound to the manager session unless noted, so a manager
handover re-points them all — § "Manager handover"):

| when (UTC) | session | trigger | what |
|---|---|---|---|
| **Wed 08:20** | weekly planning | `trig_01Pm8AMPiigZX9ndobeyT6dE` | the dialogue above |
| **Wed 18:53** | review prep (after the reset) | `trig_01LE61kLKDFKptEfTfZ7vnYS` (bound to the assistant-manager session) | two Sonnet lanes: `PERF-REVIEW-PREP-<date>` (grading and numbers only — net P&L per capital-day in R and $ per strategy and whole book, giveback, TP-rule compliance; no `/perf-followup` yet) and `ML-FRONTIER-PREP-<date>` (`/ml-review` + frontier scan, no new units yet); one PR, `docs/reviews/<date>-weekly-walkthrough.md`, by 05:30Z Thursday |
| **Thu 06:30** | combined walk-through WITH the operator | `trig_01CpyqNkhwqEjLAHq1Wrrh1b` (fires 06:17 to prepare) | performance, then ML review + frontier scan, as a dialogue; after agreement dispatch `/perf-followup` (Opus lane) and turn agreed ideas into pre-registered units or rows inside the programme plans; outcome on `WEEKLY-PLANNING` |
| **Sat 07:23** | health review | `trig_013GU17584wu4HJYEkTF1KBk` (bound to the assistant-manager session) | one Sonnet lane runs `/health-review` end to end, dispositions every finding, self-lands one PR |
| **Mon 06:07** | weekly audit | `trig_017awLRNy4rmdL57NHKXehet` | one Opus lane: CORE every week (behaviour invariants on live data, TP-rule compliance, live = mirror, full cost stack, populations, overdue, spend, health review #2, RECURRENCE) plus a ROTATING deep pass by ISO week mod 4 (0 OUTCOME + INDEPENDENCE, 1 CONSISTENCY + LIVENESS, 2 MODULARITY, 3 DESIGN CRITICISM); follows `.claude/skills/weekly-audit/SKILL.md` once row `WEEKLY-AUDIT-SKILL` lands it |
| **Tue 09:53** | research programme review | `trig_01GuB9kH3CM4WJCJUgAb1s8Q` | one Opus lane updates the research map and the five programme plans (`docs/research/programmes/`: learned, answered / unlocked / retired questions, next 3–4 weeks of pre-registered units, cross-programme feeds); the queue is fed ONLY from these backlogs; one self-landing PR, so Wednesday starts from current plans |

Unchanged and still running: research-ops 4×/day, the manager daily reviews 05:52Z / 17:52Z, lane check-ins.

**Retired by this cycle (operator, 2026-10-14).** The Monday research-planning session and the Monday
`ROADMAP-PASS-<week>` rows: the **Tuesday programme review replaces them** on the research side and the Wednesday roadmap
part on the roadmap side. Do not re-file a `ROADMAP-PASS` row; file the roadmap outcome on `WEEKLY-PLANNING`.

## Standing authorizations — the ladder is fully automated

**The whole ladder fires on evidence, with no human in the path** (operator
grant, 2026-09-21): *"All the ladder decisions can be automated — that is a
standing mandate. Strategies can be promoted to live money without explicit
operator approval if the evidence supports the decision. I should just get a
ping in realtime of the update and an evidence review in the next daily
briefing."*

| mandate | grants | direction |
|---|---|---|
| `MD-PROMOTE-S0-S1` | add a leg to the soak book on a passing Stage-0 record | `add_risk` (paper) |
| `MD-PROMOTE-S1-S2` | **add a leg to a REAL-MONEY roster** on Stage-0 + Stage-1 cost fidelity | `add_risk` (real) |
| `MD-DEMOTE-S2-S1` | demote when the mirror goes net-negative net-of-cost — since 2026-09-29 the T3 ∧ net<0 rule over the last 40 closed trades (read `config/mandates.yaml`) | `derisk_only` |
| `MD-DEMOTE-S1-OFF` | drop a Stage-1 leg whose realized cost diverges | `derisk_only` |
| `MD-KILL-QUESTION` | close a question that failed its own pre-registered rule | `derisk_only` |

**When one fires: ping in realtime, then show the evidence record in section 1
of the next brief.** The operator checks the machine's reasoning after the
fact, not before it. The ping is not optional and a promotion to real money is
never silent.

⚠️ **"IF THE EVIDENCE SUPPORTS THE DECISION" IS NOW THE ENTIRE SAFETY
PROPERTY.** With nobody in the path, the bar's content is all that stands
between a passing number and real money. It must be a **committed evidence
record** — named harness, stated n, **net of the full cost stack**, clearing a
rule registered BEFORE the run. **A claim in a PR body is not a record.** If a
lane proposes a promotion without one, that is not a close call; send it back.

⚠️ **`MD-PROMOTE-S1-S2` DOES NOT ARM UNTIL D1 LANDS, AND THIS IS ARITHMETIC
RATHER THAN CAUTION.** The harnesses default slippage and funding to `0.0`, so
every "passed the backtest" verdict in today's corpus is fee-only and
optimistic by an unknown amount — measured once at **+0.57R**. Arming
auto-promotion against that corpus routes real money on numbers already known
to be wrong in the favourable direction. The `derisk_only` mandates carry no
such block: they read live measurement, not the corpus, and their worst case
removes exposure.

⚠️ **A mandate never authorizes judgement.** It fires on a stated rule against
a stated population, or it does not fire. "The manager thought it was fine" is
a session taking a Tier-3 action, which is forbidden.

⚠️ **Expiry is load-bearing.** An expired mandate stops authorizing.

The manager's standing duty: **keep moving decisions out of the brief and into
mandates.** A decision that arrives twice in the same shape is raised as
*"should this become a mandate, and at what bounds?"* A mandate that has NEVER
fired is either mis-specified or its condition does not occur — say which.

### Before any operator popup: classify the decision (operator directive, 2026-09-29)

PR #13698 asked the operator whether to promote `slv_trend_1h` — a leg that
turned out to be `execution: shadow` with zero real fills and an
`insufficient_n` cost-fidelity verdict. That should never have reached a
popup. The operator's ruling is the standing rule, not a one-off fix:

> "In general, we need clearer, more automated processes for these kinds of
> decisions — either we have enough data to decide, or we don't and then
> getting that data becomes a task which needs to happen so that a decision
> can be made."

So **before drafting any operator popup**, classify it into exactly one of
three buckets — never skip straight to drafting the question:

1. **Data-settled.** A committed evidence record decisively answers it —
   either under a granted mandate (act, ping, and record the evidence per
   the mandate table above) or under a tier the manager already holds
   (Tier-1/Tier-2 with the operator's standing "decide, ship, verify, then
   tell me" authorization — see `docs/CLAUDE-RULES-CANONICAL.md` §
   "Data-backed Tier-2/3 decisions"). **No popup.** Act, then report what
   happened in section 1 or 3 of the brief.
2. **Data-missing.** The evidence needed to decide does not exist yet, or
   exists but is below a stated floor (an absent Stage-0 record, `n` below a
   mandate's floor, an R3 cost-fidelity verdict of `inconclusive` /
   `insufficient_n` / `no_record` / stale, a leg that is `execution: shadow`
   or has never soaked at Stage 1). **No popup either.** File the data task
   in `docs/claude/work/PIPELINE.jsonl` via `scripts/ops/pipeline.py`, with a
   `clears_when` that states exactly what would settle it and an
   `origin.rerun` that re-asks the same question — a research-queue unit, a
   Stage-1 soak placement proposal, or a replay/backfill. `#13698`'s
   own case: `scripts/ops/mandate_resolver.py` now returns a THIRD verdict,
   `NEEDS_DATA` (never `FIRE`, never a decisive `REFUSE`), names the exact
   clause that lacks data, and `needs_data_pipeline_item()` /
   `file_needs_data()` turn that straight into a pipeline row — read that
   module's docstring before hand-rolling an equivalent for a non-ladder
   decision.
3. **Genuinely a preference.** Two courses are both evidence-supportable and
   the choice is a values call the operator has not already made standing
   policy on (a sizing tradeoff, which of two valid designs to ship, whether
   to spend budget on X vs Y). **Only this bucket earns a popup**, and it
   goes in section 2 of the brief with no cap on count.

A popup that turns out, on inspection, to be bucket 1 or 2 wearing bucket 3's
clothes is the `#13698` failure repeating. If a lane hands the manager a
question, the manager re-runs this classification itself before relaying it
— it does not trust the lane's own framing of "this needs the operator".

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

⚠️ **THE SYNC IS NOT MEASURED IN TIME** (operator, 2026-09-21): *"it takes
however long it takes to go through the work I need to do — I don't want us
tracking an arbitrary time limit to measure performance."* No target, no floor,
no ceiling. **Do not report session length as a metric.** Two earlier versions
of this file set a 30-minute ceiling and then a 30-minute floor; both were
rejected. What the manager owes is the WORK being ready, not a duration.

⚠️ **THERE IS NO CAP ON SECTION 2.** A queue outrunning one person is an
argument for automating the class, not for shortening the list.

⚠️ **THE BRIEF MUST BE SHORT, RANKED AND TRUE** (2026-10-04, lane BRIEF-FIX).
At 737 KB it went unread, and so it acted on nothing. The brief carries a size
cap and a soaks slot, ranks what needs action first, and states everything it
leaves out as a count. The pushed counterpart is the daily Telegram digest (§
"The work system"). The two must rank the same way.

## The work system — due work must reach someone who acts (operator, 2026-10-04, binding)

Design of record: [`docs/plans/work-system-2026-10-04.md`](../../../docs/plans/work-system-2026-10-04.md)
(checklist row **WORK-SYSTEM**). The operator, approving it: *"that's not a
band-aid, that's a structural fix … make sure it's canonized correctly in the
manager skill so all the managers pick it up."*

**Why.** MEASURED 2026-10-04: 366 pipeline items due, 151 unrouted, 25
`ask_operator` items that had never reached the operator, 36 of 45 Stage-1
soak legs with no definition of done, and a 737 KB brief that nobody read. Every
attention signal was a page someone had to choose to open. Now the **VM
computes due and pushes it**, and **silence is itself an alarm**.

### What runs without you (two VM timers; ONE Telegram message)

**`ict-work-digest.timer`, hourly. This is THE Telegram carrier; there is no other.** `work_digest_now.py`
sends ONE message per hour. The operator decided on 2026-10-04 to fold everything into it, with no
second digest timer, ever. The message is built in this order:
1. **🆕 NEW since the last digest.** These are the actionable edges, from `scripts/ops/attention_watch.py`:
   - a new `ask_operator` item;
   - a soak moving to `passed` or `mechanical_fail`;
   - an expected-signal alarm breaching or clearing, when:
     - the R5 grade is 8 or more days old;
     - no research result has landed in 36h;
     - an `in_flight` row has gone untouched for 3 days;
     - the checklist has gone unwritten for 30h;
     - the 05:30Z report is missing, stale, errored or over 64 KB.
2. **Once a day, after 06:00Z: the ranked summary.** Counts plus the top 8,
   `ask_operator` first.
3. **Otherwise one line:** "🟢 No new actionable items", plus the open counts.
   - **No edge set is seeded silently.** On its first pass, the watch sends one
     count line for each set that already exists at deploy, e.g. "❓
     ask_operator at deploy: N open", "🧪 Soaks at deploy: N passed · N
     mechanical_fail". Alarms need no seed line: the first pass reports every alarm
     that is breached.
4. **Then "what changed".** This is the change digest that existed before:
   checklist transitions and the standing close-wedge ledger.

**`ict-work-report.timer`, 05:30 UTC.** It runs `scripts/ops/work_report.py`, which **generates and
persists** the report the manager reviews and sends nothing. The report is stored at
`runtime_logs/work_reports/<report_id>.json` and served at `GET /api/bot/work/report`.
- `report_id` = `WR-YYYYMMDD-HHMMZ`.
- Contents: alarms · soaks · `ask_operator` · due top 25 · the brief verbatim.
  The brief comes from BRIEF-FIX's renderer, so there is one renderer, and its
  §3 is "what moved".
- Each section is marked `ok`, `empty`, `absent` (we looked; the source is not
  there) or `error`.

**Soak state is computed live on the VM** by `scripts/ops/soak_state.py::soak_states()`, which reads
the contracts SOAK-WATCH commits plus the journal DB. It is never a field a session writes.
If the module is absent, the section reads `absent`.

**The manager cannot receive Telegram.** Every hourly block that was sent is appended to
`digest_log.jsonl` and served at `GET /api/bot/work/report?since=<ISO>`.

⚠️ **The carrier's own death is not self-detected.** If `ict-work-digest` stops, its alarms stop
with it. The backstop is the review: a stale `generatedAt` or an empty `digestLog` is the first
incident.

### The daily review — TWICE a day, 05:52Z and 17:52Z, fired by a routine

**The manager gets no push.** The review routine IS the periodic check. Its prompt must name
`GET /api/bot/work/report?since=<last_review.reviewed_at>`. Each run:
1. **Fetch it. Check it before trusting it.**
   - `present: false`, a `generatedAt` that is not today's ≈05:30Z, or a
     non-empty `erroredSections` is the first incident. Fix it before anything
     else.
   - So is an empty `digestLog` across 12h, because it means the carrier is
     down.
2. **Run `python3 scripts/ops/blocker_watch.py` and work its findings with the rest.**
   Every finding is unblocked, re-queued, dispatched to a lane, or dropped with
   a stated reason in that same turn — a stale block is never left standing.
   It checks the claims the register makes about itself: a `blocked` row whose
   blocker is finished (`STALE_BLOCK`), a `queued` research unit never
   dispatched or not for 48 h (`NOT_RUNNING`, `NEEDS_LANE` when nothing will
   ever fire it), an operator wait past 7 days (`OPERATOR_WAIT`), a
   `landed_unproven` row past its `due_by` (`UNPROVEN_OVERDUE`). Operator,
   2026-10-10: *"if most of the things here aren't actually blocked, then
   that's a problem that they were still marked as blocked and weren't put into
   a work queue."* New findings also page once each (`attention_watch`) and
   sit under §0 of the brief.
3. **Work every item: dispatch, close, or decide.**
   - Dispatch: route it to a lane. Set `state: routed` and `routed_to: <session>`
     on the pipeline item, and give a build a checklist row.
   - Close: `done` or `killed`, with a `terminal_reason`.
   - Decide: per § "Before any operator popup".

   A `routed` item that is still due means its lane has not delivered. Check
   the lane, then re-dispatch or kill.
4. **Every silence alarm gets a fix lane the same day.** Anything due at a known
   time gets a `send_later` wake.
5. **Record the review.** Set the top-level `last_review` =
   `{report_id, reviewed_at, by, counts: {dispatched, closed, decided, carried}}`
   on the checklist (`checklist.py header last_review '<json>'` after the cutover), then push. Per-item dispositions live on the
   pipeline items, so the next review sees what is new.

**Prep always runs, and the scratch pad feeds it (operator, 2026-10-21, binding).** The operator, paraphrased from chat:
*the prep for the daily review should happen whether or not I actually do it — I might not always have time, though you should
try to remind me — prepare the summary and reports, send the summary to the bot so I can see it without going into the session,
and take the notes from the past day's scratch pad (the Google Doc) and add those items to the work plan.* So every review run:
- **Reads the scratch pad.** That is the Google Doc "Metis — Ideas inbox", read with the Google Drive connector. Every item added
  since the last review is copied verbatim into `docs/claude/work/IDEAS.md` and triaged, in that run, into a checklist row, a
  `research/queue` unit, or `killed` with a reason.
- **Publishes a short work-plan status whether or not the operator joins.** It covers what moved, what is running, where work was
  left off, the decisions waiting, the scratch-pad items and their homes, and the next step on the standing priorities.
- **Sends that status to @claude_ict_comms_bot** with the `send-ping` system-action, so the operator can read it without opening the
  session. It also sends one reminder that the review is ready. A review the operator skipped is still a review that ran.

**Roadmap hook (2026-10-11).** After step 5, run `python3 scripts/ops/roadmap_map.py --report` and work its findings per § "The roadmap loop" (orphans, empty active milestones, an overdue weekly pass).

### Manager ↔ lane: PUSH plus POLL (operator directive 2026-10-04, binding)

1. **PUSH (primary).** A lane wakes the manager the moment it finishes, is
   blocked, or has something the manager must act on: `create_trigger(persistent_session_id=<manager>)`
   then `fire_trigger`. If that prompts, the fallback is a PR comment. The
   manager acts on a wake immediately.
   **Measured rule (MANAGER-WAKE-REFUSED, 2026-10-23): the wake works only
   from a session at lineage depth ≤ 7 (limit 8).** `get_session` (no id)
   returns `lineage: {depth, limit}`. A session at 8/8 cannot create
   triggers or sessions; its refusal reads "lineage depth limit". So the
   manager must itself sit at depth ≤ 6, so its lanes sit at ≤ 7, and a
   manager rotation is created by a shallow session, never by the manager.
   A lane that finds itself at 8 reports by PR comment (the 3 h check-in
   reads it) and does not retry the trigger.
2. **POLL (backup).** The routine "Manager lane check-in" (cron `17 */3 * * *`)
   runs § "The operating loop" every 3 h. Its prompt is that one line. Within
   it, restart or re-dispatch any lane that is dead, stalled, finished without
   pinging, or over its ceiling, and record it when a lane missed its wake.

**Which PRs the manager subscribes to (operator, 2026-10-25, binding — context-overhead cut).**
The manager subscribes ONLY to (a) the ops-flags PR (§ "Standing alert subscriptions") and (b) PRs the
manager itself opens (register PRs). It does **not** subscribe to lane PRs. MEASURED 2026-10-25: every
subscribed PR injects a ~3k-token instruction block on each event; across 11 lane PRs this was the largest
single source of context growth (~150k tokens/h, a rotation every ~4 h). Nothing is lost:
- the **lane** is subscribed to its own PR and fixes red CI there (that is its job);
- the **lane wakes the manager when its PR is green and waits on the manager** (dispatch block below);
- for a held PR the manager may also set one `send_later` ~35 min out to merge on green (no event stream);
- the 3-hourly check-in (step 4, LAND) lists open PRs and lands every green one that waits on the manager,
  so a missed wake costs at most one check-in interval, never a dropped PR;
- **never archive a lane that still owns an unmerged PR** (§ "Archive protocol"), so a red PR always has a watcher.
Also read narrowly: `get_trigger` on named routines and `list_sessions(limit=10)`, not unfiltered dumps.

**Required dispatch block.** Every `create_session` for a lane has:
- `source_url` set;
- **`permission_mode: "auto"`**. A lane in default mode blocks on exactly the
  prompts it needs to wake you.
- `model` set explicitly;
- a checklist row (id, lane, ceiling), written before dispatch.
- Never merge a manager branch that has not landed on main into your branch; wait for it to land. A manager branch's unsquashed commit carries a merge-slot claim for another branch and fails manager-scope-guard (incident #19876, 2026-10-24).

The prompt ends with this block, filled in:

```
You are lane <ROW-ID>, dispatched by Manager Session <date> (<manager session id>);
its authority is the operator's (CLAUDE.md § Every session, step 1). Ceiling: $<N>.
WAKE THE MANAGER when you finish a deliverable, are blocked, or produce something it must act on:
create_trigger(persistent_session_id="<manager session id>", prompt=<what merged/deployed/observed,
what is blocked and on what>) then fire_trigger(<id>). Never set run_once_at (it fires twice).
If your PR waits on the manager (landing: hold), wake it AGAIN once CI on your head is green, with the PR
number and head sha; you stay subscribed to your own PR and fix red CI yourself. If that prompts, comment on your PR instead.
Then continue, or run close-out. Never stop to wait for direction.
```

### The soak contract — what the manager does with each state

The soak rule is stated once: [`OPERATING-PLAN` § 2 "The soak is
MECHANICAL"](../../../docs/plans/OPERATING-PLAN-2026-09-21.md). Do not restate
it in a dispatch, a row note or a contract; point at it. A Stage-1 placement
needs a contract in `docs/claude/work/SOAKS.json`
(`python3 scripts/ops/soak_state.py --backfill` writes it). What to do per live
state (`soak_state.soak_states()`):
- `passed` → the leg is a promotion candidate: run `MD-PROMOTE-S1-S2` (read the
  file for what it still requires).
- `mechanical_fail` → dispatch the fix; the next clean trades re-soak it. Never
  wait it out.
- `awaiting_first_trade` / `in_progress` → nothing; no deadline.
- `unknown` → we could not look; find out why.

A grade's `kill` calls (e.g. R5) are applied under `MD-DEMOTE-S1-OFF` /
`MD-KILL-QUESTION`, or filed with a reason. They are never just read.

### Decision batching

Operator decisions go out **batched**: a new one as a 🆕 line in the next hourly
digest, and all open ones in the daily summary and the report's ask_operator section, each with options and a recommendation. A decision is the
exception to batching only when it blocks live money or a live incident. That
one goes out at once via `send-ping` with `priority=urgent`. A decision that
arrives twice in the same shape is raised as *"should this become a mandate?"*

### Day one for a NEW manager

1. Title yourself and read the canonical docs (§ "Start of session").
2. **Run `list_triggers`.** Routines bound to a session die with it.
   - Recreate or rebind both **"Manager lane check-in"** (`17 */3 * * *`, prompt:
     "run the operating loop (manager SKILL.md § The operating loop)") and the
     **twice-daily review** (05:52Z, 17:52Z) to YOUR session.
   - The review prompt must name `GET /api/bot/work/report?since=…` and
     § "The daily review" above.
3. **Tell every live lane your session id**, using its own trigger. Its wake
   target changed.
4. Run `curl -sS 'https://ict-bot.duckdns.org/api/bot/work/report?since=<yesterday>'`.
   If it is absent or stale, check `/api/diag/services` for
   `ict-work-digest.timer` and `ict-work-report.timer`. Fixing that comes
   before anything else.
5. Run the review. Clear `ask_operator` items first, by classification, not by
   forwarding. Record `last_review`, push, then answer.

## Manager handover (rotation)

> **Operator, 2026-10-13 (verbatim):** "we need to add a section to the manager skill to streamline handover - basically, I want the manager to handoff at their own discretion, we just need to make sure it's clear how to validate a complete handoff to the new manager before the current one turns off".

The manager rotates **at its own discretion**; no operator OK is needed to start. What is not discretionary is the proof: **the old manager stays responsible until V1–V5 below have all passed, with evidence in the handoff doc.** `old` = outgoing manager, `new` = incoming.

### When

Typical reasons:
- **Context past ~650k tokens.** Cost per turn scales with context; the 2026-10-11 session reached 730k tokens and $165 by 2026-10-13. Past it, the outgoing manager drives the rotation itself and never hands it to the operator.
  > **Operator decision, 2026-10-24 (popup answer, verbatim):** "~650k + slimmer handover (Recommended)". The concern, verbatim: "if we're always switching and the switch itself is using all that capacity, then we haven't really accomplished much here." The threshold was ~300k until then. MEASURED 2026-10-24: the outgoing manager sat at 664k context and $26.76 for the day; the handover's own share (~130-150k) is the manager's estimate (INFERRED), which is why the handover is slimmed below as well.
- **A natural boundary**, such as after a weekly planning pass or a review.
- **Degraded recall.**

**The rotation check is periodic, not remembered (operator ideas inbox, 2026-10-21).** The operator does not want to be the one
who notices. So every run of § "The operating loop", and the first turn after every context compaction, starts with one check:
call `get_session` on yourself and read `external_metadata.context_usage.used_tokens`. Past ~650k tokens, or with degraded recall,
**plan** the handover for the next natural boundary and say so in that loop's operator line. Below that, carry on silently.

**Never mid-incident, and never with a merge or deploy half-done.** Finish or hold it first.

### Steps

**1. PREPARE.** Write `docs/claude/work/handoffs/<YYYY-MM-DD>-<old-short>-to-new.md` (`<old-short>` = the first 8 characters of the old session id) containing:
- live lanes: session id, checklist row, what each is doing, what it owes;
- open PRs that need the manager (held, Tier-2/3, awaiting review);
- operator asks and decisions in flight, in their exact wording;
- every trigger and `send_later` that targets the old session (from `list_triggers`), by id and name;
- artifacts and PRs the old session watches;
- capacity state (the latest reading and the sustainable rate, § "The operating loop" step 2);
- operator directives from this session **not yet in checklist rows**: put them in rows first, then list the row ids;
- the new manager's first actions;
- the handover checklist block below, copied in.

Do not commit it from the manager session: `manager-scope-guard` refuses the
`docs/DOCUMENT-INDEX.md` row a handoff doc needs when it comes from a manager session. A small
lane (Haiku, ~$1; precedent HANDOFF-LAND-1022, #19521) lands it through a self-land PR
(§ "How lane PRs land").

**2. CREATE.** The new manager is created by a **SHALLOW session**, normally the assistant manager, **never by the outgoing manager**. The outgoing manager asks for it with a one-off fired trigger to the assistant manager carrying the parameters below. Each manager-created manager adds one level of session lineage; the limit is 8 and a session at depth 8 cannot create lane sessions (MEASURED 2026-10-23: `session_01Nk7tgM` landed at 8/8 and was abandoned; its replacement `session_01YHnEs6` was created by the assistant manager and sits at 6/8). The creator calls `create_session` with:
- `model`: **Opus** (the manager stays on Opus, operator); pass it explicitly;
- the same `environment_id`; `source_url` set; `permission_mode: "auto"`;
- tags `["manager", "predecessor:<old id>"]`;
- title `Manager Session YYYY-MM-DD`;
- prompt: read this skill and the handoff doc in full; `CLAUDE.md` is already in the system prompt (do not re-read it); from `docs/CLAUDE-RULES-CANONICAL.md` read only the sections named in § "Start of session" step 2. Then perform V1 (the SHORT diff, including its own depth, `get_session` → lineage) and **wait for the old manager's diff**. Do not start routine work yet.

**3. REWIRE.** `update_trigger` **cannot change a trigger's target session**, so:
- (a) For every trigger whose `persistent_session_id` is the old session: `create_trigger` the same name, cron and prompt with `persistent_session_id=<new>`, then `update_trigger(enabled=false)` on the old one. Do not delete the old ones until step 5.
- (b) Update every prompt that **names the old session id**: the research-ops routine, the assistant-manager charter and routines, the review and check-in routines, any live lane's brief. Routines: `update_trigger(prompt=...)`. Live lanes and the assistant manager: a fired trigger message (reply channel in § "Every spawn carries provenance"; `fire_trigger` takes no `text`) naming the new id as the wake target.
- (c) Re-subscribe the new session to the PRs it must watch (`subscribe_pr_activity`), **including the ops-flags PR** (number: `scripts/research/research_watchdog.yaml` `ops_flags.pr_number`; § "Standing alert subscriptions").
- (d) Point the checklist at the new manager. There is no dedicated "manager" header field: `checklist.py header last_review` carries `by` (the new manager sets it at its first review), and any row `note` or `owner` naming the old manager as escalation target is updated with `checklist.py note`/`set`. Push to `main`.

**4. VALIDATE.** All five must pass, each with its evidence written into the handoff doc.

| # | Check | Pass means |
|---|---|---|
| **V1** | **Short diff** | The new manager lists **only what differs from the handoff doc** (lanes, PRs, triggers, operator decisions) and nothing that matches. Read with targeted calls: `list_sessions(mine=true, limit=10)` and `list_triggers(enabled=true)`, not full dumps; `get_session` on itself for depth. The old manager checks the diff against its own list; every mismatch is fixed and re-read. Record the incoming manager's `used_tokens` here: the target is under ~80k for the whole handover (MANAGER-HANDOVER-SLIM). |
| **V2** | **Trigger audit** | The new manager is subscribed to the ops-flags PR (a `subscribe_pr_activity` call on it returns subscribed, not "already watched by another session"). `list_triggers` shows **zero enabled** triggers targeting the old session id. Every recurring routine, by name, exists, is enabled and targets the new one, including the "Manager lane check-in" routine (`17 */3 * * *`) (MEASURED 2026-10-23: dropped at the 10-21 and 10-22 rotations, a 4.7 h gap from 09:16Z to 13:59Z with no manager action). Counts match the pre-handover list from step 1. |
| **V3** | **Id sweep** | The ops-flags subscription is held by the new session only. No enabled trigger prompt, assistant-manager charter or live lane brief still names the old session id as the escalation target. Grep the prompts from `list_triggers` / `get_trigger` for the old id. |
| **V4** | **Wake round-trips** | (a) old → new: a test trigger is answered by a trigger back. (b) assistant manager → new: the assistant fires its escalation path and the new manager answers. (c) one live lane, if any, is told the new id and acknowledges. |
| **V5** | **Operator notified, in one message** | New session link, what moved, and anything **not** moved with the reason. |

A grep that returns nothing proves nothing until the same grep is shown to find the old id on a known positive (RULE ONE): run V3's search on the pre-rewire prompt list first.

V2-V5 are unchanged as checks; do them with targeted reads (`get_trigger` on the named routines, a grep over the already-fetched enabled list), not full re-dumps.

**5. STAND DOWN.** Only after V1–V5 pass:
- the old manager takes no further actions;
- its last message points to the new session;
- the **new** manager archives the old session (§ "Archive protocol") **after confirming nothing still wakes it**, for example a fired `send_later` lands in the new session. Then it deletes the disabled old triggers.

**If any check fails, the old manager stays responsible and fixes it. It never goes quiet with a check open.** A handover that stops partway is a HANDOFF with the gaps named in the handoff doc, not a completion.

### Handover checklist (the old manager copies this into the handoff doc and ticks it with evidence)

```
- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created by a shallow session (assistant manager), not by the old manager: <id / link>, Opus, tags manager + predecessor:<old id>; depth reported in V1: __/8
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = __)
- [ ] Prompts naming the old id updated; checklist references updated and pushed
- [ ] New manager subscribed to the PRs it must watch, incl. the ops-flags PR
- [ ] V1 read-back diffed against the old manager's list; mismatches fixed: <evidence>
- [ ] V2 trigger audit: 0 enabled triggers on old id; recurring routines present, enabled, on new id, incl. "Manager lane check-in" (17 */3 * * *): <list_triggers evidence>
- [ ] V3 id sweep: grep of prompts / charters / lane briefs for old id finds none (positive control shown): <evidence>
- [ ] V4 wake round-trips: (a) old->new <trigger id>  (b) assistant->new <evidence>  (c) lane ack <lane id>
- [ ] V5 operator told in one message: new link, what moved, what did not and why
- [ ] STAND DOWN: old manager's last message points to the new session; new manager has archived the old one after a wake landed in the new session
```

## The ladder the manager is moving things along

```
STAGE 0  Backtest        → does an edge exist, net of the FULL cost stack?
   GATE 1
STAGE 1  Soak            → bybit_1 · alpaca_paper. MECHANICS on 1–2 clean trades
                           (2026-10-15); realized cost is ongoing monitoring.
   GATE 2
STAGE 2  Live + mirror   → bybit_2 + bybit_portfolio · alpaca_live + alpaca_portfolio.
                           Identical rosters, identical trades. The mirror is the
                           honest-size read, and its net-of-cost window is the
                           DEMOTION signal.
```

**Edge is decided offline. A book only ever checks mechanics and cost.** If a
lane proposes advancing a leg to Stage 2 on live-book evidence, that is a
category error — send it back.

## Closing the session: publish the record, then ping

**Operator instruction, 2026-09-22, verbatim:** *"once you actually finish
merging and deploying all of the work and you're actually ready to close out the
session, then make the summary and then post it on the site so that I can refer
to it without having to go back into the chat. And ping me also when everything
is fully closed out."*

A chat reply is not the record. The operator should never have to scroll a
transcript to find out what a session did.

### The gate: what "fully closed out" means

Do NOT publish and do NOT ping until **all** of these are true. A partial close
reported as a close is the drop this whole contract exists to prevent.

1. **Every PR this session opened or drove is merged** — or is HELD with the
   blocker stated on the PR itself and filed in `PIPELINE.jsonl`. "Waiting on
   CI" is not closed out; wait, or say precisely what is pending and where.
2. **Deployed means deployed.** A row whose work needs a service reload is not
   done when the PR merges. Land it, wait for `ict-git-sync`, restart the unit,
   and OBSERVE the running process — `/api/bot/config` reports the FILE, not
   what the trader loaded.
3. **Every row has a true state**, and no row says `in_flight` against a lane
   that is not working. `landed_unproven` names the observation that closes it.
4. **Every finding is fixed, filed or flagged**, and *filed* means the pipeline
   or the checklist. A chat message, a PR comment and a memo are none of them.
5. **Doc sweep** — any doc this session's work made stale is corrected, not
   left for the next reader to trip over.
6. **`close-out` skill run**, all seven checks, including when stopping early.
7. **Every finished lane archived** per § "Archive protocol" above, and no lane
   archived while it still owns an open PR.

### Then, in this order

**PUSH FIRST.** The checklist is the operator's live Workflow page; answering
before pushing hands them a reply and a page that disagree.

**PUBLISH THE SUMMARY AS A PAGE** (the Artifact tool), not as a chat message.
It carries, at minimum:

- what each lane was dispatched to do, and what became of it
- what MERGED, with shas — and separately what DEPLOYED and what was OBSERVED,
  never collapsed
- what is verified vs what is still waiting, with the specific observation each
  one needs
- the decisions the operator made, in their own words
- **the session's own errors**, plainly — they are the most reusable part
- next steps in priority order, with the reason the first one is first
- a **receipt**: sessions run, spend per lane against ceiling, total, archived

**THEN PING**, with the page link and one line of state. Not before the gate
above is satisfied — an early ping trains the operator to re-check the work,
which costs more than the ping saves.

⚠️ **If the gate cannot be met, say so and do not pretend otherwise.** Publish
the page anyway, with the unmet conditions named at the top and what each one
needs. A handoff that states its own gaps is fine; one that implies completeness
it does not have is the failure.
