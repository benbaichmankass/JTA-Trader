---
name: health-review
description: The WEEKLY technical health review of the LIVE ICT trading system (Wednesday 19:11Z after the weekly reset, feeding Thursday planning). Four layers per docs/reference/llm-analyst-skill-design.md. PRIOR CALLS re-runs and grades the last review's calls first. CHECKS is a fixed list of script/diag-route must-checks, each with its population and a read-state, so nothing is skipped and a null never reads as 0. ANALYSIS is LLM reasoning over wide context: the trend across the last 4 reviews, cross-signal correlation and competing-hypothesis root cause. DECISIONS ranks calls by money and risk, each with a probability and a pre-registered check. Covers services, deploy state (merged ≠ deployed ≠ observed), broker reachability, signal→order→fill→close plumbing, close reasons and orphans, DB validity, consumed-input freshness, alert delivery, research and learning pipeline liveness, saturation, security and new-work compliance. Every call is fixed, or becomes a row, unit or pipeline item. Use when the manager dispatches a HEALTH-REVIEW lane, or the operator says "/health-review", "run the health review". NOT trade scoring (/performance-review), NOT model quality (/ml-review), NOT control testing or design criticism (/weekly-audit), NOT a code or security review.
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /health-review — is the machine running, and is it getting better or worse?

> **Redesigned 2026-10-28** (lane `SKILL-DESIGN-SYSTEM`, operator directive ~07:15Z: every weekly review is rebuilt
> on researched practice, avoiding both *too loose* and *too scripted*). It follows the shared two-layer pattern
> in [`docs/reference/llm-analyst-skill-design.md`](../../../docs/reference/llm-analyst-skill-design.md)
> (lane ANALYTIC-SKILL-DESIGN). If that file is not on main yet, this skill is self-contained.
> The 923-line predecessor is kept verbatim at
> [`docs/archive/2026-10-28-skill-redesign/health-review-SKILL.md.pre-redesign`](../../../docs/archive/2026-10-28-skill-redesign/health-review-SKILL.md.pre-redesign).
> Its transport notes are carried below. Its retired parts (the coordination board, sprint-log review, the
> weekday rotation, the sibling-skills essay) were dropped on purpose; see § Design basis.

**This is QA of the live system, not a report.** You hunt for what is broken or getting worse, root-cause it,
and fix what is Tier 1 this session. Tier 2/3 goes to the operator with the exact change. A finding you log
without a root cause and a closing observation is a post-it note, and that is a review failure. Pull live state
yourself through the diag relays. Never ask the operator for a snapshot, and never ask scoping questions: the
scope is this file.

## The shape — four layers, never merged ([shared pattern](../../../docs/reference/llm-analyst-skill-design.md) § 1)

| layer | what | budget |
|---|---|---|
| **0. Prior calls** | re-run the check each of last review's calls named; grade it | ~10 % |
| **1. CHECKS** | the fixed H1–H16 list below: scripts and diag routes, each with population, window and read-state | ≤ 35 % |
| **2. ANALYSIS** | material questions, competing hypotheses, discriminating tests, cross-signal causes, the hunt | ≥ 35 % |
| **3. Decisions** | each call is a fix, row, unit or pipeline item with a pre-registered check; plus the bounded open-set walk | ~ 20 % incl. close-out (reserve it first) |

If the budget runs short, cut the open-set walk (§ 3c) and state how many items were left. Never thin Layers 0 or 2.
A run that executed every check and analysed nothing has failed the *too scripted* way. A run that analysed without
the checks has failed the *too loose* way.

## Step 0 — window, history, instruments

1. **Windows, every run.**
   - *This window*: from `reviewed_at` of the newest file in [`comms/reviews/health/`](../../../comms/reviews/health/)
     to now (7 d if there is none; say so).
   - *Medium*: the last 4 review JSONs.
   - *Lifetime*: wherever a check's series exists (snapshot history, `comms/research/health/`, `pipeline.py
     --stats`).

   Cover the whole window. A pull that reaches only part of it is recorded as partial, with the covered span.
2. Read the newest `docs/reviews/*-weekly-audit.md` (it runs 40 min before you; its C8 may have re-tested your
   last verdicts).
3. `git fetch --deepen=2000 origin` if the clone is shallow.
4. Self-test before trusting a green: `python3 scripts/ops/pipeline.py --self-test`,
   `python3 scripts/research/research_slo.py --self-test`, `python3 scripts/ops/system_invariants.py --self-test`.
   A failing self-test makes its checks `could_not_look`, and the failure is a finding.

## Layer 0 — PRIOR CALLS (first, before you form any view)

For every call and every `concern`/`watch` in the previous review, re-run the check it named (or the closest check
that answers it) and grade it:
- `hit` / `miss` / `unresolved` / `void`, per the shared pattern (`result`, plus `action_happened`);
- plus the state of its action: `closed+detector` · `closed-no-detector` · `moving` · **`stalled`** (no state change
  ≥ 7 d).

A call `stalled` across **≥ 2 reviews** is a follow-through bug. Say why it is not closing (no owner? tier-blocked?
too big? nobody reads the row?) and decide in Layer 3: fix now, put the exact decision to the operator, re-scope,
or kill with a reason. Re-filing it is not an option. Re-run the check; do not re-argue the call. Record
`prior_calls_scorecard`, with counts and a Brier score once ≥ 10 calls have resolved (`INDETERMINATE` below that).

## Layer 1 — CHECKS (fixed; every one runs, every one is recorded)

Each check writes one `checks[]` entry:
`{id, status: ok|watch|concern|could_not_look, value, population, window, evidence, prior: [last 4 values], coverage}`.

- **Read-state rule.** `could_not_look` means we did not see it. It carries the reason, it is never an
  all-clear, and it is itself a finding about the instrument. A count of `0` must name its denominator and,
  for the money checks (H3, H4, H6), a positive control: show the probe finds a known positive. Render a
  missing field as `—`, never `0`.
- **Read the row, not the label** (canonical § "The row you are reading outranks the label in it"). `pnl` is not
  the account's money, and `exit_reason` is not the exit mechanism without `exit_price`. `journalTrust:
  no_record` is not "trusted". Check what wrote a column with `scripts/ops/column_provenance.py trades.<col>`.
- **Never quote a previous run's number as this run's.** Re-run.

| id | question | instrument (exact) | population / denominator | concern when |
|---|---|---|---|---|
| H1 | Are the services up and the heartbeat fresh? | diag `status`, `services`; `api/bot/health/latest`, `api/bot/health/history?hours=168` | the canonical units in `src/web/api/routers/diag.py::_CANONICAL_UNITS` | a unit is not active, the heartbeat is stale during a session, or the snapshot disagrees with your own pull (that means the generator is broken) |
| H2 | **Merged ≠ deployed ≠ observed.** Is the VM running what main says? | running SHA from `status` vs `git rev-parse origin/main`; `git diff --name-only <running>..origin/main -- src config`; `python3 scripts/ops/verify_running_roster.py` (layer 4 vs 5) | files under `src/` + `config/` changed since the running SHA | src/config drift with no pending restart, roster disagreement, or two surfaces disagreeing on the SHA |
| H3 | Is every declared-live broker account reachable? | diag `exchange_positions` (`positions: null` = could-not-read); `runtime_logs/account_reachability_alert_state.json` via `log_file`; `api/bot/accounts/balances` `api_ok` | accounts with `mode: live` in **re-parsed** `config/accounts.yaml` on a probeable venue, plus the prop accounts by their own route (state the ones with no probe as `could_not_look`) | any live account down. This is a standalone flag and a `high` ping, never a body line |
| H4 | Is every open position protected and reconciled? | `python3 scripts/ops/system_invariants.py --payloads <dir>` (stems `ib_open_orders`, `bybit_open_orders`, `exchange_positions`, `positions`, `journal_trades`, `exit_loop_health`) | open positions × accounts; (account, symbol) pairs journal⇄venue | a naked, over-covered or target-less position; journal⇄venue qty mismatch |
| H5 | Does signal → package → order → fill → close flow? | diag `audit?limit=600` (page with `journalctl?unit=ict-trader-live.service&since=&until=` to cover the window), `journal?table=order_packages`, `journal?table=trades` (page past 100) | actionable signals in the window; enabled strategies in `config/strategies.yaml` (shadow legs still emit `*_eval`) | a signal with no package or logged refusal; an enabled strategy silent > 1 h of its session; repeated `failed_exchange`/`failed_risk_gate` on one symbol; monitor-tick gaps |
| H6 | Did every close end in TP / SL / strategy-close, and is no orphan resting? | the trades pull from H5: `exit_reason` + `exit_price`; `log_file?name=orphan_events`; Data Explorer `trades` with `setup_type=adopted_orphan` | closed rows in the window, by account class | any reconciler-driven, watchdog or orphan close (a bug to root-cause this session), or an orphan unreconciled across the window |
| H7 | Are DB values valid and the write path intact? | `scripts/check_db_integrity.py` (INV-1..5, `recent_count` vs `total_count`); recency + monotonic totals from the journal pulls | rows written in the window | `recent_count > 0`, a table total that dropped, `closed_at < opened_at`, a closed row missing `pnl`/`exit_reason` |
| H8 | Are the inputs the trader **consumes** fresh, not just their producers? | `python3 scripts/macro/check_producer_liveness.py` (the consumer-side checks) | readers in `src/` and the files they open (state how you found them) | a consumed artifact stale past its cadence |
| H9 | Did alerts reach a human? | AlertsQueue drain in the audit tail; `delivered.telegram` in `comms/research/health/<date>.json` runs | trip events and alert runs in the window | an alert queued but not drained, or `delivered.telegram: false` |
| H10 | Is the research pipeline flowing? | every `comms/research/health/<date>.json` in the window (SLOs in `scripts/research/research_slo.yaml`) | days × SLOs; runs (gap > 4 h means the monitor was down) | a red SLO with no disposition, a missing day, a run gap |
| H11 | Is the learning pipeline alive? (service + flow, not model quality) | `trainer-vm-diag-request`: `systemctl is-active/is-enabled ict-trainer.service ict-trainer.timer`, `systemctl show ict-trainer.service --property=ExecMainStatus,ActiveEnterTimestamp`; newest cycle, newest dataset build and newest trained model timestamps | cycles scheduled vs ran in the window | the timer is dead, a non-zero exit, or no dataset built / model trained in the window. **"Rows recorded but never trained" is a red flag**; hand the detail to `/ml-review` |
| H12 | Saturation: disk, memory, CPU, WAL — and the trend | `status` `vm_health`; snapshot history | both VMs | free disk on a trend to cross 10 % within 14 d (project it from the last 4 values), memory pressure, a WAL ≫ main DB |
| H13 | Any breach signal since the last review? | `mcp__github__run_secret_scanning` (it now needs a `files` argument; if it cannot run, `could_not_look`); collaborators and deploy keys; `.github/workflows/**` changes by actor; `python3 scripts/ops/ssh_auth_sweep.py --since <ISO> --until <ISO> --trainer-ip <trainer>` (unit `ssh.service`, never `sshd.service`; one plain pull covers only ~1.5 h) | sources swept × the window covered | a confirmed breach or exposed credential (standalone flag, `high` ping). Match each non-trainer accept to a workflow run (Health Snapshot produces 2 every ~6 h) |
| H14 | Did new work respect the tiers? (risk-based, not every commit) | `git log origin/main --since=<window> --format='%h %s' -- config/ src/runtime/ src/core/ src/units/accounts/ deploy/ .github/workflows/ scripts/ops/*.sh` and the PR of each | the commits touching Tier-2/3 paths (state the total commit count beside it) | a Tier-2/3 change merged with no recorded operator OK, a new default-off `*_ENABLED` gate on a required capability, a mode auto-flip, or a "verified/deployed" claim your H1/H2 pulls contradict |
| H15 | Is the open set being driven? | `python3 scripts/ops/pipeline.py --gate` and `--stats`; checklist rows this review owns | the gate set (unrouted ∪ closed-owner ∪ high-severity due items), with `due`, `excluded` by reason | gate items untouched; unrouted count or oldest-unrouted age rising |
| H16 | Is a soak at its gate? (surface, don't decide) | `api/bot/shadow/stats`, `api/bot/strategies/{name}/review`, `docs/claude/work/SOAKS.json` | soaks in flight | a met gate unactioned across ≥ 2 reviews. Route it to `/ml-review` or `/performance-review`. A soak is 1–2 clean trades (OPERATING-PLAN § 2), never a date |

## Layer 2 — ANALYSIS (reasoning, not restatement)

The checks say *what*. The analysis says **why, how bad, and whether it is getting worse**. Never paraphrase the
check table; write what the checks *together* imply. Follow the shared prompts (pattern § 3). For this review:

**2a. Read wide first.** Before forming a view, read:
- every check's series across the windows;
- the `journalctl` errors of the window;
- the open rows and items that name a failing subject (**search before you call a finding new**);
- the last runs' *checks and calls*, not their conclusions.

**2b. Trend, not snapshot.** Name every series moving the wrong way for ≥ 2 consecutive reviews, even while it is
under its threshold, and project it (*at this rate it crosses X on <date>*). A slow drift is the incident you can
still prevent.

**2c. Choose 3–7 material questions by money and risk, not recency**, and for each:
1. write ≥ 2 hypotheses, one of them always *noise or expected variation*;
2. say what each predicts that the others do not;
3. run the discriminating query now, or file it with its rule written first;
4. record what was eliminated and by what evidence;
5. name the surviving cause at the level of a file, line, config key, unit or job, with a probability.

Blameless: name the mechanism, not who.

**2d. Correlate across signals.** Separate symptoms (what is broken) from causes (why). A cause at one layer is a
symptom one layer down. Line up the timestamps of the window's anomalies, and ask whether one cause explains
several. One mechanism behind N symptoms is **one** structural call, not N.

**2e. Hunt one thing no check covers.** Look at one of these:
- new error signatures in `journalctl` vs last week, by count;
- a surface that reports `ok` with no input that could falsify it;
- a declared capability with zero call sites.

Write down what you looked at. If nothing surprised you, say what you checked. Count comparisons: scanning 30 series
flags ~1.5 by chance.

**Neutral framing.** There is no quota of findings. "Nothing material changed" is a valid conclusion only when the
falsification attempt behind it is shown.

## Layer 3 — DECISIONS (every call ends somewhere)

**3a. Rank by money at risk.** One `calls[]` list:
1. real money;
2. prop;
3. the demo floor (`bybit_1` / `alpaca_paper` / `ib_paper`);
4. research and learning liveness;
5. observability;
6. docs.

Each call carries:
- `claim` (falsifiable);
- `evidence` (the command and its output path);
- `population`, `trend`, `cause`, and `p` (a probability, MEASURED or INFERRED);
- `blast_radius` and `tier`;
- **`check {command, rule, resolves_when}`**: pre-registered, so next week's Layer 0 can grade it;
- **`ending`**, exactly one of:
  - **fixed**, in this PR (state merged / deployed / observed);
  - **row**: `checklist.py add HEALTH-<YYYYMMDD>-<slug> … --tier N`, with a `roadmap` ref;
  - **unit**: `research/queue/`;
  - **pipeline**: `PI-…` via `scripts/ops/pipeline.py`, with `due_when` + `origin.rerun`;
  - **no action, because …**, with the probe.

"Noted", "monitor" and "investigate" with no owner, n or check are not endings. A finding filed twice is one call
with a `stalled` grade.

**3b. Premortem each Tier-2/3 call.** Assume it made things worse in three months and say why. Tier-2/3 calls carry
the exact change and go to the operator. Fix Tier 1 now.

**3c. Drive the open set (bounded).** Walk the H15 gate set. For each item:
- re-validate it against what you already pulled;
- disposition it `resolved` / `fixed_now` / `invalid` / `kept_open` (with this run's observation and the blocker);
- write it back with `scripts/ops/pipeline.py`: never by hand, append-only, `terminal_reason` to close.

Record `backlog_coverage`: `open_at_start` = the gate set, `due_total`, `excluded`, the sources, `count_untriaged`. If
the budget ends the walk, stop there and state the count. Never bulk-redate.

## Output

1. **`comms/reviews/health/<YYYY-MM-DD>-health-review.json`** per
   [`comms/schema/health_review_response.template.json`](../../../comms/schema/health_review_response.template.json).
   It carries the four blocks:
   - `prior_calls_scorecard`
   - `checks[]`
   - `analysis{trend, questions[], correlations[], hunt, surprises}`
   - `calls[]`

   plus `backlog_coverage`, `security_check`, `new_work_compliance`, `soak_decisions_due[]`, `overall_assessment`,
   `recommended_action` and `operator_attention_required`. `overall_assessment` is `healthy` (all ok), `caution`
   (≥ 1 watch) or `investigate` (any concern). The newest `reviewed_at` anchors next week's window.
2. **`docs/reviews/<YYYY-MM-DD>-health-review.md`**, **one page (≈ 60 lines), the Thursday-planning read**, in the
   shared order:
   - `# Health review <date> — <one sentence: what most affects money/risk now>`;
   - `## 0. Prior calls`: graded, with every `stalled` named;
   - `## 1. CHECKS`: one line per H-id (status · value · population · prior), with `could_not_look` listed;
   - `## 2. ANALYSIS`: trend lines, then per question: hypotheses · test · survivor · p; then surprises;
   - `## 3. Decisions`: ranked, with tier, check and ending id;
   - `## 4. Not done`: what was not run or read, and why.

   Doc-status line on top. Register the page in `docs/DOCUMENT-INDEX.md` the way
   `docs/reviews/2026-10-19-weekly-audit.md` is.
3. **One self-landing PR** (§ Landing). Then a **ping**: open a `system-action` issue with the lines
   `action: send-ping`, `target: claude`, `priority: normal|high`, `message: /health-review — <grade>: <n> concerns,
   <m> watches, <k> stalled calls; <top action>`. Only the **first line** of `message:` is sent, ≤ 200 chars. Open
   the next system-action issue only after the previous one closes.
4. **Report to the manager once**, in 5 lines, via `create_trigger(persistent_session_id=<manager>)` +
   `fire_trigger`, no `run_once_at`.

## Transport (carried from the predecessor; read `diag-data` and `git-actions` for the mechanics)

- Try `scripts/ops/diag_fetch.sh '<path>'` first; on exit 3, use the relay.
- **Batch every live-VM path into ONE `vm-diag-request` issue** (a JSON array body). Each relay issue is a billed
  Actions job. Paths under `/api/bot/…` need the `api/bot/` prefix; the bare `health/latest` returns
  `fetch_failed`.
- `audit?limit=600` covers ≈ 6 h. Page the rest of the window with `journalctl … since/until`, and say what was
  summarised rather than enumerated.
- The trainer VM is reached only by `trainer-vm-diag-request` with a `cmd: |` block.
- On curl exit 7, fire `vm-web-api-recover` and retry once. If the relay is still down, every live check is
  `could_not_look`, `operator_attention_required: true`. Still do Layer 0, the open-set walk (3c) and H14 (they are repo-local), and still
  land and ping. Never synthesise a live finding without evidence.

## Landing

1. Commit the JSON, the page, the DOCUMENT-INDEX line, the rows/items and any Tier-1 fixes.
2. Run `python3 scripts/ops/land_pr.py --held-by <your session id> --why "<tier judgement>" --verify`. It writes
   `.github/pr-landing/<slug>.json`, `.github/pr-automerge-requests/<slug>.txt` and the merge-slot claim. If it
   computes a **hold**, the manager merges; say so.
3. Run the guards locally: `python3 scripts/ci/run_guards.py --base-ref origin/main`.
4. Push, open the PR, and drive it green.
5. Row `HEALTH-REVIEW-<YYYYMMDD>`: `landed_unproven` with the closing observation, then `done` once merged and
   observed.

## Never

Edit `src/`, `config/` or any live path; write `comms/claude_strategy_scores.jsonl`; close another review's
rows; ask the operator to paste, SSH or download; report session length; resurrect a retired register.

## Design basis (2026-10-28) — why this shape

**Diagnosis of the last 4 runs** (`comms/reviews/health/2026-10-{09,17,21,24}-health-review.json`):

- **The gate was never met.** Items re-validated: 4/76, 5/110, 0/256 and 8/369. The skill demanded a full walk
  that no $6 lane could do, so every run spent its budget on the walk or abandoned it. The 10-17 note:
  *"A $6 lane cannot re-validate 110 items against live state."*
- **Checks were skipped silently, or sampled.**
  - 10-17: `research_pipeline: could_not_look — not read this run`; `trainer_service: skip — not pulled`.
  - 10-21: no security sweep and no orphan check.
  - 10-24: the security sweep covered ~3.5 h of a 3-day window; `run_secret_scanning` did not run.
- **The window was this week only.** No run compared itself to the previous one, so a slow trend was read as
  a new event each week: disk 93 % (10-17), then 26.7 % free (10-24), each graded on its own.
- **Findings became post-it notes.** Most stayed `routed` 7–11 days later:
  - `PI-20261017-VSMHZYHF-0001` and `PI-20261017-VMDGITZI-0002` (disk);
  - `PI-20261021-20261021-0001` (false URGENT liveness);
  - `PI-20261021-41BO5V65-0001` (SHA disagreement).

  The disposition was correct (filed) but nothing graded whether they closed.
- **What went well.** 10-21 root-caused two real bugs to a code line (a `safe_place_order` with 0 production
  callers; the watchdog counting side-filtered SELLs). That is the depth 2c asks for every week.
- **Dead weight.**
  - The coordination board (retired 2026-09-21; 10-24 flagged it).
  - Sprint-log review: 0 sprint logs since 2026-05-19.
  - A weekday rotation that now always lands on Wednesday.
  - 923 lines of instructions on a $6 budget.

**Practice adopted** (tags: ACAD academic · PRAC practitioner · VEND vendor):

- **Symptoms vs causes, the four golden signals, alert on symptoms** — Google SRE book ch. 6
  ([sre.google](https://sre.google/sre-book/monitoring-distributed-systems/)) — PRAC. Basis for 2d and H12.
- **Trend over snapshot; compare each metric to its history on a weekly cadence** — AWS Well-Architected
  OPS11-BP07 / REL06-BP06 and AWS's weekly operational review
  ([docs.aws.amazon.com](https://docs.aws.amazon.com/wellarchitected/2024-06-27/framework/ops_evolve_ops_metrics_review.html)) — VEND. Basis for 2b.
- **Untracked postmortem action items get forgotten; deeper review when failures mirror earlier incidents** —
  SRE Workbook ch. 10 ([sre.google](https://sre.google/workbook/postmortem-culture/)) — PRAC. Basis for Layer 0
  and the pre-registered `check`.
- **Error budgets / SLOs decide when reliability work preempts features** — SRE Workbook "Implementing SLOs"
  ([InfoQ summary](https://www.infoq.com/news/2018/07/google-explains-sre)) — PRAC. Basis for H10's SLO
  reading.
- **Knight Capital (SEC 2013): 97 automated emails flagged the error pre-open and nobody acted; reliance on
  human monitoring; no pre-market-access check; earlier incidents fixed narrowly without root cause** —
  [SEC press release 2013-222](https://www.sec.gov/news/press-release/2013-222) — PRAC/regulatory. Basis for
  H9, H2, H4 and 2c.
- **Market Access Rule 15c3-5: a documented, regular review of control effectiveness, with an inventory of the
  controls reviewed** — [FINRA 2026 oversight report](https://finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/market-access-rule) — PRAC/regulatory.
  Basis for `checks[]` being an inventory with populations.
- **BCBS 239 accuracy / completeness / timeliness of risk data** —
  [summary](https://en.wikipedia.org/wiki/BCBS_239) — PRAC/regulatory. Basis for H7 and H8.

Pattern and anti-patterns: [`docs/reference/llm-analyst-skill-design.md`](../../../docs/reference/llm-analyst-skill-design.md).
