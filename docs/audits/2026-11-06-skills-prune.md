# Skills prune audit, 2026-11-06: what to cut, merge or point instead of restate

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Lane `SKILLS-PRUNE-AUDIT`, dispatched by Manager Session 2026-11-05b (session_01AFoLuLmhUKeUzHC6CHz2uP). Measured 2026-11-06 on `main` @ `0297e3549`.
> Operator, 2026-11-06 ~00:52Z, verbatim: *"Yes, let's continue the sweep"*, after *"make sure that what left is designed optimally and efficiently and not redundant or repetitive"*.

**Gates this adds or changes:** none. This doc proposes moving text to pointers. It changes no rule's meaning, and **nothing in `.claude/` or any other doc is edited until the operator approves** (§ 6).

## 1. How this was measured, and what it cannot say

- **Bytes** are `wc -c` over every file in each `.claude/skills/<name>/` (MEASURED, 2026-11-06). Total: **868,400 B** (41 files; the dispatch said ~643 KB, and the 32 `SKILL.md` files alone sum to 704,500 B; the total here includes the wake briefs, amendment logs and two `.py` files that live beside the skills).
- **"Last change" cannot be taken from git.** The clone is shallow (50 commits, oldest 2026-11-05); every skill reads "2026-11-05". A `git fetch --deepen=1500` timed out. I used each skill's own `last verified` stamp instead, and those stamps are *claims*: `manager` says `2026-10-27` yet gained ~21 KB after that date (§ 3).
- **Invocation counts do not exist** (Skill-tool calls are not logged). The proxy is *references from outside the skill*: files outside `docs/archive` that name `skills/<name>` or `/<name>`, and references from `.github`, `config`, `CLAUDE.md`, the canonical doc or `settings.json`. Substring counts are noisy (`health-review` 174, because `/health-review` appears in many prose lines), so read the *ops* column as the signal and the *all* column only as a ceiling.
- **Not read in full:** I read the manager skill in full and measured every other skill by section size and targeted grep. Savings for those are **ESTIMATED** from section sizes, marked `~`. The byte-identical block in § 2a is MEASURED (md5).
- The canonical doc is 159,496 B and `CLAUDE.md` 23,478 B. I did not prune either; I only record where skills restate them.

## 2. Findings

### 2a. One block is copied byte-for-byte into six skills (MEASURED)

The section `## Definition of done — a capability is not shipped until something RUNS it` is **5,149 B and identical (md5 `d354dafc75c5`) in `backtesting`, `exit-refinement`, `macro-research`, `model-training`, `new-broker` and `new-strategy`**, at the end of each file. It ends with a paragraph saying `/system-review` "now enumerates everything shipped since the previous review"; `/system-review` was retired and archived 2026-09-21. The rule is not stated in the canonical doc or `CLAUDE.md` (grep outside the skills finds nothing), so it needs **one** home. 6 × 5,149 = 30,894 B becomes 5,149 B + 5 pointers.
Whether the `review_coverage.since_last_build_verification` field is still produced by anything now that its review is retired is **unverified**; `scripts/reports/render_system_report.py` still mentions it. That is a separate question, filed in § 7.

### 2b. The manager skill has regrown

`manager/SKILL.md` is **87,782 B**. The context diet (2026-10-27) started from 100,457 B (`docs/archive/2026-10-27-context-diet/manager-SKILL.md.pre-diet`). The dispatch quotes ~66 KB; I did not measure the post-diet size, so the regrowth is **about +21 KB since the diet if that figure is right**. Every new operator directive was added as a new section with its verbatim quote, so the file grew back by the same mechanism the diet removed. It is loaded in full by every fresh manager and by every rotation.
Size by section (MEASURED): work system 12,337 · weekly planning and cycle 11,833 · Spawning 10,884 · operating loop 8,317 · handover 6,453 · weekly reset 6,295 (includes its 1,261 B close-up) · alert subscriptions 5,108 · checklist 4,650.

### 2c. Rules restated in several places

| rule | where it is stated now | proposed ONE home | pointer elsewhere |
|---|---|---|---|
| **No new gates** | canonical § "No new gates…" (4 hits), `CLAUDE.md` (2), manager (2: § Spawning and the Weekly-reset box), `backtesting`, `new-strategy` | canonical (already the home) | one line `see canonical § "No new gates…"`. The per-doc "Gates this adds or changes" opener is the *required form*, not a restatement, and stays. |
| **The soak is mechanical** | OPERATING-PLAN § 2 (the stated-once home), `CLAUDE.md`, manager (2), `model-training`, `new-strategy`, `performance-review` | OPERATING-PLAN § 2 | a pointer. The guard `soak-doctrine-guard` already refuses a *longer* soak. Manager § "The soak contract" and § "The ladder…" are duplicates of `CLAUDE.md` and go. |
| **Permission tiers** | canonical § Permission Tiers, `CLAUDE.md` table, `credentials-and-vm-mutations`, `health-review` | canonical | pointer |
| **Merge/landing recipe** (`pr-landing` + `pr-automerge-requests` + `claim_merge_slot` + `ccr/auto_merge`) | manager § "How lane PRs land" (4), `settings.json` SessionStart hook (3), one line each in `health-review`, `ml-review`, `performance-review`, `research-ops` | manager § "How lane PRs land", shrunk, with the commands emitted by a script (§ 4) | pointers |
| **Checklist edit recipe** | manager § "How to edit it" (7 commands, 1 KB), `CLAUDE.md`, 6 more skills name `checklist.py` | `checklist.py --help` (the script owns its syntax) | one line each |
| **Audit-outcome contract** | manager § (1.4 KB), `close-out` check 4, and a `## Done-condition` section in `health-review`, `ml-review`, `performance-review`, `programme-review`, a numbered item in `weekly-audit` | manager § (home) | each review keeps one line `Done-condition: manager § "The audit-outcome contract"` plus its own table-column name. Savings are small; the value is one place to edit. |
| **Soak/ladder, six brief sections, standing authorizations** | `CLAUDE.md` (full), manager § "Standing authorizations", § "The daily brief", § "The ladder…" | `CLAUDE.md` + `config/mandates.yaml` | manager keeps only the manager-specific parts (the popup classification) |

### 2d. Stale content (MEASURED, grep of `.claude/skills` on 2026-11-06)

- `system-report/SKILL.md` is a "back-compat alias" for `/system-review`, which is archived. Its target file `../system-review/SKILL.md` **does not exist** (it is under `docs/archive/2026-09-21-operating-reset/skills/`). The skill resolves to nothing.
- `/system-review` is still cited as live in `model-training:267`, `macro-research:304`, `backtesting:424`, `new-strategy:724`, `new-broker:263`, `exit-refinement:407` (all inside the § 2a block), `diag-data:80` and `weekly-audit` C6.
- `doc-freshness:165` links `../research-driver/SKILL.md`, retired 2026-09-21. `macro-research:11,28` say `research-driver` dispatches to it. `llm-delegate:213` lists the retired `delegate-work` as a live sibling.
- The manager skill's Archive protocol item 0 says the repo slug is `Metis-Insights` "until the operator renames it". It was renamed 2026-10-28 (`CLAUDE.md` § Repo identity). Two other "Metis" mentions are the deliberately kept names (`metis-lane` tag, the old Google Doc title).
- **20 of 32 skills carry `last verified 2026-09-07`** (60 days) or earlier, so their stamps predate the operating reset of 2026-09-21. Those 20 were not re-verified by this audit.
- The weekly-cycle trigger ids and times (`trig_01…`) in manager § "Weekly planning" are copies of what `list_triggers` returns. The manager text itself says one time was "not re-read by that lane". Any copy goes stale; the table should point at `config/reset_protocol.yaml` / `list_triggers`.
- The `.claude/settings.json` SessionStart hooks inject **~9.3 KB into every session** (4,034 + 3,956 + 1,324 B). Most of it restates `CLAUDE.md` § "Every session", the canonical Generation Discipline and the review-skill split. It is a canonical-instruction duplicate loaded by every lane, so it costs more than any skill. Proposal in § 5.

### 2e. Bloat that is a script or a table

- Manager § "Weekly reset protocol" (6.3 KB) and "Close-up on low usage" (2.3 KB): `config/reset_protocol.yaml` already holds the jobs, offsets, models and ceilings, and `scripts/ops/reset_protocol.py --plan/--sweep` prints them. The prose re-narrates the config. The close-up item embeds a 10-line Python heredoc that appends a PIPELINE row; that is a `pipeline.py` subcommand waiting to exist.
- Manager § "Recurring dispatches" (4.3 KB): each bullet describes a cadence the *owning skill* (`research-ops`, `perf-followup`, `frontier-research`) already carries. The manager needs a 5-row table (name, cadence, model, ceiling, skill).
- Manager § "Standing alert subscriptions" (5.1 KB): the `ltr-wake` / `mandate_cadence` / `judgement_cadence` recipes are the live-review reviewer's dispatch contract. They belong in `live-trade-review/SKILL.md` (which already owns the REVIEWER-BRIEF); the desk and short-hold wake recipes belong in `trading-desk/SKILL.md` § 6b, which already says "create_session exactly as … § 6b specifies". The manager keeps the one rule that is its own (subscribe to the ops-flags PR; one marker, one lane).
- Manager § "The daily review" step 4b/4c (≈3 KB of prose): the commands are `checklist_daily_measure.py` and `iteration_orphans.py`, whose output is the instruction. Keep the rule, cut the narrative.
- Verbatim operator quotes: 76 lines in the manager, 53 in `live-trade-review`, 43 in `trading-desk`, 18 in `research-ops`. A quote proves authority; it need not be reloaded every session. Keep a date + 6-word quote in the skill and move the full text to the archive (the pre-diet file already does this for older ones).
- `AMENDMENTS.md` logs in `live-trade-review` (8.9 KB) and `trading-desk` (3.9 KB) are change history, not instruction.
- `research-ops` § "What changed on 2026-10-16" (4.0 KB) is a changelog inside the skill.
- `performance-review` repeats three things that have homes: "Live review (LTR-5)" 4.9 KB (→ `live-trade-review`), "Underperformance → diagnose, don't demote" 4.4 KB (→ canonical § "Tune before demote" and manager "Underperformer first step"), "Fetching trade data" 3.4 KB (→ `diag-data`).

### 2f. Skills that could merge or retire

| candidate | verdict | why |
|---|---|---|
| `system-report` | **Retire** | alias to an archived skill (§ 2d). The only mechanical cost is that `check_skills_index.py` requires every `SKILL.md` to be named in `docs/claude/INDEX.md`, so the index line and `DOCUMENT-INDEX.md` row 233 go in the same PR. |
| `doc-freshness` (13.0 KB) into `close-out` (7.6 KB) | **Candidate; read both in full before deciding** | both run "at the end of a session"; `close-out` check list and `doc-freshness` step list overlap on "docs updated / finding filed". I did not read both in full, so I do not know whether the merge loses a rule. Not in the savings total. |
| `db-setup` (6.1 KB) + `db-wiring` (4.0 KB) | **Candidate** | both are about the canonical SQLite stores; each says it composes with the other; each has 1–8 outside refs. Merge saves headers and the cross-references only (~1 KB). Low value; leave unless touched. |
| `vm-ops` + `git-actions` + `diag-data` + `credentials-and-vm-mutations` + `before-asking-the-operator` | **Keep** | five small skills (4–8 KB) with distinct triggers; `diag-data` and `git-actions` are referenced from 9–12 other skills. Merging would not cut a repeated rule. |
| `llm-delegate`, `vm-migration` | **Keep** | each has a live workflow (`llm-delegate.yml`; `cutover-live.yml` etc.). Fix the stale `delegate-work` link in `llm-delegate`. |

## 3. Inventory and proposals (one row per skill)

`ops refs` = references from `.github`, `config`, `CLAUDE.md`, canonical, `settings.json`, routine files. `saved` is bytes removed from `.claude/skills` (`~` = ESTIMATED from section sizes, not read in full). "Rules kept" lists what must survive and where it lives after the change.

| skill | bytes | last verified (claim) | ops refs / all | proposal | saved | rules preserved, and where they live after |
|---|---:|---|---|---|---:|---|
| **manager** | 87,782 | 2026-10-27 | 72 / 201 | Cut to ≤ 40 KB (§ 4). | **~48,000** | § 4 table lists each binding rule and its destination. |
| **trading-desk** (6 files) | 132,373 | 2026-10-27 | 4 / 38 | Move `AMENDMENTS.md` to archive; take the desk/short-hold wake recipes from the manager (§ 6b is the home). Check `SKILL.md` § 2 "Roles" (4.1 KB) against its design doc. Leave the DESK/SHORT-HOLD briefs (repo-less wake briefs must be self-contained). | ~8,000 | § 0 binding limits and § 6b untouched. |
| **live-trade-review** (3 files) | 107,952 | 2026-10-26 | 3 / 23 | `AMENDMENTS.md` (8.9 KB) to archive; § 0.0 (6.9 KB) and § 3b (5.7 KB) point at ARCHITECTURE § "Active management" and `mandates.yaml` for what they restate; absorb the manager's `ltr-wake` recipe (net + ~2 KB). | ~15,000 | REVIEWER-BRIEF stays whole (it is read repo-less). Advice-only-until-tested rule stays in § 0.0 as one paragraph. |
| **performance-review** (3 files) | 75,962 | 2026-10-28 | 18 / 160 | Replace the three duplicated sections (§ 2e) with pointers; keep the Layer 1/2 structure and the blind/reveal briefs. | ~10,000 | Blind-then-reveal grade, per-decision scoring, prior-calls grading. Underperformance rule lives in canonical § "Tune before demote". |
| **research-ops** | 59,079 | 2026-11-01 | 64 / 13 | Archive the "What changed 2026-10-16" changelog; fold § D/E duplicate bullets. Keep THE CORE MANDATE whole. | ~6,000 | Core mandate, A–E pass structure. |
| **new-strategy** | 38,964 | 2026-09-07 | 1 / 18 | Remove the § 2a block (−4.8 KB); shrink "The execution gate" (3.3 KB) to a pointer at `CLAUDE.md` § "The two execution gates". | ~7,300 | Definition-of-done lives in its one home (§ 5, item 2). Two-gate rule stays in `CLAUDE.md`. |
| **ml-review** | 30,644 | 2026-10-28 | 18 / 189 | Done-condition → one line. | ~300 | Audit-outcome contract (manager). |
| **frontier-research** | 30,328 | 2026-10-28 | 3 / 21 | None proposed (not read in full). | 0 | — |
| **backtesting** | 27,808 | 2026-09-07 | 0 / 32 | Remove the § 2a block. Stamp predates the reset: needs a verify pass. | ~4,800 | DoD in its one home. |
| **perf-followup** | 27,722 | 2026-10-28 | 4 / 42 | None proposed. | 0 | — |
| **exit-refinement** | 26,604 | 2026-09-07 | 17 / 43 | Remove the § 2a block. Needs a verify pass. | ~4,800 | DoD in its one home. |
| **weekly-audit** | 26,522 | 2026-10-28 | 6 / 5 | Fix the `/system-review` mention in C6; Done-condition → one line. | ~300 | Audit-outcome contract. |
| **health-review** | 25,701 | 2026-10-28 | 217* / 174* | Done-condition → one line. (*ops/all inflated by the string `/health-review`.) | ~300 | Audit-outcome contract. |
| **macro-research** | 21,309 | 2026-09-07 | 0 / 91 | Remove the § 2a block; drop `research-driver` mentions (L11, L28). | ~4,900 | DoD in its one home. |
| **model-training** | 17,401 | 2026-09-07 | 0 / 3 | Remove the § 2a block; drop the `/system-review` mention. | ~4,800 | DoD in its one home. |
| **new-broker** | 16,128 | 2026-09-07 | 0 / 3 | Remove the § 2a block. | ~4,800 | DoD in its one home. |
| **programme-review** | 15,792 | 2026-11-01 | 4 / 7 | Done-condition → one line. | ~300 | Audit-outcome contract. |
| **doc-freshness** | 13,038 | 2026-09-07 | 1 / 17 | Fix the dead `research-driver` link. Merge into `close-out` only after a read-in-full lane (§ 2f). | ~100 | — |
| **llm-delegate** | 12,621 | 2026-09-07 | 0 / 5 | Fix the dead `delegate-work` link. | ~100 | Scope guard (public code and docs only). |
| **credentials-and-vm-mutations** | 8,320 | 2026-09-07 | 0 / 3 | Keep; tier restatement → pointer. | ~400 | Operator originates secrets only. |
| **diag-data** | 8,051 | 2026-09-07 | 0 / 18 | Keep; fix `/system-review` mention. | ~100 | — |
| **close-out** | 7,612 | 2026-09-21 | 2 / 6 | Keep. It is the completion test. | 0 | — |
| **vm-migration** | 6,998 | 2026-09-07 | 1 / 8 | Keep. | 0 | — |
| **regime-selectivity** | 6,797 | 2026-09-07 | 0 / 46 | Keep. | 0 | — |
| **before-asking-the-operator** | 6,526 | 2026-09-07 | 1 / 2 | Keep. | 0 | — |
| **git-actions** | 6,330 | 2026-09-07 | 0 / 16 | Keep. | 0 | — |
| **db-setup** | 6,090 | 2026-09-07 | 0 / 1 | Keep (see § 2f merge option). | 0 | — |
| **sprint-format** | 4,753 | 2026-09-07 | 0 / 5 | Keep. | 0 | — |
| **vm-ops** | 4,284 | 2026-09-07 | 0 / 4 | Keep. | 0 | — |
| **db-wiring** | 3,968 | 2026-09-07 | 0 / 8 | Keep (see § 2f). | 0 | — |
| **drift-remediation** | 3,542 | 2026-09-07 | 0 / 19 | Keep. | 0 | — |
| **system-report** | 1,399 | 2026-09-07 | 1 / 30 | **Retire** (delete the directory; index lines in the same PR). | 1,399 | Nothing: it contained no rule. |
| **Total skills** | **868,400** | | | | **~ −121,000 (≈ 14%)** | |
| *SessionStart hooks in `settings.json` (not a skill)* | *~9,300 per session* | | | Cut to ≈ 2,000. | *~7,300 per session* | See § 5, item 3. |

The manager row dominates by design: it is the one skill every manager loads in full, and it is also the one the operator asked to halve. The ~74 KB across the other skills is mostly one duplicate block (28.8 KB) and archived history.
Reload cost matters more than disk size. A fresh manager loads manager (88 KB) + canonical (159 KB) ≈ 247 KB. The proposal takes that to ≈ 200 KB, and every lane drops ~7 KB from the hook.

## 4. The manager skill: from 87.8 KB to ≤ 40 KB

Target met on paper: **87,782 → ≈ 38,000 B (−49,800 B, −57%)** by the per-section plan below. Section sizes are MEASURED; "after" is ESTIMATED from the draft headings I would keep. The result is re-measured with `wc -c` before the cut lands, and I will not claim the half is met until it is.

| section (now → after, B) | what is cut | where each binding rule lives after |
|---|---|---|
| The one job (458 → 458) | nothing | stays |
| **Operating loop** (8,317 → 4,500) | the two long verbatim quotes and the 35-session incident narrative; the REFILL paragraph folds into step 3 | the six steps stay verbatim in this skill, under the heading `## The operating loop`, which `manager-pacing-guard` requires. Verbatim quotes go to `docs/archive/2026-11-06-skills-prune/manager-SKILL.md.pre-prune`. |
| Toolbox (≈1,400 → 1,000) | rows that duplicate loop steps | `scripts/ops/*.py --help` |
| Standing alert subscriptions (5,108 → 1,400) | `ltr-wake`, `mandate_cadence`, `judgement_cadence` recipes → `live-trade-review`; `desk-wake`, `short-hold-wake` → `trading-desk` § 6b | **kept in manager:** subscribe to the ops-flags PR; one marker one lane; a `could_not_*` kind is an incident; never create a session with no `source_url`; no manager-run timers that start a reviewer. |
| Start of session (3,085 → 1,800) | duplicate read-by-role text (also in `CLAUDE.md`, canonical, the hook) | read-by-role pointer to `CLAUDE.md` § Every session; title rule, sweep 2a, ops-flags 2b, console re-watch 2c stay |
| Classifier refusal + lane refusal (2,159 → 900) | the incident narrative and long quotes | rules stay: manager asks the operator to take it out of auto mode; the exact denied action; no rewording; a refusing lane is re-dispatched with an accurate brief, never disguised. Incident text to the archive. |
| Five does / may-not (2,074 → 1,500) | wording | all five "may not" stay (guarded by `check_manager_scope.py`) |
| Budget, output-per-unit, hibernating (3,018 → 900) | practice list; hibernate steps | pointer to pre-diet § Hibernating (already archived). **Kept:** the weekly bar is reported with its reading time; hibernate = arm auto-merge, tell lanes, pick-up reminder, pause routines. |
| **Spawning** (10,884 → 4,300) | landing recipe → one script-printed block (§ 7); recurring dispatches → 5-row table; archive protocol (2.5 KB, duplicates loop step 5 and `lane_reconcile.py`) → 4 lines; No-new-gates → one pointer | **kept:** Tier-1 self-land, Tier-2/3 `landing: hold`; push less push checked; model table and "`create_session` model defaults to the caller's"; provenance and chain of authority; reply channel (`create_trigger` + `fire_trigger` with no `text`); one question per lane and a dollar ceiling; never archive a lane owning an unmerged PR; check status pages first. |
| The checklist (4,650 → 2,400) | edit recipe (the CLI owns its syntax); state-table prose | **kept:** one register; `landed_unproven` ≠ `done`; push then answer; process-not-gates defaults; audit-outcome contract (home); `checklist-readers-guard`. |
| Roadmap loop (2,649 → 800) | cadence detail (already in pre-diet and `roadmap_map.py`) | **kept:** every row carries `roadmap`; closing row sets `writeback`; guard name. Also in `CLAUDE.md`. |
| Weekly planning and cycle (11,833 → 3,000) | Thursday follow-through steps 0–4, surge/throttle items 1–7 and the cycle table move to a new on-demand **`docs/plans/weekly-planning-protocol.md`** (opened by the planning routine's prompt); trigger ids/times removed | **kept in manager:** planning is a dialogue not a report; reviews first then planning Thursday; every review output gets exactly one disposition (a/b/c); WIP limit against `--capacity`; surge = real-money/ML-to-live, throttle = rest, standing never pauses, one ML-research lane through the surge; mid-week real-money arrivals are surge. Each is one sentence + a pointer. |
| Standing authorizations (3,746 → 2,000) | restated mandate list (the file is the source) | **kept:** `config/mandates.yaml` is the source; ping then evidence record; "if the evidence supports it"; a session proposes, only the operator grants; expiry is load-bearing. The **popup classification** (data-settled / data-missing / preference, 1.4 KB) stays whole: it exists nowhere else. |
| Daily brief (1,410 → 400) | six-section table is in `CLAUDE.md` | pointer; "not measured in time", "no cap on section 2", "short, ranked, true" stay as one line each |
| **Work system + daily review** (12,337 → 6,000) | digest-carrier detail (2.2 KB, already in pre-diet), scratch-pad paragraph to 0.5 KB, decision batching, soak contract, ladder | **kept:** the VM computes due and silence is an alarm; review steps 1–6 as one line each with their commands; backlog drain lane daily; orphan count as a number; PUSH + POLL with the depth ≤ 6 rule; subscribe only to ops-flags and own PRs; the **required dispatch block template** (1.4 KB) verbatim. |
| Weekly reset + close-up (6,295 → 2,200) | narrative of what `config/reset_protocol.yaml` and `reset_protocol.py` print; the pipeline heredoc → a `pipeline.py` subcommand | **kept:** claim first (exit 4 = stop), push the claim, restore the check-in cadence, stuck-work sweep with one disposition each, dispatch from `--plan`, one Telegram line; at ~90% every lane writes a resume note, then ONE paused-work pipeline item. |
| Handover (6,453 → 3,200) | the closing checklist copy (the V1–V5 table already is the checklist), long step prose | **kept:** archive first; prepare doc; created by a shallow session; rewire; V1–V5 table; stand down only after V1–V5 pass; link in the last message; ~650k trigger and depth limit. |
| Ladder + closing the session (2,534 → 1,200) | ladder is in `CLAUDE.md` | **kept:** the seven-point close gate; push, publish the page, then ping. |

Binding rules that are **not** moved or shortened: the six loop steps; the five "may not"; the audit-outcome contract; the popup classification; the required dispatch block; V1–V5; the reset claim/exit-4 rule; the two-model rule (`create_session` model explicit; order path = Opus); never question operator authority.

## 5. Proposals outside the skills

1. **`docs/plans/weekly-planning-protocol.md`** (new, on-demand, ~15 KB): the text cut from manager § "Weekly planning". It *relocates* binding text so that the planning routine reads it and no one else does. It is a doc, not a gate, and opens with "Gates this adds or changes: none".
2. **Definition of done in one home.** Put the 5,149 B block in canonical § Generation Discipline as Rule 4 (`+5.1 KB` there), or keep it in `new-strategy` and point the five others at it (`0` added). I recommend **canonical**: the text says it is "binding on every build skill", and the canonical doc is where binding rules live. It needs to pass `canonical-doc-coherence`.
3. **SessionStart hooks** (`.claude/settings.json`, ~9.3 KB per session): replace the long text with the three load-bearing lines (live money; read-by-role pointer; one-register pointer) and `ls .claude/skills/`. Everything else is already in `CLAUDE.md` or the canonical doc. Settings edits are Tier 1 but the hook text is what a session reads first, so I mark it for explicit operator approval.
4. **Verbatim quotes** move to `docs/archive/2026-11-06-skills-prune/` per skill, as the diet did, with a date and a six-word tag left in place.

## 6. Decisions requested (at most four, grouped)

1. **Manager skill halving.** Approve the § 4 plan: cut to ≤ 40 KB, with the planning/surge text relocated to `docs/plans/weekly-planning-protocol.md` and the wake recipes handed to `live-trade-review` / `trading-desk`. *Recommended: yes.* Without it the file keeps regrowing at ~2 KB/day.
2. **Duplicate-block and stale-reference cleanup.** (a) Give the Definition-of-done block one home (recommended: canonical) and remove it from six skills; (b) retire `system-report`; (c) fix the five dead links and the `/system-review` mentions. All mechanical, no rule changes. *Recommended: yes.*
3. **History out of the live skills.** Move `AMENDMENTS.md` (×2), the research-ops changelog section and the quote-heavy paragraphs to `docs/archive/2026-11-06-skills-prune/`; replace the three `performance-review` repeats with pointers; shrink the `settings.json` hook. *Recommended: yes for the archive moves; the hook edit is the one I would like to be explicitly confirmed.*
4. **Merge `doc-freshness` into `close-out`, and `db-setup` into `db-wiring`.** *Recommended: not yet.* Both need a read-in-full lane first, and the saving is under 10 KB. Choose "read-in-full lane" or "leave them".

## 7. Follow-through (audit-outcome contract)

| proposal | row / unit | `due_by` |
|---|---|---|
| Decisions 1–3 once approved: execute the prune as ONE lane per decision, Tier-1 self-land PRs | checklist row `SKILLS-PRUNE` (queued, `roadmap: L-OPS`) | 2026-11-09 |
| Decision 4: read-in-full lane for the two merge candidates | same row, note | 2026-11-13 |
| Verify the 20 skills stamped 2026-09-07 or earlier (a verify pass or retire; re-stamp) | same row, note | 2026-11-16 |
| Is `review_coverage.since_last_build_verification` still produced by anything? (§ 2a) | same row, note; check by reading `scripts/reports/render_system_report.py` callers | 2026-11-09 |
| Emit the landing recipe from a script (`claim_merge_slot.py --print-recipe`, or a `land_pr.py`), and a `pipeline.py` subcommand for the paused-work item | same row, note (Tier 1, tooling) | 2026-11-13 |
| Re-measure the manager skill after the cut (`wc -c`) and set a size note so regrowth shows | same row, `observe` | 2026-11-13 |

Not run: the CI guards against the *proposed* edits (nothing is edited). The doc itself is `unknown` status, as are the other audit docs.
