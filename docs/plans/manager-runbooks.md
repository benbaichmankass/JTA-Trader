# Manager runbooks (moved verbatim from the manager skill, 2026-11-06)

> **Doc status:** `live` · category `instruction` · last verified `2026-11-06` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Moved VERBATIM from `.claude/skills/manager/SKILL.md` (SKILLS-PRUNE, operator answer 2026-11-06). The manager skill keeps the binding rules and points here for the step-by-step recipe. Read the section for the kind of event you are acting on BEFORE you act on it.
>
> **Gates this adds or changes:** none. This is a relocation, not a change.

## A. Standing alert subscriptions: wake-marker recipes

> **Lane repository = `source_url` at creation (operator, 2026-11-12, binding).** A lane gets ONLY the repository named in
> `create_session(source_url=...)`; a session's repositories are fixed when it starts. Work in another repo (the SPA
> `ict-trader-dashboard`, the phone app `ict-trader-android`) is dispatched as a lane whose `source_url` IS that repo, or handed to a
> standing multi-repo lane the operator started (tag `repos:3`, e.g. lane UI-SPA). **Never try `add_repo` mid-session as the route**:
> the auto-mode classifier refuses it ("Access Added As A Means", 2026-11-11 and 2026-11-12), and a lane that cannot reach its repo
> must NOT close quietly: its blocker goes to the operator the same turn, and the manager re-dispatches the work the same day.
> Failure this rule closes: 2026-11-11/12 the UI lane merged only backend halves, the SPA halves sat unbuilt and the standing UI lane
> was not re-dispatched (operator: "I don't understand why that lane went silent").

## Standing alert subscriptions (operator, 2026-10-13, binding)

Full recipes (the exact `create_session` arguments, marker fields and receipts for every wake kind below): pre-diet § "Standing alert
subscriptions" in [`docs/archive/2026-10-27-context-diet/manager-SKILL.md.pre-diet`](../../docs/archive/2026-10-27-context-diet/manager-SKILL.md.pre-diet).
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
  row. **Every reviewer dispatch prompt says: "end your report with a `PACKET DEFECTS:` line (REVIEWER-BRIEF § 2d): each defect as field — reason —
  n/denominator, or `none`"** (PACKET-HEALTH, operator 2026-11-05). The wake comment prints `PACKET HEALTH <pkg>: …` from the packet's computed
  `packet_health`; a `degraded` / `could_not_look` line with a report that says `none` is a failed report, so re-ask once. **You file each reported
  defect once** on its one owner (`LTR-GRADER-COVERAGE` pricing, `LTR-PACKET-READ-REACH` venue reads; else a PIPELINE item), never a duplicate and never a new
  row. Never commit a packet or table yourself from the comment text. `packet_state` `could_not_commit` / `evidence_conflict` → no reviewer;
  an incident (the VM receipt `ltr_wake_post_receipt` and the poller run name the http code). An `ltr-mirror-refused` comment (a row the
  mirror refused on `packet_sha` or a missing cited file) is an incident: repair the branch file from the generator's bytes, never by hand.
  **Event `mandate_cadence`** (a per-package auto-apply mandate, `kind: ltr_auto_apply` in `config/mandates.yaml`, first MD-LTR-ADA-AUTO,
  operator 2026-10-29): the VM emits it for the scoped open package once per `review_cadence_minutes` slot after the bar boundary, with
  the packet committed first; dispatch the reviewer exactly as above, packet inline, and the VM applies its `recommended` row within the
  mandate's bounds. **Never run your own timer/scheduled watch that starts a reviewer without a marker** (the LTR-ADA-WATCH
  `evidence_missing` failure, 2026-10-29: only the wake poster commits packets). To review a package regularly, the operator grants a
  cadence on its mandate; there is no reviewer-commit or system-action packet route (runner queues are 15-50 min; operator 2026-10-29
  "we need to make sure the design doesn't increase latency on the round trip decisions").
  **Event `judgement_cadence`** (DESK-AM-REFOCUS, 2026-10-30): the VM's regular judgement slot for every open package of a reviewed
  account (`config/live_trade_review.yaml` `judgement_cadence.hours_by_timeframe`). The slot is UTC-aligned, so one marker carries the
  whole book. For a marker whose entries are ALL `judgement_cadence`, dispatch **ONE** Sonnet reviewer for the whole marker, not one per
  package: same branch, same REVIEWER-BRIEF, with every entry and every inline packet block verbatim. The reviewer reads any
  `omitted_too_large` packet from the branch (REVIEWER-BRIEF § 2b) and writes one row per package. A marker that mixes in trigger events
  is dispatched per package as above.
- **`desk-wake` / `desk-trigger-wake`** (operator 2026-10-26/27): `create_session` exactly as `.claude/skills/trading-desk/SKILL.md` § 6b
  specifies (Sonnet, auto, `desk/decisions`, depth-1 sparse checkout, WAKE PROMPT verbatim; the trigger kind adds the packet-id line). Do
  not read the packet. `could_not_commit` http 403 → tell the operator.
- **`short-hold-wake`** (DESK-SHORT-HOLD-LANE, operator 2026-10-27): ONE Sonnet lane per `order_package_id` on `live-review/rows`
  following `SHORT-HOLD-BRIEF.md`; on `short-hold-closed` note package, leg, rows, cost, latency and close reason on the row. A dead lane is
  noted, not an incident (the trade keeps its venue brackets).

## B. The checklist: edit recipe

### How to edit it — the recipe (PI-20261004-APBY4NTV-0003)

The register is **one file per row** under `docs/claude/work/checklist/<ROW-ID>.json` (the monolith
was deleted at the 2026-10-08 cutover; one shared array made every concurrent edit conflict). **Never
edit it with ad-hoc python.** The CLI writes one row atomically, checks it against the header's
declared `states` (and `priority_rank`: a positive number or null), and never touches the shared header:

```bash
python3 scripts/ops/checklist.py add  NEW-ROW --title "one line" --state queued --due-by 2026-11-05 --roadmap L-OPS --tier 1 --rank 3 --by "$SESSION"
python3 scripts/ops/checklist.py set  A3 state=in_flight lane=session_01... ceiling_usd=25 --by "$SESSION"
python3 scripts/ops/checklist.py set  A3 prs='[123,456]' blocked_on='[]'     # values parse as JSON, else string
python3 scripts/ops/checklist.py note A3 "what is true about this row"        # --append to add to it
python3 scripts/ops/checklist.py archive-lane A3                              # lane -> lane_history, lane = null
python3 scripts/ops/checklist.py queue --limit 10                             # the ranked runnable queue
python3 scripts/ops/checklist.py header last_review '{"report_id": "...", "reviewed_at": "..."}'   # writes the work store (not _header.json); read: work.py --via direct header get last_review
```

⚠️ **Process, not gates (operator, 2026-11-01, binding; lane `CHECKLIST-OWNER-DUE`).** The manager owns every row and does not assign owners
to sessions; `add`/`set` therefore FILL `owner=manager`, a computed `due_by` (the observation date the row names; else in_flight +2d, blocked
+7d, landed_unproven +3d, queued by `priority_rank` +1/+3/+7d) and `roadmap=["unmapped"]` + a reason (the weekly pass maps it). Nothing is
refused; only a *deliberate clearing* of owner/due_by/roadmap errors. The date is what step 4b of § "The daily review" measures. Gates this adds
or changes: **none.**


## C. The work system and the daily review

## The work system — due work must reach someone who acts (operator, 2026-10-04, binding)

Design of record: [`docs/plans/work-system-2026-10-04.md`](../../docs/plans/work-system-2026-10-04.md) (row **WORK-SYSTEM**); operator:
*"that's not a band-aid, that's a structural fix … make sure it's canonized correctly in the manager skill."* MEASURED 2026-10-04: 366 items
due, 151 unrouted, 25 `ask_operator` items never delivered, 36 of 45 soak legs with no definition of done, a 737 KB brief nobody read. Now
the **VM computes due and pushes it**, and **silence is itself an alarm**. Full detail of both timers: pre-diet.

**What runs without you.** `ict-work-digest.timer` (hourly) is THE digest carrier, no second digest timer ever. ⚠️ **Since 2026-11-04
(TELEGRAM-TRIM, `config/telegram_policy.yaml`) the full digest no longer goes to Telegram**: it is recorded (receipt `suppressed_by_policy`,
`digest_log.jsonl`, the alert ledger with `delivered: suppressed_by_policy`) and only a NEW actionable item (❓ ask, 🧪 soak transition, alarm) is sent, as one
short message. The digest content, unchanged:
🆕 new since last (new `ask_operator`, a soak moving to `passed`/`mechanical_fail`, an expected-signal alarm breaching/clearing) → once a
day after 06:00Z the ranked summary (top 8, `ask_operator` first) → otherwise one "🟢 No new actionable items" line → "what changed". No
edge set is seeded silently (one count line per set at deploy). `ict-work-report.timer` (05:30Z) runs `scripts/ops/work_report.py`, which
persists `runtime_logs/work_reports/<report_id>.json` (`WR-YYYYMMDD-HHMMZ`), served at `GET /api/bot/work/report`; each section is marked
`ok`/`empty`/`absent`/`error`. Soak state is computed live (`soak_state.py::soak_states()`), never a field a session writes. The manager
cannot receive Telegram: every sent block is in `digest_log.jsonl`, served at `?since=<ISO>`. ⚠️ **The carrier's own death is not
self-detected**: a stale `generatedAt` or empty `digestLog` is the first incident.

### The daily review — ONCE a day, 05:52Z, fired by a routine (operator, 2026-11-04: "we switched the twice daily to once daily leave it like that")

The review routine IS the periodic check; its prompt names `GET /api/bot/work/report?since=<last_review.reviewed_at>`. Each run:
1. **Fetch and check before trusting**: `present: false`, a `generatedAt` not today's ≈05:30Z, non-empty `erroredSections`, or an empty
   `digestLog` over 12 h is the first incident — fix it first.
2. **Run `python3 scripts/ops/blocker_watch.py`** and resolve every finding the same turn (unblock, re-queue, dispatch, or drop with a reason):
   `STALE_BLOCK`, `NOT_RUNNING` / `NEEDS_LANE`, `OPERATOR_WAIT` (> 7 d), `UNPROVEN_OVERDUE`. Operator 2026-10-10: *"if most of the things
   here aren't actually blocked, then that's a problem that they were still marked as blocked."*
3. **Work every item: dispatch** (`state: routed`, `routed_to: <session>`, a checklist row for a build), **close** (`done`/`killed` with a
   `terminal_reason`) or **decide** (§ "Before any operator popup"). A `routed` item still due means its lane has not delivered.
4. **Every silence alarm gets a fix lane the same day**; anything due at a known time gets a `send_later` wake.
4b. **The backlog drain — MANDATORY, once a day (the daily run) (operator, 2026-11-01, binding).** *"The manager owns everything, including the
   backlog ... check it once a day and open a lane that fixes the things that need to get fixed ... It's not like an open-ended optional."*
   The manager owns ALL checklist rows and pipeline items and **does not assign owners to sessions** (a row's `owner` is `manager`; `lane` is
   only who is working it now). Run `python3 scripts/ops/checklist_daily_measure.py`: rows by state, overdue, `landed_unproven` observations due,
   pipeline due, research units queued-not-run, and rows opened vs closed over 24 h and 7 d. Rank what is due (oldest and most money-relevant
   first) and **dispatch ONE `BACKLOG-DRAIN-<date>` lane** on the ranked set (one question per lane, row first, ceiling stated; it observes the
   soaks, closes or re-dates with a reason, and kills what is stale with a reason). A review that skips the drain lane has failed close-out. If
   inflow exceeds outflow three days running, put it in "decisions for you". No cap on starting work (operator: "No cap, metric only"). A lane
   that lands a change as `landed_unproven` writes the runnable `observe: {when, how}` on its row; lanes archive as normal and are not kept open.

4c. **Orphan drain — the research loop, daily (operator 2026-11-01, binding).** Run `python3 scripts/research/iteration_orphans.py`.
   The rule: [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../docs/plans/OPERATING-PLAN-2026-09-21.md) § 2 "What does not pass goes back into research — THE research workflow". Report the orphan count per kind as a NUMBER every review (target 0), and from `--levers` the subjects whose lever map has untested families with no live unit. Every
   `ORPHAN` (a testing leg, a non-live ML model or a live-review class with no live iteration unit) and every `overdue` iteration gets
   ONE disposition this run: the next research-ops slot is told to author it first (name the subjects in its prompt), a topic lane is
   dispatched for it, or the family-review path is opened (`research/family_reviews/`). Put the counts per kind in the brief's
   "what is running"; an orphan carried past two reviews is a dispatch failure of the manager, not of research-ops.
5. **Record the review**: `checklist.py header last_review '{report_id, reviewed_at, by, counts: {dispatched, closed, decided, carried}}'` (writes the work store; read back with `work.py --via direct header get last_review`), push.
6. **Roadmap hook**: `roadmap_map.py --report`, work its findings (§ "The roadmap loop").

**Prep always runs, and the scratch pad feeds it (operator, 2026-10-21, binding)** — the daily-review prep happens whether or not the
operator joins. Every run: **reads the scratch pad** (Google Doc "JTA Trader — Ideas inbox", formerly "Metis — Ideas inbox"; match EITHER title, the operator renames the doc, via the Drive connector), copies each new item
verbatim into `docs/claude/work/IDEAS.md` and triages it that run into a checklist row, a `research/queue` unit, or `killed` with a reason;
**publishes a short work-plan status** (what moved/is running, where work was left off, decisions waiting, scratch-pad items and homes,
next step on the standing priorities) **in-session and on the UI (Workflow page), NOT to Telegram** — the twice-daily summary is a
recurring post and the operator turned recurring Telegram posts off (2026-11-04, TELEGRAM-TRIM: *"I'd rather be focused on being able to
check on the UI when I want to check and not have to like sift through messages"*; supersedes the 10-21 `send-ping` of the summary).
`send-ping` is still used for a decision the operator must take or a red flag — an event, not the summary.


## D. Weekly reset protocol and close-up on low usage

## Weekly reset protocol (operator, 2026-11-02, binding)

> **Gates this adds or changes: none.** It fixes WHAT the manager does after the weekly usage reset and WHEN; it decides no execution, mode,
> promotion or merge.

Operator, verbatim excerpt: *"I just keep on going over this every week ... after the reset at 6 o'clock on UTC ... all the reviews that we
need to do in order to start the planning session ... if there are like monthly reviews ... spaced so that it doesn't happen every week ...
any work that was left undone, if we ran out of usage automatically, like we know how to close it up ... a reset protocol. Preferably with at
least a backup trigger from the VM ... even if I'm not necessarily available right after a reset ... kick things off after the reset as soon
as possible."* The strategy review stays WEEKLY with a 30-day lookback every week (`perf-review-prep`, `lookback_days: 30`).

**One source:** [`config/reset_protocol.yaml`](../../config/reset_protocol.yaml) (`jobs` with cadence / order / offset / model / ceiling /
skill / dedupe tag, and one-shot `after_reset` items). **Machinery:** `scripts/ops/reset_protocol.py` (`--plan <reset-ts>`, `--receipt`,
`--sweep`, `--self-test`). **Receipt store:** `comms/ops/reset_receipts.jsonl`, append-only, committed by the manager to `main` (no DB, no
second source of truth). **Triggers:** primary = a Claude routine Wed **18:05Z** (resolves the current manager by title; it forwards, never
dispatches on its own authority); backup = `.github/workflows/reset-protocol-backup.yml` (18:15Z wake comment on the ops-flags PR #17895 if no
receipt; 19:00Z RED-FLAG comment + `send-ping` if still none). The protocol dispatches each job at its offset itself (the legacy per-job routines are disabled; their prompts are the briefs, see
step 3). Primary routine `trig_018F2BmrzKwWTYoSYCCbroqy`; Thursday planning stays its own routine.

**The steps, in order. Step 0 is the claim; everything else is skipped by whoever finds the claim already made.**

0. **Claim.** `python3 scripts/ops/reset_protocol.py --receipt <reset-ts> --write started --by <your session id> --json '{"jobs_due":[...]}'`,
   then push that line to `main` at once. Exit 4 = another trigger owns this reset: stop in one line. The 18:15Z backup reads `main`, so the
   claim must be pushed before then.
1. **Restore the pacing cadence.** The pre-reset pacing (6 h check-ins, event wakes only) ends at the reset: put the check-in back to its
   normal cadence (`17 */3 * * *`, manager SKILL § Manager handover V2) with `update_trigger` and say so in the Telegram line.
2. **Stuck-work sweep.** `python3 scripts/ops/reset_protocol.py --sweep` lists checklist rows `in_flight`/`blocked`, open PRs older than 12 h
   and PIPELINE items with `due_when.event == weekly_reset` (the paused-work item, below). The script **cannot see sessions**: add
   `list_sessions(mine=true)` and find every lane that is blocked, failed or paused, plus every row with no working lane and every green-waiting
   or red PR. **Each gets exactly one disposition with a reason:** resumed (`SendMessage`/`fire_trigger`), re-dispatched (fresh lane, the
   resume note on its row as the brief), or closed (row `dropped`/`done`, reason written). A row `blocked` on a typed edge that is still
   open is a valid blocked row: say so and leave it. An empty sweep is read-state `ok`, never silence.
3. **Dispatch the due jobs.** `--plan <reset-ts>` prints them (monthly jobs appear on the first Wednesday reset of the month and
   `supersedes` the weekly job they replace). For each at its offset: check the `dedupe_tag` in `list_sessions` (created inside
   `dedupe_hours` = skip), then `create_session` with the config's `model` and `ceiling_usd`, tags `lane:<NAME>`, `manager:<id>`, `metis-lane`.
   **The lane brief:** read each weekly job's brief with `get_trigger(<brief_trigger>)` (a DISABLED legacy routine whose stored prompt is
   the brief; review prep's one brief covers its three lanes) and use it verbatim with the current manager id substituted. Monthly jobs use
   their config `note` as the brief. On a monthly week the deep audit replaces the weekly audit. The legacy per-job routines are disabled:
   this protocol is now the only dispatcher of these jobs.
   **Thursday planning** is its own routine, now `trig_01QhYHMBFSnMB5CYYAyy7MH6` (assistant session, forwards to the manager); the old
   `trig_01VKbpUoD72EAAs8oPUVU5Lm` is disabled.
4. **Start the `after_reset` items** the plan lists (key + reason); each starts once and is removed from the config in the PR that confirms
   it started.
5. **Receipt and ONE Telegram line.** `--receipt <reset-ts> --write complete --by <id> --json '{"dispatched":[...],"skipped":[...],
   "after_reset_started":[...],"stuck":{"resumed":n,"redispatched":n,"closed":n}}'`, push, then ONE `send-ping` line (sections separated by
   " || ", the workflow sends only the first line): what was dispatched, what was stuck and its disposition, what is waiting on the operator.

### Close-up on low usage (the other half)

At about **90% of the weekly bar**, or on any limit hit (a lane or the manager reads "usage limit"): **every running lane writes a resume <!-- population-ok: a threshold on the operator-read weekly usage bar (a rule parameter), not a measurement -->
note on its checklist row** (what is done, the exact next command, branch/PR, what it owes) **and stops**; it opens no new work and starts no
new lane. The manager then files **ONE PIPELINE item** listing all paused work, due at the next reset, so the sweep above finds it:

```
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts/ops"); import pipeline
pipeline.append({"id": pipeline.mint_id("<session id>"),
  "what": "PAUSED AT LOW USAGE <date>: <lane> (row <ID>, PR #n, resume note on the row); ...",
  "origin": {"kind": "session", "ref": "<session id>", "rerun": "python3 scripts/ops/reset_protocol.py --sweep"},
  "due_when": {"kind": "event", "event": "weekly_reset", "clears_when": "every listed lane is resumed, re-dispatched or closed with a reason"},
  "next_action": "dispatch_lane", "state": "queued"}, intent="new")
PY
```

`due_when.event: weekly_reset` is the marker `--sweep` reads. Close the item (`terminal_reason`) only when every listed lane has a disposition.
Hibernating before a usage-limit outage (§ above) is the same act at the manager level.

## E. Manager handover (rotation): full steps

## Manager handover (rotation)

> **Operator, 2026-10-13 (verbatim):** "we need to add a section to the manager skill to streamline handover - basically, I want the manager to handoff at their own discretion, we just need to make sure it's clear how to validate a complete handoff to the new manager before the current one turns off".

The manager rotates **at its own discretion**; what is not discretionary is the proof: **the old manager stays responsible until V1–V5 have
all passed, with evidence in the handoff doc.** `old` = outgoing, `new` = incoming. Full step text and rationale: pre-diet.

**When.** Context past **~650k tokens** (operator, 2026-10-24: "~650k + slimmer handover (Recommended)" — the switch itself must not eat the
capacity it saves), a natural boundary (after a planning pass or review), or degraded recall. **The check is periodic, not remembered**: every
run of § "The operating loop" and the first turn after every compaction starts with `get_session` on yourself and
`external_metadata.context_usage.used_tokens`; past ~650k, plan the handover for the next boundary and say so in the loop's operator line.
**Never mid-incident, never with a merge or deploy half-done.**

0. **ARCHIVE FIRST** (operator, 2026-11-05, binding: *"We also need to make sure that we're not forgetting to archive old lanes. That does not
   seem to be passing through to all the managers correctly."*). Before PREPARE, the outgoing manager runs the full sweep (§ "The operating
   loop" step 5) and archives **every finished lane it owns**; the handoff doc lists each lane left open **with a reason** (the sweep's KEEP
   list). The incoming manager re-runs the sweep as its first act (§ "Start of session" 2a), so a miss here is caught within one hand-off.
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
   *Before archiving:* the outgoing manager runs `python3 scripts/ops/routine_prompt_check.py <list_triggers JSON>` (all pages) and repoints any enabled routine whose prompt names its own session id (advisory, not a gate; row ROUTINE-PROMPTS-ON-ROTATION).
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

## F. Hibernating before a usage-limit outage

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
