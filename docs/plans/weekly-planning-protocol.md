# Weekly planning protocol (moved verbatim from the manager skill, 2026-11-06)

> **Doc status:** `live` · category `instruction` · last verified `2026-11-06` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Moved VERBATIM from `.claude/skills/manager/SKILL.md` § "Weekly planning (Wednesday) and the weekly cycle" (SKILLS-PRUNE, operator answer 2026-11-06: *"YES: halve manager SKILL.md … moving the planning/surge text verbatim"*). Still binding; the manager skill keeps a summary and points here. The planning routine's prompt names this file.
>
> **Gates this adds or changes:** none. This is a relocation, not a change.
>
> **Staleness note (added on the move, not part of the moved text):** the weekly-cycle table below copies trigger ids and times; `list_triggers` and `config/reset_protocol.yaml` are the source and win when they disagree.

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
([`docs/reviews/2026-10-29-followthrough-triage.md`](../../docs/reviews/2026-10-29-followthrough-triage.md) § 1). These steps are
mandatory in the planning routine's prompt and come BEFORE part (B) 1:

0a. **Before the numbers, the scoreboard** (net $/% per book + the sceptical-quant line for each leg up for decision; § "The daily brief"). Planning that starts from activity counts optimises activity.
0. **First agenda item: the numbers.** Run `python3 scripts/ops/review_followthrough.py --window-days 7` and put its table (with its
   population line) at the top of the Artifact. Each review's Layer 0 runs the same script with `--source <review>` first, so a review starts
   by grading its own prior follow-ups.
0b. **The backlog: reviewed weekly, budgeted in planning, drained the same morning (operator, 2026-11-01, binding).** *"The backlog is supposed
   to be reviewed and handled during the weekly review sessions so that we can account for that in the Thursday planning sessions."* Collect
   every review's backlog numbers (weekly-audit C6, health H15, ml C9 `backlog_coverage`, performance backlog gate) plus
   `checklist_daily_measure.py`; put one **BACKLOG** line in the workplan (due / overdue / unrouted, oldest age, opened vs closed 7 d, last
   week's drain result); budget the week's drain inside the capacity plan; and **dispatch that drain lane the same morning**. **Never
   bulk-drop**: every drop is a row with its own reason. One process, two cadences: **daily** (§ "The daily review" step 4b) drains what is
   due; **weekly** the reviews measure, planning budgets and dispatches. *What went wrong without it:* the 2026-10-28 weekly audit measured
   C6 **fail** (510 due, 59 unrouted, oldest unrouted 94 d) and health H15 **concern** (same 510; 275 of 337 health-backlog items with no
   owner), no drain lane was dispatched, and the 2026-10-29 bulk reset then dropped rows instead of working them (the register now holds 143
   `dropped` rows over all time; I did NOT verify how many came from that reset).
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

### Surge, then throttle: every workplan item is one or the other (operator, 2026-11-05, binding)

> **Gates this adds or changes: none.** It decides the ORDER and PACE work is dispatched in, never whether anything runs or trades.

Operator, verbatim excerpt: *"we push them even against unsustainable usage rates at the beginning, and then we slow down and pace
ourselves based on the usage that we have left to keep the rest of the week making sure that the systems stay running and that we progress
with work that we have capacity for ... I just want to make sure that for the weekly work plan, we know what stuff is surge stuff and what
stuff is if we get to it at the throttle down stage."*

1. **Tag in planning.** Step 4 (workplan) tags every (a) item `week_lane: surge`, `week_lane: throttle` or `week_lane: standing` on its checklist row
   (`checklist.py set <ID> week_lane=surge`), agreed with the operator like the rest of the workplan. The workplan Artifact lists the
   sets separately: standing, surge, throttle.
2. **What is surge:** real money (a leg, a fix or a bug on a real-money or prop book), anything that moves a strategy or ML model toward
   live trading, the week's big ML milestones, and the week's big strategic milestones (e.g. a redesign). **What is throttle:** important
   work that is not top of the line: development infrastructure that cannot go live this week (e.g. the options data infra), the less
   urgent parts of a UI upgrade, cleanups and guard pruning. When unsure, ask in planning; never let a row stay untagged.
3. **The surge** runs from planning: dispatch surge rows first, as wide as the work allows, and do NOT throttle them to the even weekly
   pace. Throttle rows wait unless a surge row is blocked and capacity would otherwise sit idle.
4. **The throttle-down** starts when the surge rows are landed or blocked, or when the capacity reading says the rest of the week's usage
   is needed to keep the systems running (the standing routines, live review, the daily review and incident response come first). From
   then on, REFILL dispatches throttle rows, paced to `spend_meter.py --capacity`. Record the switch on `WEEKLY-PLANNING` with the reading
   it was made on, and tell the operator in one line.
5. **Always on, surge or not (operator, 2026-11-05, second message, verbatim excerpt: *"even during the surge, I want to have one lane
   dedicated to the ML research ... making sure that that work plan is continuing to get taken care of even during the surge"*; *"we
   don't need to have like a backlog drain going, but we do need to make sure that we're not missing like the regular checkups ... those
   are sort of like the strategic items that should always have some resources allocated to them"*):**
   - **One ML-research lane through the surge.** It does not have to run constantly, but the ML research workplan (the throttle-tagged
     ML research rows, in queue order) must keep moving: at every check-in during the surge, if no ML-research lane is running and an
     ML research row is runnable, dispatch one. It is reserved: it is not counted against surge dispatch or displaced by it.
   - **The regular checkups are `standing` (`week_lane: standing`) and never pause for the surge**: the daily review, the weekly reviews,
     research-ops, live review and desk wakes, health and pipeline checks, incident response. They are dispatched before surge work when
     they are due. During the surge the backlog DRAIN may be deferred to the throttle-down (record the deferral on `WEEKLY-PLANNING`); the
     daily review's measurement of the backlog still runs. After the surge, standing work keeps first priority, then throttle rows.
6. **Prop-account MLs are surge** (operator, 2026-11-05: prop MLs belong with the real-money surge items).
7. **Mid-week arrivals** are tagged when they are filed: a new real-money bug or an operator directive about live trading is surge even
   after the switch, and is dispatched at once.

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
| Wed 19:29 (per the manager's 2026-10-28 dispatch; trigger time not re-read by that lane) | research programme review (`trig_01GuB9kH3CM4WJCJUgAb1s8Q`) | one Opus lane runs `.claude/skills/programme-review/SKILL.md` (CHECKS packet + per-programme, per-track ANALYSIS) and updates the research map and programme plans (`docs/research/programmes/`, `research/programmes/`); the queue is fed ONLY from these; one HELD PR (programme trees are landing machinery) |

Unchanged: research-ops 4×/day, the daily review ONCE a day at 05:52Z (operator 2026-11-04: "we switched the twice daily to once daily leave it like that"), lane check-ins. **Retired (operator 2026-10-14):** the Monday research-planning
session and `ROADMAP-PASS-<week>` rows; file the roadmap outcome on `WEEKLY-PLANNING`.

---

## Roadmap weekly pass and cadence (moved verbatim from the manager skill § "The roadmap loop", 2026-11-06)

**Cadence.** (1) *Per merge:* the write-back above; reviews close their rows with a `writeback` naming the milestones moved. (2) *Every daily
review:* run the report and work its findings that turn (orphans get a milestone; an `active` milestone with no work gets rows or goes
`dormant` with a reason; a milestone past `review_cadence_days` makes the weekly pass due). (3) *Weekly pass* — since 2026-10-14 part 2 of
the Wednesday planning dialogue (the `ROADMAP-PASS-<week>` rows are retired; never re-file one). In order: re-measure every baseline and
active `where` with its own command (an un-re-measured date is marked "not re-measured"); read the week's outcomes and rewrite
`where`/`next`, set `reviewed`; derive rows/units for every `next` and operator ask; prioritise by goal (live-money defect under G3 first,
then G1/G2 evidence) and compare `research/THEMES.yaml` weights with where open units sit (a high-weight theme with no runnable units is a
finding); dormant sweep (two passes without work = close or fresh reason); architecture check; `roadmap_map.py --write-roadmap` and commit.
(4) *Slices plug in, they do not fork* (ML-ROADMAP-LOOP, REGIME-PROGRAM edit their own milestones inside the same pass). Detail: pre-diet.

**Also from that section (verbatim):**
- **The link is a field.** Every checklist row carries `roadmap: ["<milestone id>"]` from creation; every queue unit `roadmap: <id>`. No
  fitting milestone = a roadmap gap: add one under a goal in the same PR (never reword another lane's entry).
- **Closing a row** (`done`/`landed_unproven`) sets `writeback: {"roadmap": "<milestone change | none: reason>", "arch": "<ARCHITECTURE
  section changed | none: reason>"}`; the closing lane edits in the same PR. A component/path/contract change with the map unedited is a defect.
- `python3 scripts/ops/roadmap_map.py --report` lists live/closed rows and open units per milestone plus orphans. A milestone with neither
  must carry `no_rows_reason`. Guard `roadmap-map-guard` fails dangling refs, empty milestones without a reason, a stale `ROADMAP.md` block,
  a non-heading `architecture:` ref, and (on the diff only) new rows/units without a ref or a closing row without `writeback`.
