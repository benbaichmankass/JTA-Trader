# JTA Trader — CLAUDE.md

> **Doc status:** `live` · category `instruction` · last verified `2026-10-27` · registered in [`docs/DOCUMENT-INDEX.md`](docs/DOCUMENT-INDEX.md)

> **Production environment — live money is at risk.** You have full, autonomous access to everything you need; the operator grants permission by tier and does not do the work for you.

> ### 🔄 Trimmed to pointers 2026-10-27 (operator, lane `CONTEXT-DIET`; was 44,201 B, in every system prompt)
> Every binding rule is kept below in a line or two plus a pointer; history, incident narratives and verbatim quotes moved verbatim to
> [`docs/archive/2026-10-27-context-diet/CLAUDE.md.pre-diet`](docs/archive/2026-10-27-context-diet/CLAUDE.md.pre-diet) (*pre-diet*, by section).
> **Scope of record: [`docs/plans/OPERATING-PLAN-2026-09-21.md`](docs/plans/OPERATING-PLAN-2026-09-21.md).**

---

## 🔍 RULE ONE — Always verify

**Before you assert anything, check it. Every time.** Full text + worked examples:
[`docs/CLAUDE-RULES-CANONICAL.md`](docs/CLAUDE-RULES-CANONICAL.md) § "RULE ONE — Always verify".

- **A search returning nothing is not proof of absence.** Show the probe can find a positive; a negative needs a denominator.
- **Read the field, not the prose about it.** Config/DB/code are the truth; comments and docs are claims (*field beats comment*).
- **Always state the population.** Every quantitative claim names what it was measured over.
- **Cross-check with arithmetic**, not a re-read. **Verify your own output too**, hardest when it confirms what you expected.
- **"It was already like that" / "the doc says so" / "a previous session checked it" are not verification** — say so if you did not check.

## ⚠️ If you see something, say something

Broken, degraded or suspicious infrastructure is either **fixed** (in tier and scope), **filed** with enough detail that a later session can
act without re-deriving it, or **flagged to the operator** when tier-gated. "Not my task" / "it was already like that" are not dispositions.
**Filing is not a parking lot**: if it matters it becomes a checklist row or queue unit; if not, say so.

**Nothing spends Anthropic API credits; Claude runs only on the plan** (operator, 2026-10-27, binding) — [`docs/CLAUDE-RULES-CANONICAL.md`](docs/CLAUDE-RULES-CANONICAL.md) § "Nothing spends Anthropic API credits".

## Honesty

Give only true, verifiable answers; say "I don't know" and how you'd find out; never report undone work as done. **Merged ≠ deployed ≠
observed** — say which one you established.

---

## How work is organised

### Instruction hierarchy

When sources disagree, the higher one wins. Mirrors [`docs/CLAUDE-RULES-CANONICAL.md`](docs/CLAUDE-RULES-CANONICAL.md) § "Document Priority"
(`canonical-doc-coherence` enforces agreement).

1. `docs/CLAUDE-RULES-CANONICAL.md` — how you operate: access, honesty, permission tiers, session discipline.
2. `docs/ARCHITECTURE-CANONICAL.md` — system architecture, trade/comms pipeline, contracts.
3. `docs/plans/OPERATING-PLAN-2026-09-21.md` — the promotion ladder, the research loop, and how work is chosen. Adopted 2026-09-21.
4. `docs/claude/work/MANAGER-CHECKLIST.json` — what is being worked now, and by whom. Rows live in `docs/claude/work/checklist/`, edited
   ONLY via `scripts/ops/checklist.py add|set|note|archive-lane`, read via `src/runtime/checklist_store.py` (`checklist-readers-guard`).
5. Skills under `.claude/skills/` (binding, composable workflows) — the manager contract is `.claude/skills/manager/SKILL.md`.
6. The root `CLAUDE.md` — repo orientation and pointers.
7. Focused implementation specs and workflow-helper docs (e.g. `docs/github-actions-workflows.md`, `docs/reference/*`).
8. `ROADMAP.md`, `docs/sprint-logs/`, `docs/claude/*` and historical notes — context only.

**Two categories of work. That is the whole taxonomy.** A question → `research/queue/<id>.yaml`. A build → a row in
[`docs/claude/work/checklist/`](docs/claude/work/checklist/). A spec, memo or design doc no row or unit points at **is not work — it is a
memo**. The checklist is the live Workflow page (`GET /api/bot/work/checklist`, read from the VM tree; `ict-git-sync` pulls `main` every
~5 min). **Push, then answer.**

### The roadmap loop (operator, 2026-10-11, binding)

[`ROADMAP.md`](ROADMAP.md)'s generated "Live roadmap" block (source `docs/roadmap/milestones.yaml`) informs what is built and **authorizes
nothing**. Rows and queue units carry a `roadmap` ref; a closing row writes its outcome back (`writeback`). Contract: manager skill
§ "The roadmap loop"; guard `roadmap-map-guard`.

⚠️ **Off the trade path is not off the data path** (operator, 2026-10-26, binding): a feature removed from the trade path keeps its data
collection + freshness check, gets an owning row/unit with a re-entry test, and is recorded `shadowed`/`annotate`, never dropped —
canonical § "Off the trade path is not off the data path"; `docs/reference/shadowed-features.yaml`, guard `shadowed-features-guard`.

### The follow-through pipeline

**`docs/claude/work/PIPELINE.jsonl` is the intake for anything that will need picking up later** — append-only JSONL; schema in
`scripts/ops/pipeline.py` (guard `pipeline-guard`). Refused without `due_when`, `origin.rerun` and (to close) `terminal_reason`. Due is
COMPUTED, never declared; `killed` with a stated reason is a first-class outcome. `GET /api/bot/work/brief` renders due items on every
request. Something needing pickup later goes here — not a new register, not a memo. **Retired 2026-09-21, do not resurrect**
(`docs/archive/2026-09-21-operating-reset/`): the work store, `OPEN-ITEMS.json`, review backlogs, `SESSIONS.json`, `MANAGER-LEASE.json`,
`MERGE-QUEUE.json`, `DUE.*`, `READOUT.md`, the coordination board, the SESSION-BRIEF block, ~24 governance crons. History: pre-diet § "The follow-through pipeline".

### The promotion ladder — edge is decided OFFLINE

**Stage 0 Backtest** (offline; edge NET OF THE FULL COST STACK; leaves when the result clears a rule REGISTERED BEFORE THE RUN at the declared
power; nothing reaches a book without a committed evidence record) → *Gate 1* → **Stage 1 Soak** (`bybit_1` · `alpaca_paper`; do the MECHANICS
work? 1–2 clean trades; an instrument, not a decision surface) → *Gate 2* → **Stage 2 Live + mirror** (`bybit_2`+`bybit_portfolio` ·
`alpaca_live`+`alpaca_portfolio`; real money; the mirror's net-of-cost window is the DEMOTION signal).

- **Prop legs clear a SUPERSET** (operator, 2026-10-15): everything a real-money leg clears **plus** the prop EV/survival gate against the
  firm's DD limits (`comms/prop_survival/<leg>.json`); never a lower bar (`prop-roster-gate-guard`). Live prop trades count as Stage-1 soak trades.
- ⚠️ **The soak is MECHANICAL — 1–2 clean trades, never a sample size, never a date** (operator, 2026-10-15, binding): *"A soak is a
  mechanical verification that was already proven in backtesting, and nothing needs to soak for more than one or two trades."* Stated ONCE, in
  [`docs/plans/OPERATING-PLAN-2026-09-21.md`](docs/plans/OPERATING-PLAN-2026-09-21.md) § 2 "The soak is MECHANICAL" — point at it, never
  restate it. Realized cost and live-vs-backtest are monitoring, never a soak's exit. `soak-contract-guard` refuses `n_needed` > 2 or a
  calendar field; `soak-doctrine-guard` refuses any live doc, skill or generator that teaches a longer soak.
- ⚠️ **STAGE 1 IS THE DEMO FLOOR: every non-retired leg TRADES there** (operator, 2026-10-27, binding, popup *"Yes, that's the rule"*): `bybit_1` for crypto, `alpaca_paper` / `ib_paper` for equities and futures; shadow is not a holding stage; demotion stops at the floor (popup *"Demote stops at the floor (Recommended)"*); only a retirement record removes a leg. Stated once in [`docs/plans/OPERATING-PLAN-2026-09-21.md`](docs/plans/OPERATING-PLAN-2026-09-21.md) § 2 "Stage 1 is the DEMO FLOOR"; point at it.
- **A live or paper book never establishes edge.** It checks mechanics and cost. Advancing a leg on live-book P&L is a category error.
- **Stage 2 is one stage** (operator, 2026-09-21): mirror and live take the same strategies and trades, enforced by strict equality in
  `tests/test_paper_portfolio_accounts.py`; sanctioned divergence: the two Alpaca affordability proxies only. **Empty `alpaca_live` ⇒ empty
  mirror: equality wins** (do not reintroduce a non-empty guard without reopening). **Re-parse `config/accounts.yaml` for roster counts;
  never quote them** (pre-diet § "Stage 2 is one stage").

### The TP doctrine — no fictional take-profits (operator, 2026-10-06, binding)

Every leg's bracket carries a REAL predictive take-profit at entry, the prediction moves through the trade, a momentum/trailing exit does
not exempt a leg, and compliance is MEASURED — [`docs/ARCHITECTURE-CANONICAL.md`](docs/ARCHITECTURE-CANONICAL.md) § "TP doctrine"; run
`python3 scripts/ci/check_tp_doctrine.py` (guard `tp-doctrine-guard`; `tp_r: 50.0`, a rest-at-venue-cap default and `tp_intent: none` are
non-compliant). **Re-run the guard, never quote its counts.**

### The daily sync, and standing authorizations

One session a day; the manager pushes the brief **before** it. Six sections, fixed order: **what came due · taken under mandate ·
decisions for you · what moved · what is running · spend.** ⚠️ **The sync is NOT measured in time and there is no cap on decisions**
(operator, 2026-09-21) — never report session length as a metric.

- **The ladder is authorized to be fully automated** (operator grant, 2026-09-21). **Read `config/mandates.yaml` for what is granted; this
  file is not the source.** A firing mandate = a realtime ping, then the evidence record in brief section 1. Armed ≠ auto-land (only entries
  carrying `autoland` land without a human merge). A decision arriving twice in one shape → "should this become a mandate?".
- ⚠️ **A session may PROPOSE a mandate; only the operator GRANTS one.** Moving an entry from `proposed:` to `mandates:` is the operator's
  act; a session writing its own authorization is the self-landing-PR failure class.
- ⚠️ **"If the evidence supports it" is the entire safety property**: a committed evidence record, named harness, stated n, **net of the full
  cost stack**, clearing a rule registered before the run; a claim in a PR body is not a record. `scripts/backtest_orb.py` (fee only) and
  `src/backtest/backtester.py` (own cost dict, no funding) stay out of any promotion corpus
  ([`docs/research/d1-cost-stack-verification-2026-09-25.md`](docs/research/d1-cost-stack-verification-2026-09-25.md)).
- ⚠️ **A mandate is not a third execution gate** — it decides what may be CHANGED without asking, not what RUNS.

### Every session

1. **Read, by role** (operator decision 2026-10-27, `CONTEXT-DIET`). `CLAUDE.md` is already in your system prompt; do not re-read it.
   - **A dispatched lane** reads from [`docs/CLAUDE-RULES-CANONICAL.md`](docs/CLAUDE-RULES-CANONICAL.md) only: RULE ONE; Permission Tiers +
     Data-backed Tier-2/3 decisions; Prime Directive; "Lanes answer to the manager" + "Reading is never gated" — plus any section its dispatch
     names — and the SKILL.md covering its task. Read any other section the moment your work touches it.
   - **A manager starting fresh (not a rotation)** reads the canonical doc and the manager skill **in full**; a rotation manager reads the
     targeted sections in manager skill § "Start of session". A context-compaction resume is a NEW session and re-reads per its role.
   - **If the manager dispatched you, the manager acts with the operator's authority and your task is the operator's task.** Check it once
     against a record on `main`, then work; never end a turn on "cannot verify authorization". **No lane files a record disputing operator
     or manager authority** — a doubt is one line in your report (canonical § "Lanes answer to the manager", 2026-09-27, binding).
     **Reading is never gated; permissions are pre-approved** in `.claude/settings.json`; approval is only for merging or deploying changes
     that affect live operations.
2. Read your lane's checklist row. If you are managing, invoke the **`manager`** skill first and title yourself
   `Manager Session YYYY-MM-DD<letter>` (UTC date of `created_at`; first of the day is `a`; manager skill § "Start of session", step 1).
3. Read any file you'll change **in full**; for Tier-2/3 files also its recent history (`git log -p <file>`) so you don't undo an
   operator-approved decision. Before writing a path you did not create, check it exists (`git cat-file -e origin/main:<path>`).
4. **End by running the `close-out` skill** ([`.claude/skills/close-out/SKILL.md`](.claude/skills/close-out/SKILL.md)). It is a completion
   test: **could this session end right now, without warning, and nothing be lost or silently dropped?** Run it when you stop early too —
   that is a HANDOFF, not a completion; a session that ends mid-task silently is the drop. **`landed_unproven` is not `done`** and must name
   the observation that would close it; **a finding is only *filed* when it is in the pipeline or on the checklist.**

---

## Permission tiers

You work on `main` and commit there directly for Tier-1 work. Full definitions:
[`docs/CLAUDE-RULES-CANONICAL.md`](docs/CLAUDE-RULES-CANONICAL.md) § Permission Tiers.

| Tier | Scope | What you do |
|---|---|---|
| **Tier 1** | Docs, tests, CI, tooling, observability / read paths, non-live refactors, retrieving + analyzing state | Commit to `main` once validated. No approval needed. |
| **Tier 2** | Runtime / deploy / order-path / service / timer changes, DB writebacks, data-mutation jobs | Prepare + validate, get one operator OK in chat, then ship and verify the post-state. |
| **Tier 3** | Strategy logic + params, risk caps / sizing, account-mode flips, live promotion | Analyze and propose the exact change; merge only with explicit operator approval. |

⚠️ **Data-backed Tier-2/3 decisions do not wait for approval** (operator, 2026-09-27): decide, ship and verify when a committed evidence
record settles it, then **notify the operator at once** (what changed, evidence, merged/deployed/observed, revert). Ask first only when
the data leaves the question open or the action cannot be reverted; **a real-money promotion on a fee-only corpus stays blocked.** Terms:
canonical § "Data-backed Tier-2/3 decisions". **"The data leaves the question open" is not itself a reason to ask** (2026-09-29): getting
the data is a task (queue unit, Stage-1 soak, replay/backfill) — **file it, no popup**; ask only on a preference no data would settle
(`scripts/ops/mandate_resolver.py` → `NEEDS_DATA`; manager skill § "Before any operator popup: classify the decision").

## The two execution gates

Exactly two declared, default-permissive switches decide whether a strategy trades — both in YAML and on `/api/bot/config`:

- **Account level** — `config/accounts.yaml::mode: live | dry_run`. Only the `set-account-mode` system-action (operator-gated) writes `mode:`.
- **Strategy level** — `config/strategies.yaml::execution: live | shadow`. `shadow` runs and logs order packages but never sends a live
  order; folded into the same `effective_dry` in `Coordinator.multi_account_execute`. *(Exception: the M22 pairs sleeve is an isolated
  2-leg path, `pairs_executor.run_pairs_tick`; its gate is `config/pairs.yaml`.)*

**There is no third gate**: never hide a capability behind a default-off `*_ENABLED` flag (the pattern that stranded MES). The
`config/account_state.yaml` dry-only fold was retired 2026-09-29 (JC-CA-06); do not re-add one (`canonical-doc-coherence`).
**`accounts.yaml::symbols` is NOT a gate**: the `strategies:` roster decides what trades; `symbols:` is an additive data-pull list, and a
symbol missing from it is a bug in the PULL LIST, never a reason a rostered leg does not trade (operator, 2026-09-22;
`roster-symbol-reachability` prints current counts).

The trader runs 24/7 and never switches itself off — no auto-flip, no mode-toggling breaker, no go-dry-on-boot default; transient issues
route through `RiskManager` per-trade (canonical § Prime Directive).

⚠️ **There is no halting — in ANY pipeline** (operator, 2026-10-09, binding; Prime Directive rule 7). Trading, prop execution, training,
research and data pipelines never halt themselves: failures are contained per item and retried with diagnosis; when one keeps failing, ONE
red flag reaches the operator while the pipeline keeps trying. A self-halt needs the operator's verbatim permission recorded in the repo
(verbatim quote: pre-diet § "The two execution gates").

⚠️ **The ONE sanctioned exception: the account-level daily drawdown switch** (operator, 2026-10-09): `accounts.yaml::<acct>.risk.daily_dd_switch`,
`armed` defaults `false` (arming is an explicit per-account YAML act); prop default 0.8 × the firm's daily limit at the firm's reset, others
3%; **keep open, block new** (open positions keep SL/TP). A per-trade `RiskManager` refusal, never a `mode:` flip; row `DAILY-DD-SWITCH`.

⚠️ **CI is asymmetric**: `scripts/check_dry_run_in_diff.py` guards turning a leg OFF; **nothing blocks turning one on**, and **removing a leg
from a `strategies:` roster is unguarded** — a promotion guard must key on roster membership, not the `mode`/`execution` fields.

---

## What this is

Multi-strategy trading system (ICT + pairs + macro/value) on two Oracle VMs; FastAPI `:8001` feeds one front end.

- `ict-bot-arm` (141.145.193.91) — live trader: `ict-trader-live.service` (src/main.py → pipeline.py), `ict-web-api.service` (FastAPI :8001,
  `/api/bot/*`, `/api/diag/*`, `/ws/market`), `caddy.service` (HTTPS `ict-bot.duckdns.org` → :8001).
- `ict-trainer-vm` (158.178.209.121) — ML lifecycle · `ict-ib-gateway` (10.0.0.251) — IB Gateway, isolated.

**The Svelte SPA is the only live consumer** (operator, 2026-09-01): `benbaichmankass/ict-trader-dashboard`, calling the API
**browser-direct** through Caddy — **CORS is load-bearing.**

Reference: `docs/reference/*` (bot-api, env-vars, data-model, vm-topology, diag-access, session-capabilities, runtime-notes) and `docs/api-tier-policy.md` — **on demand, not at session start.** Three rules bind you first:
1. **Numbers carry provenance** — `src/runtime/provenance.py`: `MEASURED` · `ESTIMATED` · `FABRICATED` · `UNVERIFIED` (never folded into
   measured). Import it; do not add another bespoke `exclude_*` predicate.
2. **A count that reads `0` may mean "we could not look".** Publish an explicit read-state beside a nullable quantity
   (`scripts/ci/check_collapsed_states.py`).
3. **Render a missing/null field as "—", never `0` or "unknown".**

---

## Access & autonomy

- **VMs/DBs/GitHub** — `VM_SSH_KEY` and `DIAG_READ_TOKEN` are Actions secrets; read both VMs and run tiered changes via workflows you dispatch
  (skills `diag-data`, `vm-ops`, `git-actions`, `db-wiring`); GitHub via the MCP tools.

Retrieve state yourself, then act. Physical/credential actions (rotating exchange/prop keys, an OCI CAPTCHA, a human at a broker) are the
operator's: say exactly what to do, after the `before-asking-the-operator` skill. Tiered production mutations run through the
`system-actions` workflow's fixed allowlist ([`docs/claude/system-actions.md`](docs/claude/system-actions.md)): Tier-1 autonomous, Tier-2
after an operator OK in chat.

---

## Skills

Workflows live under [`.claude/skills/`](.claude/skills/). **Skill-first lookup is binding** — before generating task output, scan the
catalog; precedents are example outputs, not authority. **The manager contract is `.claude/skills/manager/SKILL.md`.**

- `research-ops` (4×/day) · `weekly-audit` (Mon 06:07Z) · `frontier-research` (weekly; `ml_plan_status.py --diversity`) · the ML plan, reviewed
  weekly as step 9 of the Sunday `/ml-review` (`ROADMAP.md` § "AI trader (ML) — build plan"). The three reviews stay separate:
  `/health-review` · `/performance-review` (hands off to `/perf-followup`) · `/ml-review`. The `/system-review` roll-up and ten process
  skills were retired 2026-09-21 (`docs/archive/2026-09-21-operating-reset/skills/`); do not resurrect.

---

## Repo identity

The project is named **JTA Trader** (operator, 2026-10-28; previously "Metis Insights", 2026-07-23, and "ICT bot"). The GitHub repo is renamed by
the operator in GitHub Settings (steps: [`docs/runbooks/jta-trader-rename.md`](docs/runbooks/jta-trader-rename.md)); until then and after, the old
names redirect — **do not chase a rename sweep.** The MCP repo name is whatever THIS session's scope says (a denial is a scope mismatch, not an
outage). **Runtime identifiers deliberately keep their old names:** VM dirs `/home/ubuntu/ict-trading-bot` and `/opt/ict-trading-bot`, systemd
unit names, Python package/module names, the `ict-bot.duckdns.org` domain, bot names, the `Manager Session` title convention, Kaggle slugs,
`~/.cache/metis-*` dirs and `data-metis-*` selectors. Tooling reads the repo slug from `GITHUB_REPOSITORY` / `git remote`, never a literal.
