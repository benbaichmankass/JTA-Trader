# Work store: one register and the bot-output ledgers move off the repo (design, 2026-11)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) ·
> **a DESIGN for operator approval; nothing here is built and nothing changes until the operator approves it.**
>
> Written 2026-11-04 by lane `WORK-STORE-DESIGN` (session_01AFoLuKFYUoKzs5TXjGfEdh), dispatched by Manager Session 2026-11-04b with the
> operator's authority. Rows: `REGISTER-CONSOLIDATION`, `SYSTEM-AUDIT-REPO-FLOWS`; it also settles `AUD-20261104-TWO-PICKUP-REGISTERS`
> (operator ~22:41Z: "Fold into redesign"). Every number is dated 2026-11-04; re-read, never quote forward.

## Gates this adds or changes

**No new gate on trading, deploys, merges or pipelines.** Each control below is disclosed so the operator can see it before approving
(canonical § "No new gates", rule d).

| # | Control | Change | What it blocks, where | Why | How to remove it |
|---|---|---|---|---|---|
| G1 | Filing refusals: an open item needs `owner`, a `roadmap` ref and a computable due | **Carried over, not added.** Today `checklist_store.filing_problems` (`src/runtime/checklist_store.py:56`) refuses a row with no `due_by`, and `pipeline.validate` (`scripts/ops/pipeline.py:284`) refuses an item with no `due_when` / `origin.rerun` / closing reason. The merged model keeps exactly those refusals, each on the item kind it applies to today, and **tightens none**: a build still needs a date, and an observation may still have no date (it is then always due, as `pipeline.is_due` does today). | A write to the store that lacks those fields (new `scripts/ops/work.py`, and the API's validator). | The deep audit's root cause: 504 of 622 open checklist rows have no `due_by`, so nothing surfaced them. | Delete the check in the one validator. |
| G2 | Write authentication on `POST /api/bot/work/items` | **New access control** on a new route (bearer token, fail-closed, the pattern `_require_decision_write_token` uses at `src/web/api/routers/work.py:1879`). | An unauthenticated write to the register on a public host. It does not block any work: every session gets the token through the environment proxy (D3). | A public, browser-reachable host must not accept anonymous edits to the operator's work list. | Remove the dependency on the route. |
| G3 | Optimistic concurrency (`If-Match: <version>`) on item writes | **New.** A write based on a stale version is answered `409` with the current item; the CLI re-reads and re-applies once by itself. | Two sessions silently overwriting each other's edit to one item. | Replaces what git's merge conflict did for the files, without the PR. | Drop the version check (last write wins). |
| — | **Removed:** the per-edit PR, its 4 required checks and the merge-slot claim for register and bot-data writes | **Loosened.** About 1,227 of 1,660 commits on `main` in 7 days touch no code, config or doc (§ 1). | — | — | — |

The deploy path (§ 5) keeps automatic deploys. The bar-close restart window in § 5 would add a delay of up to 3 minutes to a trader restart.
That is a gate, so it is **only proposed** (decision D6). It is not part of the default plan.

---

## 0. The answer in one paragraph

The register and the bot's output move into one **SQLite database on the live VM** (`work_store.db`, a separate file from
`trade_journal.db`), behind the FastAPI routes that already serve the Workflow page. The checklist row and the pipeline item become **one item
model with a computed due**. Every change is an **append-only, hash-chained event**, and that event table replaces `git log` as the audit trail.
Sessions write through a CLI that calls an authenticated API. The SPA reads the same routes it reads today, now live, not 5 minutes behind.
**Git keeps what is reviewed:** code, config, docs, skills, research-unit *specs* (the git timestamp is the pre-registration proof), and the
evidence records a promotion cites. Bot output becomes **ledgers** in the same database, with large research payloads in object storage. These
are records of what happened, not registers of work. **ict-git-sync stays**, because automatic deploys are the operator's rule. It then deploys
only code. On 11-04, all 21 trader restarts followed bot or research writes; none followed a human code merge.

---

## 1. Inventory (MEASURED)

**Population.** Every commit on `origin/main` from 2026-10-28T00:00Z to 2026-11-04T00:00Z: **1,660 commits**, read with
`git log --name-only` after `git fetch --shallow-since=2026-10-28 --filter=blob:none`. Flows are classified by commit subject, because every
bot flow has a fixed subject. Paths are counted with `.github/pr-*` landing files excluded. CI job-hours come from the COMPUTE-ALLOCATION
7-day census (`comms/ci/compute-allocation-inventory-2026-11-03.json`, 10-27T21Z..11-03T21Z, ESTIMATED job-h). They are the PRODUCER
workflow's own hours. The merge-path hours each flow's PR adds are a class total, given below the table.

| Flow (subject) | Commits / 7 d | Files touched | Writes | Producer job-h / 7 d (EST.) | Readers (grep count of files that name the path) |
|---|---|---|---|---|---|
| Desk mirror (`desk: mirror decisions …`) | **232** | 686 | `comms/desk/{role_grade.json, packets/, decisions.jsonl}` | 133 (desk-decisions-mirror) | scripts 11, workflows 4, skills 3, src 1 (`decisions.jsonl`) |
| Work digest (`chore(ops): queue the daily work digest`) | **137** | 411 | `docs/claude/pending-pings.jsonl`, `docs/claude/work/WORK-DIGEST.json` | 103 (work-digest) | the VM sends the queued pings after git-sync: **the repo used as a message queue** |
| Research result batches (`research: batch-land …`) | **127** | **13,566** | `comms/research/RQ-*/…` | part of research-queue-dispatch 175 | grade, programme review, research-ops (scripts) |
| Research result, single (`research result: …`) | 52 | 159 | `research/results/`, `docs/claude/work/` | (same) | same |
| Dispatch stamps (`stamp last_dispatched_at`) | **107** | 634 | `research/queue/*.yaml` (a mutable field on the spec file) | (same) | dispatcher fire gate, 19 scripts |
| Liveness receipts (`research-queue: liveness receipt`) | **103** | 210 | `docs/claude/work/research-queue-dispatch-receipt.json` | (same) | 3 scripts, 3 workflows |
| Live-review mirror (`live-review: mirror …`) | **96** | 507 | `comms/live_review/{packets/, tables/, reviews.jsonl}` | 97 (live-review-rows-mirror) | src 5, scripts 8, skills 6 |
| Research SLO (`chore(research-slo)`) | **93** | 186 | `comms/research/health/*.json` | 58 (research-slo) | 4 scripts, 3 workflows, 3 skills |
| Forecast grade | 37 | 148 | `comms/desk/{forecast_grade, am_judgement_grade}.json`, `forecast_ledger.jsonl` | 20 | 1 script, 3 workflows |
| Mechanical grading (`research-queue: mechanical grading`) | 28 | 1,074 | `research/queue/*.yaml` | 24 (research-queue-grade) | dispatcher, programme review |
| Trainer capture-watch receipt | 21 | 42 | `docs/claude/work/TRAINER-CAPTURE-WATCH.json` | 9 | 2 scripts |
| Queue replenish | 20 | 114 | new `research/queue/*.yaml` | 11 | dispatcher |
| Corpus sweep (`corpus: e35 …`) | 18 | 53 | `docs/research/e35-bracket-corpus*.jsonl` | 13 | e35 harness |
| Counterfactual grades | 14 | 56 | `comms/research/counterfactual_grades/` | 10 | 2 scripts |
| Loss-detector receipt | 14 | 28 | `docs/claude/work/RESEARCH-LOSS-RECEIPT.json` | 8 | 2 scripts |
| Smaller data flows (parity, valuation, utilisation, GDELT, replay pre-gate, strategy-review packets, econ calendar, closed-trade grades, usage, data-lake health) | 66 | 278 | `comms/{live_parity, macro, cloud, news_alpha, strategy_reviews, data_lake}/`, `comms/claude_strategy_scores.jsonl`, `runtime_logs/replay_pregate/` | ≈ 70 together | mostly one script or workflow each |
| Backlog drains | 5 | 147 | checklist rows | — | — |
| **Session and manager commits** (everything else) | **490** | — | **282 touch checklist rows, 116 touch pipeline records**, 223 touch code or config | (merge path) | — |

**Totals and what they cost.**

- **1,227 of 1,660 commits (74%) touch no code, config or doc.**
- **Register writes ride along on the other 26%.** 288 commits touch `docs/claude/work/checklist/` (2,021 file-touches); 122 touch
  `docs/claude/work/pipeline/` (7,144 file-touches).
- **The stores are large.** 1,303 row files (6.3 MB) and 7,193 pipeline record files (32 MB). The research results tree
  `comms/research/` is **5.1 GB on disk across 26,034 files**, and `.git` is 2.2 GB.
- **Merge path, by origin** (COMPUTE-ALLOCATION § 1, before the 11-04 cuts): `automation/*` PRs **685 job-h/wk** of 2,211. That is about
  0.57 job-h per bot PR (ESTIMATED: 685 ÷ ~1,190 automation PRs).
- **After CI-STREAMLINE's cuts** (§ 8 there, 20.3 h on 11-04): merge-path job-h fell 73%. The data-only fast path (B4) now carries most bot
  PRs, so this design's CI saving is **smaller than the pre-cut figure**. It is mainly:
  - the producers' `commit-to-main` verify-merged wait, which holds a runner for up to 80 min (`tests/test_commit_to_main_callers.py`);
  - the landing machinery.
  - Per-flow hours after the cuts were **not separated** (UNVERIFIED).
- **The VM pays for these flows too (§ 5):** 573 of the 1,660 commits change a path outside the deploy's non-runtime set, and 397 of those
  carry the subject prefixes `desk`, `live-review`, `forecast-grade` or `compute-util-telemetry`. Each one restarts services (§ 5).

**What the repo is being used as.** Four different things share one mechanism:

1. **A database:** registers and ledgers.
2. **A message queue:** pending pings, stamps and receipts.
3. **A blob store:** 5.1 GB of research payloads.
4. **A deploy channel** for code.

Only the fourth needs git, plus the research specs and evidence records whose git timestamp is itself the evidence (§ 3).

---

## 2. The ONE register

### 2.1 Where it lives

| Option | For | Against | Verdict |
|---|---|---|---|
| **A. SQLite (WAL) on the live VM, `work_store.db`, behind the existing FastAPI** | Zero new services. Sits next to the API that already serves `/work/*`. The repo already has the patterns: lazy creation and WAL (`src/utils/db_init.py`), a token-gated write route. Writes are immediately visible to the SPA, so it **fixes the 5-minute lag and the "push, then answer" rule**. A separate file means a register write can never lock `trade_journal.db`. | It shares the VM with the 115 s tick (F8, F10). The VM becomes a single point for register writes. | **Recommended** |
| B. Postgres on the VM | Concurrency, roles | A new always-on service and its upgrades on a VM already at a 115 s tick. The write volume (≈ 400 events/day expected, § 2.4) does not need it. | Rejected |
| C. Hosted DB (Neon, Supabase, …) | Off the trading VM | A new vendor, a credential, a network allowlist from every session, and spend. The Workflow page would depend on a third party. | Rejected |
| D. GitHub Issues or Projects as the register | No new store | Rate limits; every edit notifies people; still GitHub. Field schemas and computed due are awkward. | Rejected |
| E. Keep files, but on a non-`main` data branch | Cheapest change | Still git as a database. Still conflicts, still a mirror PR to reach `main`'s readers. It is the desk and live-review pattern: 328 of the 1,227 data commits in § 1. | Rejected |

**Why not the trainer VM:** the API and the Workflow page are on `ict-bot-arm`. A register there would need a second API surface, and the
operator's page would depend on two VMs.

### 2.2 Schema: one item model with a computed due

The checklist row and the pipeline item are the same concept, "this needs someone to act by a time". They merge into **`items`**, with
**`events`** as the only write path.

```sql
-- columns map to today's stores; new ones: kind, parent_id, version, summary, due_at (computed), created_at
-- (pipeline items carry no created field today: imported from the id's date or the first record's filename)
CREATE TABLE items (
  id              TEXT PRIMARY KEY,            -- existing ids kept verbatim (0 collisions between row and item ids, § 4)
  kind            TEXT NOT NULL CHECK (kind IN ('build','observation')),  -- build = a checklist row; observation = a pipeline item
  parent_id       TEXT REFERENCES items(id),   -- an observation's owning build (today pipeline `routed_to: <ROW>`)
  title           TEXT NOT NULL,               -- row.title | item.what
  state           TEXT NOT NULL CHECK (state IN ('queued','in_flight','blocked','landed_unproven','done','dropped')),
  owner           TEXT NOT NULL DEFAULT 'manager',
  lane            TEXT, model TEXT, tier INTEGER,
  roadmap         TEXT NOT NULL,               -- JSON list, or ["unmapped"] + roadmap_unmapped_reason
  roadmap_unmapped_reason TEXT,
  due_rule        TEXT NOT NULL,               -- JSON: {kind: date|every|soak|event, due_date, check_every_days,
                                               --        last_checked, clears_when, soak{subject}}  (pipeline.due_when, generalised)
  due_at          TEXT,                        -- COMPUTED by the store on every write, from due_rule (+ soak state);
                                               --   never accepted from a caller. NULL only for kind=event until the event is recorded.
  origin          TEXT,                        -- JSON {kind, ref, rerun}: required for observations (pipeline reason 3)
  next_action     TEXT CHECK (next_action IN ('dispatch_lane','check_observation','apply_mandate','ask_operator') OR next_action IS NULL),
  priority_rank   INTEGER, severity TEXT,
  ceiling_usd REAL, spend_usd REAL,
  prs             TEXT,  blocked_on TEXT,      -- JSON, as today
  summary         TEXT,                        -- the current one-paragraph state; history lives in events
  terminal_reason TEXT,                        -- REQUIRED to enter done/dropped (pipeline reason 4; checklist note today)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
  version         INTEGER NOT NULL             -- optimistic concurrency (G3)
);
CREATE TABLE events (                          -- append-only; the audit trail (§ 2.4)
  seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, at TEXT NOT NULL, by TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('create','set','note','close','reopen','observe','migrate')),
  patch TEXT NOT NULL,                         -- JSON of exactly what changed (or the note text)
  op_id TEXT UNIQUE,                           -- client idempotency key: a retried write is a no-op
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL  -- sha256(prev_hash || canonical(row)): tamper-evident chain
);
CREATE VIEW due_now AS SELECT * FROM items WHERE state NOT IN ('done','dropped') AND due_at <= strftime('%Y-%m-%dT%H:%M:%SZ','now');
```

**How the two vocabularies map:**

| Today | In the merged model |
|---|---|
| checklist `due_by` | `due_rule {kind: date}` |
| pipeline `due_when` | `due_rule`, kept as written |
| pipeline `queued` / `due` | `queued`. "Due" is computed, never stored, as `pipeline.py` already insists (reason 1). |
| pipeline `routed` + `routed_to: ROW` | `queued` with `parent_id = ROW` |
| pipeline `killed` | `dropped` + `terminal_reason` |
| the long `note` | first imported as one `migrate` event, then one `note` event per later append |

**What this settles from the deep audit (#13).**

- **There is one register.** The checklist row is the build, and the pipeline item is an observation, usually hanging off its build.
- **Due is computed for both.** `due_now` is the single "what came due" list, so the brief's section 0 and the manager's step-4b sweep read
  the same thing.
- **An undated item is not filed (G1).** A `routed` observation whose parent closed shows up as a computed **orphan**, never as an owned item.
  That is today's `owner_closed` class: 96 items.

**Derived fields, never stored:**

- strategy status (as `scripts/ops/strategy_status.py` does today);
- `ageHours` and `staleInFlight` (in_flight with `updated_at` older than 48 h and no live lane);
- `overdue`.

`CHECKLIST-STATE-TRUTH` (c) becomes a view, not a script.

### 2.3 How sessions write, and how the Workflow page reads

- **Write: `scripts/ops/work.py`**, a thin HTTPS client with the verbs sessions already know:
  - `add`, `set`, `note`, `close --reason`, `observe` (record a check of an observation), `reopen`, `queue`.
  - `checklist.py add|set|note` and `pipeline.py` appends become shims over it, so skills, prompts and the 8 workflows that call them keep
    working through the transition.
  - Every write carries `op_id` and `If-Match: version`. The server validates (G1), computes `due_at`, appends the event and updates the item
    in one transaction.
- **Transport: the session → `https://ict-bot.duckdns.org/api/bot/work/items`.**
  - The bearer is a **new, write-scoped token `WORK_STORE_TOKEN`**. It is accepted by these routes only, never by `prop/report` or `decision`.
  - It is injected by the cloud environment's proxy for that host (`request_credential`), so no session ever holds the value. The operator
    originates it (D3).
  - **Fallback** when the VM is unreachable from a session: the CLI posts the same op JSON as a comment on one fixed GitHub issue
    ("work-store outbox"). A small workflow drains the outbox every 5 min into the API, idempotent by `op_id`. That costs no PR, no required
    checks and no repo write. The CLI says which path carried the write.
- **Bots and the VM write in-process** through the same module (`src/runtime/work_store.py`, the successor of `checklist_store.py`, so
  `checklist-readers-guard`'s one-loader rule carries over).
- **Read:** `GET /api/bot/work/checklist`, `/snapshot`, `/brief`, `/report` and `/decisions` keep their response shapes, read from the
  database instead of the VM's working tree. **The SPA needs no change.**
  - New: `GET /api/bot/work/items?state=&due=&parent=&since=` and `GET /api/bot/work/items/{id}/events`.
  - `/work/checklist` is 4.19 MB today (F7). It gains `?open=1` and pagination, so the card stops pulling the closed history.
  - **Reads stay open**, as they are today ("Reading is never gated").
- **The VM's own consumers** (`attention_watch.py`, `work_digest_now.py`, `work_report.py`, `blocker_watch`, `owner_liveness`) read the
  database in-process. A failed read publishes `read_state: could_not_look`, never "0 due" (collapsed-states rule).

### 2.4 Backups and history (replacing `git log`)

- **The audit trail is `events`.** Every create, set, note and close is a row with who, when and the exact patch. It is hash-chained, so a
  silent edit breaks `hash`. `work.py history <id>` replaces `git log -p docs/claude/work/checklist/<id>.json`.
  - Expected volume: 288 checklist-touching and 122 pipeline-touching commits a week today (they overlap) become ≈ 400–600 events a day once every note is its own event. That is
    small for SQLite.
- **Backups, three tiers:**
  1. `sqlite3 .backup` every hour to `runtime_logs/backups/work_store/`, keeping 48.
  2. A nightly copy pulled by the trainer VM over the same SSH path that already pulls `trade_journal.db` (F11).
  3. A **weekly JSONL export of `items` + `events` committed to the repo** in one PR. That is git durability and public readability for
     about 1 PR a week instead of about 410 (D5).
- **Restore drill, monthly and report-only:** restore the latest backup into a scratch file, verify the hash chain and compare counts with
  the live database. A failure is a red flag, not a halt.

---

## 3. What moves off the repo, what stays, and why

**Rule.** A file stays in git if a human reviews it, a running process loads it as code or config, or its **git timestamp is itself evidence**
(pre-registration). Anything a bot appends on a clock is a record. Records go to a ledger table, or, when large, to object storage with the
hash in a ledger row.

| Stays in git | Why |
|---|---|
| Code, config, workflows, deploy units, skills, docs, ROADMAP, `docs/roadmap/milestones.yaml` | Reviewed, and loaded by processes; CI decides something about them |
| `research/queue/<id>.yaml` unit **specs** and the `research/templates/` | The commit timestamp proves the rule was **registered before the run** (OPERATING-PLAN Stage 0). A database row an operator could edit afterwards does not. |
| **Evidence records cited by a promotion or mandate** (`comms/strategy_evidence/`, `comms/mandate_evidence/`, `comms/prop_survival/`) | CLAUDE.md: nothing reaches a book without a **committed** evidence record. The record lands in the promotion's own PR, which is a config PR anyway. **Unchanged.** |
| Reviews and audits as documents (`docs/reviews/`, `docs/audits/`) | Read by people; one per review |

| Moves to the work store | Today | Becomes |
|---|---|---|
| Checklist rows, pipeline items, `SOAKS.json` contracts, `soak-state.json` | files + PRs | `items` / `events` (soak contract = `due_rule.soak`) |
| Dispatch stamps and grading state on unit YAML | 107 + 28 commits/wk editing the **spec** file | `research_runs` ledger (unit id, run id, dispatched_at, verdict, grade). The spec file stops being edited after registration, which also makes the pre-registration claim cleaner. |
| Liveness, capture-watch and loss-detector receipts, usage readings | 145 commits/wk (103 + 21 + 14 + 7) | `receipts` ledger: `{producer, at, run_id, read_state, body}` |
| Pending pings from GitHub producers | `docs/claude/pending-pings.jsonl` via git-sync | `POST /api/bot/alerts` (ALERT-LEDGER step 1). This is the same chokepoint, so the repo stops being a message queue. |
| Research SLO, forecast grade, counterfactual and closed-trade grades, parity, utilisation, data-lake health, strategy-review packets | 175 commits/wk | ledger tables, one per record family (`slo_readings`, `grades`, …); each served by the API |
| `config/economic_calendar.yaml`, rewritten by the econ-calendar bot (7 commits/wk) | a bot editing **config**, which restarts every unit | an `econ_calendar` ledger the reader queries. The build checks which keys in that file are bot-written; `config/` keeps the human-set ones |
| Desk decisions + packets, live-review rows + packets + tables | branch + mirror PR (328 commits/wk) | `desk_decisions` and `live_reviews` ledgers written by the session through the API (D4) |
| Research result payloads (`comms/research/RQ-*`; the whole `comms/research/` tree is 5.1 GB) | batch-land PRs (127/wk, 13,566 files) | object storage (OCI bucket or the trainer's disk, D7) keyed by sha256; the `research_runs` row holds the verdict, the metrics and the payload hash |

**One store or two?** One database file holds two table families:

- the **register** (`items`, `events`): work, with a due;
- the **ledgers**: facts, with no due.

The integration audit's rule holds: a ledger is never a third register. An alert, a desk decision or an SLO breach that needs work becomes an
`item`, linked to the ledger row that caused it.

---

## 4. Migration of every existing row and item (dry run)

**Dry-run population:** `main` @ `b78decb3f`, read 2026-11-04 ~23:20Z with `checklist_store.load()` and `pipeline.load()`.

- checklist: 1,303 rows;
- pipeline: 2,619 item ids over 7,193 records, 0 unreadable, 4 collisions reported by `pipeline.load()` (kept as events, never merged);
- row ids ∩ item ids = **0**, so ids are kept verbatim.

The script that produced these counts is in Appendix A.

| Source | Count | Imported as | Needs a disposition at import? |
|---|---|---|---|
| Checklist `done` / `dropped` | 536 / 145 | closed `build`; `terminal_reason` = the row's note (all 681 carry a note ≥ 10 chars) | no |
| Checklist open, **dated** | 118 | open `build`, `due_rule {date}` | no |
| Checklist open, **undated** | **504**: queued 220, landed_unproven 255, blocked 16, in_flight 13 | open `build` with a **triage due** (below) | **yes**, one by one, in the triage drain |
| Checklist `in_flight` with no `lane` | 7 | open `build`, flagged `staleInFlight` | yes (CHECKLIST-STATE-TRUTH sweep) |
| Pipeline `done` / `killed` | 523 / 1,360 | closed `observation`; `terminal_reason` kept (0 missing) | no |
| Pipeline routed → **live** row | 310 | open `observation`, `parent_id` = that row | no |
| Pipeline routed → **closed** row | **97** | open `observation`, parent kept, computed **orphan** | **yes**: re-parent or close with a reason |
| Pipeline routed → unresolved / PR | 14 / 6 | open `observation`, no parent, computed orphan | yes |
| Pipeline queued, **due** (= unrouted) | **175** (oldest 156 d, BL-20260601-003) | open `observation`, no parent | yes |
| Pipeline queued, not yet due | 134 | open `observation` | no, the computed due surfaces it |
| Event history | 7,193 pipeline records + the git history of 1,303 row files | `migrate` events: each pipeline record becomes one event, and each row's current note becomes one event (the row files' git history stays in git; it is not replayed) | — |

**No bulk drop.** Nothing is closed by the importer. Every open item arrives open. The import is a `migrate` event per item, and a closed item
carries its existing reason.

**The triage due for the 504 undated rows.** Assign `due_at` in three weekly waves:

1. landed_unproven (255) first, because their closing observation is usually one read;
2. then blocked + in_flight (29);
3. then queued (220), by `priority_rank` first (254 open rows carry one).

The waves give each row a date; they close nothing. **Funding the drain is D2.**

**Cutover in five steps (each step can be reverted with a `git revert`; there is no switch flag):**

1. **Shadow:** the importer runs every 5 min from the files into the database. `GET /work/checklist?source=db` is compared with the
   file-served payload, and the parity report lists every differing row.
2. **Freeze:** after two clean days, the `checklist.py` / `pipeline.py` shims start writing to the API, and the files stop being written.
3. **Flip readers:** the routes and the VM consumers read the database.
4. **Archive:** the files move to `docs/archive/2026-11-work-store/`, and one final export matches them.
5. **Retire** the mirror workflows and the `commit-to-main` callers for data, flow by flow (§ 6).

---

## 5. The deploy path: keep ict-git-sync

**Measured this session.** The question was why the trader restarted 21 times on 11-04 (F9). I matched the 21 `Started ICT Trader Live`
times (00:00–18:18Z) against the merges to `main` in the same window, taken from `git log --format=%ct` in UTC.

- **All 21 restarts came 1–7 min after a merge that changed a path outside the deploy's non-runtime set.**
- **For 19 of the 21, every such merge was a bot data write:** the desk mirror, the live-review mirror (including "mirror 0 row(s)"),
  forecast-grade, closed-trade grades, live-parity and compute-util telemetry.
- **The other 2 were not human code either.** 03:19 was a bot writing `config/economic_calendar.yaml` (the econ-calendar flow writes
  config). 01:01 was a prop-survival evidence record under `comms/prop_survival/`. **No restart that day followed a human code merge.**

The cause, from the code:

- `scripts/deploy_pull_restart.sh` (the `RUNTIME_CHANGES` `grep -vE`) and `scripts/ops/trader_import_closure.py`
  (`NON_RUNTIME_PATHS_RE`, rule b: "a non-`.py` path outside the non-runtime set restarts the trader") both list `comms/research/`,
  `comms/strategy_evidence/` and `comms/macro/`.
- Neither lists `comms/desk/`, `comms/live_review/`, `comms/claude_strategy_scores.jsonl`, `comms/live_parity/`, `comms/cloud/`,
  `comms/news_alpha/`, `comms/strategy_reviews/` or `comms/reports/`.

**Filed as row `DEPLOY-RESTART-ON-DATA-MIRRORS`** (Tier 2, due 2026-11-07), because the fix is one PR and should not wait for this design.
Its first step is confirming that no long-running unit caches those trees at import.

**The two options:**

| | A. Keep ict-git-sync (5-min pull, automatic) | B. Manager-driven deploys (deliberate pull-and-deploy) |
|---|---|---|
| Merged-but-undeployed drift | Bounded at about 5 min, plus a restart-gate skip that is recorded per unit (`deployed_sha*.txt`) | Unbounded. It grows whenever the manager is busy, rotating or compacting, and a session will believe a merged fix is live. |
| "Merged ≠ deployed ≠ observed" | Deployed is automatic; observed still has to be checked | All three are manual |
| Surprise restarts | **Today 21/day, 19 of them from data.** After `DEPLOY-RESTART-ON-DATA-MIRRORS` and § 3, only code merges restart. On 11-04 that would have been 0 of 21; bot config writes like the econ calendar stay in git until moved. | Only when chosen |
| Rollback | `git revert` on `main`, live in ≤ 5 min | `git revert` + a dispatch |
| Canonical fit | **"Deploys of green Tier-1/2 work are automatic"** (No new gates, c) | Puts a person in the deploy path: **a new gate** that needs the operator's permission |
| Workflow page freshness | No longer depends on sync once the register is in the database | Same |

**Recommendation: A, made observable.**

1. Data stops flowing through `main` (§ 3), so a sync deploys only code.
2. On every deploy the VM appends a `deploys` ledger row: `{at, from_sha, to_sha, units_restarted, trader_gate_note, healthy_at}`. That
   makes "deployed" and "observed" recorded facts.
3. A report-only drift detector (audit #11) flags a running sha ≠ the on-disk sha for more than 15 min. F9 caught `156f1b1a8` running vs
   `2c37e7330` on disk.

**D6 (optional, a gate):** defer a *trader* restart that would land within ±2 min of an hourly bar close by up to 3 min. 17:01Z on 11-04 is the
case. It is not in the default plan.

---

## 6. Build order, and where the re-scoped rows plug in

| Step | What | Tier | Depends on | Closing observation |
|---|---|---|---|---|
| **P0** | `DEPLOY-RESTART-ON-DATA-MIRRORS`: widen the three lockstep non-runtime lists | 2 | — | a day of journalctl with no trader restart within 7 min of a data-only merge |
| **P0** | `CHECKLIST-STATE-TRUTH` (a): sweep every in_flight row against `get_session` **on today's files** | 1 | — | 0 in_flight rows older than 48 h with no live lane |
| **S1** | `src/runtime/work_store.py` + `work_store.db` schema + `events` hash chain + validator (G1) + computed `due_at` + `POST/GET /api/bot/work/items` + `WORK_STORE_TOKEN` (G2) | **2** (a new store on the VM API: Generation Discipline rule 3 needs the operator's OK, which is D1) | D1, D3 | a synthetic item written by a session appears in `GET /work/items` within 1 s, with its event |
| **S2** | Importer + dry-run + shadow parity (§ 4 steps 1–2) | 2 (a VM timer that writes the new store) | S1 | the parity report shows 0 differing rows over 2 days, and the counts equal Appendix A re-run on that day |
| **S3** | `scripts/ops/work.py` CLI; `checklist.py` / `pipeline.py` become shims; outbox fallback workflow | 1 | S1 | a write from a cloud session lands through each path (direct and outbox) |
| **S4** | Readers flip: `/work/*` routes, `attention_watch`, `work_digest_now`, `work_report`, `blocker_watch`, brief section 0 from `due_now`; guards repointed (§ 7) | 2 (VM services) | S2, S3 | `/work/checklist` byte-shape unchanged for the SPA; the brief's section-0 count equals `due_now` |
| **S5** | `CHECKLIST-STATE-TRUTH` (b)+(c): dispatch sets `in_flight` **in the same API call** that records the lane; `staleInFlight` / `ageHours` as views; `owner_liveness.main()` reads the store | 1 | S4 | `staleInFlight` reads 0 for a day, with the denominator printed |
| **S6** | Ledgers + flow moves, in order of restart and CI cost: work-digest pings → alerts POST; desk + live-review → API (D4); forecast/grades/SLO/receipts → ledgers; stamps + grading → `research_runs`; research payloads → object storage (D7) | 1–2 per flow | S1; ALERT-LEDGER step 1 for pings | each flow: 0 commits/wk on `main` from its subject, and its readers reading the API (re-run § 1) |
| **S7** | Retire the mirror workflows and data `commit-to-main` callers; archive the files; weekly export (D5) | 1 | S6 | § 1 re-run: data-only commits on `main` ≤ 10/wk (from 1,227) |
| **S8** | Triage drain of the 504 undated rows and 292 orphan/unrouted items (D2) | 1 | S4 | 0 open items without a computable due; orphan count published every day |

**Where the re-scoped rows plug in.** Each is **built against the new store, not the file tree**, per the operator's 22:27Z direction.

| Row | Plugs in at | How its scope changes |
|---|---|---|
| `ALERT-LEDGER-TO-MANAGER` step 4 | after S4, beside S6 | The ledger lives in the same database as an `alerts` ledger (not `runtime_logs/alerts_ledger.jsonl`). The work report's alerts section is a store query. An alert class that needs work becomes an **item via the API**, not `checklist.py add`. Steps 1–3 can start now on the jsonl and import later; better, they start once S1 lands. |
| `CHECKLIST-STATE-TRUTH` | (a) now on files (P0); (b)+(c) at S5 | `staleInFlight` is a view over `updated_at`, which is real once every edit is an event; no file scanning. |
| `LIVE-DECAY-MONITOR` | after S1 + S6 ledger API | The template stays in `research/templates/` (git: pre-registered). CUSUM readings go to a `decay_readings` ledger. A trip **creates an observation item** with `next_action: dispatch_lane` (a cause-naming unit), never a config edit. |
| `PASS-TO-DECISION-SLO` | definitions now; computation after S6 (`research_runs`) | The SLO definitions stay in `scripts/research/research_slo.yaml`. "Money-leg PASS older than 5 d with no decision" is a join of `research_runs` with `items`, and is only computable once both are in one database. Readings go to `slo_readings`, not `comms/research/health/`. |
| `ML-LEARNING-LEDGER` | after S1 | The weekly record is a `ml_learning` ledger row per hop (H1–H7), with `read_state` per hop, served to `/ml-review`. The script stays in `scripts/ops/`. |
| `UI-OVERVIEW-HEALTH-CARDS` | after S4 | The cards bind to store-served endpoints (`/work/items` aggregates, ledger summaries with `read_state`), designed against the new contract. Built on the file tree, they would have to be rebuilt within a week. |
| `CI-BATCH-BOOKKEEPING` (COMPUTE-ALLOCATION B5) | **superseded by S6** for stamps, receipts and result batches | Batching three PRs into one is a stopgap the store removes. **Recommendation: do not build B5** unless S6 slips past 2026-11-18. |

---

## 7. Risks, rollback, and the guards and tests to update

| Risk | Mitigation |
|---|---|
| The VM is down or unreachable, so the register cannot be written | Reads come from the hourly backup copy on the trainer. Writes go through the outbox issue (§ 2.3), drained when the VM returns. A VM that is down is already the trading emergency, and the register is not the binding constraint then. |
| Database corruption or a bad migration | WAL, hourly backups, the hash chain, a monthly restore drill. The files are archived, not deleted, until S7 + 30 days. `work.py export --to-files` can regenerate the file store at any time. |
| Load on a VM that already runs a 115 s tick (F8) | Writes are tiny. Reads are indexed, and `/work/checklist?open=1` removes the 4.19 MB full pull. Heavy aggregates (the brief) are computed by the existing `ict-work-digest` timer, not per request. |
| The public git audit trail is lost | The hash-chained `events` table, plus the weekly export committed to git (D5). |
| Pre-registration integrity | Unit specs stay in git and are no longer edited after registration. Stamps move off them (§ 3). |
| The write token leaks | It is write-scoped to `/work/items` and the ledgers only. Rotation is the operator's credential action. Every write records `by`. |
| Two truths during the transition | There is no dual write. The shadow importer is one-way (files → database) until the freeze, then one-way (database → archive). |
| A session cannot reach the API (firewalled egress) | The outbox path; the CLI reports which path carried each write. |

**Rollback per step:** S1–S3 are additive. S4 is a `git revert` of the reader flip, and the files are still current until the freeze. After
the freeze, roll back with `work.py export --to-files`, then revert S4.

**Guards and tests to update.**

The population is `scripts/ci/run_guards.py` (129 guards) plus the 8 workflows that call `checklist.py` or `pipeline.py` (grep). Each
guard below keeps its rule and changes only where it reads:

| Guard or test | Change |
|---|---|
| `checklist-readers-guard` | the one-loader rule now points at `src/runtime/work_store.py` |
| `checklist-store-guard` | becomes `work-store-guard`: schema, hash chain, validator self-test |
| `pipeline-guard` | its five-reason self-test moves onto the merged validator |
| `roadmap-map-guard` | reads `roadmap` refs from the store, or from the weekly export when CI has no VM access |
| `soak-contract-guard`, `soak-registered-guard`, `soak-doctrine-guard` | soak contracts are `due_rule.soak`; read from the store export |
| `operator-owed-guard`, `shadowed-features-guard`, `prop-roster-gate-guard`, `research-workflow-landing-guard`, `research-queue-ml-consumer-guard`, `research-tooling-selftests` | each reads checklist, pipeline or soak data by grep; repointed |
| `new-table-wiring` | the new tables declare their canonical-source relationship: `items` ← checklist+pipeline (backfill = § 4), ledgers ← their producers |
| `canonical-doc-coherence` | CLAUDE.md and canonical name `PIPELINE.jsonl`, which audit item 16 already flagged as wrong; they now name the store |
| `check_collapsed_states.py` | covers the store's `read_state` |
| `tests/test_push_paths_ignore_bot_data.py`, `tests/test_commit_to_main_callers.py`, `tests/test_deploy_pull_restart_runtime_gate.py`, `tests/test_diag_restart_pending_lockstep.py` | data paths retire flow by flow |

**CI reaching the store.** A guard on GitHub cannot read the VM database directly. Guards that need register data read the weekly export or
call `GET /api/bot/work/items` through the existing diag transport. A failed read is `could_not_look`, never a pass.

---

## 8. Decisions for the operator (one popup)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| **D1** | Approve the design: one SQLite `work_store.db` on the live VM behind the API, with `items` + `events` as the one register and ledgers for bot output (Generation Discipline rule 3: a new store needs your OK + a backfill, § 4) | **Approve (Recommended)** | Zero new services. It fixes the 5-min lag and moves the 74% of `main` commits that are data off the merge path. |
| **D2** | The 504 undated rows and 292 orphan/unrouted items: a **funded triage drain** in three weekly waves (each row gets a date or a stated close), or import them as-is and let the computed due surface them | **Funded drain (Recommended)** | The audit's root cause is undated rows. Importing them undated would reproduce it in the new store. |
| **D3** | Session write access: a new write-scoped `WORK_STORE_TOKEN` injected by the environment proxy (you originate the value once), with an issue-outbox fallback | **Yes (Recommended)** | Sessions never hold a secret. The scope is the register only, not `prop/report` or `decision`. |
| **D4** | Desk and live-review rows move from protected branches + mirror PRs to API writes. This changes the 10-26 "rows branch + pinned commit" design: the apply reads the row from the store by `review_id` + content hash. | **Move them (Recommended)** | They are 328 of the 1,227 data commits a week, and the mirrors drive the restarts. The pinned-content property is kept by the hash. |
| **D5** | Keep a weekly JSONL export of the register committed to git | **Yes (Recommended)** | Public history and a recovery point for about 1 PR a week |
| **D6** | Defer a trader restart that would land within ±2 min of an hourly bar close by up to 3 min. **This is a gate.** | **Not now (Recommended)** | On 11-04, 0 of the 21 restarts followed a human code merge. Measure the restarts left after the data moves first. |
| **D7** | Research payloads (5.1 GB under `comms/research/`): OCI object storage, or the trainer VM's disk | **Trainer disk first (Recommended)**, behind the same hash interface | No new vendor. It moves to OCI if the disk alarm fires. |
| **D8** | Deploy path | **Keep ict-git-sync, automatic (Recommended)** plus the `deploys` ledger and a report-only drift detector. Manager-driven deploys would add a gate (No new gates, c). | — |
| **D9** | Drop COMPUTE-ALLOCATION B5 (`CI-BATCH-BOOKKEEPING`) in favour of S6 | **Yes, unless S6 slips past 11-18 (Recommended)** | It batches PRs the design deletes |

---

## Appendix A — the dry-run count (re-run)

```bash
python3 - <<'EOF'
import sys, collections; sys.path[:0] = ['.', 'scripts/ops']
from datetime import date
from src.runtime import checklist_store as cs; import pipeline as p
t = date.today(); rows = cs.load()['items']; R = {r['id']: r for r in rows}; res = p.load(); I = res.items
op = [r for r in rows if r['state'] not in cs.TERMINAL]; und = [r for r in op if not cs._as_date(r.get('due_by'))]
print('rows', len(rows), dict(collections.Counter(r['state'] for r in rows)), 'open', len(op), 'undated', len(und),
      dict(collections.Counter(r['state'] for r in und)), 'id-collisions', len(set(R) & set(I)))
b = collections.Counter()
for i in (i for i in I.values() if i['state'] in p.OPEN_STATES):
    if i['state'] == 'routed':
        k, ref = p.owner_of(i, R)
        b[('routed->live row' if R[ref]['state'] not in cs.TERMINAL else 'routed->CLOSED row') if k == 'row' else 'routed->' + k] += 1
    else:
        b['queued, due' if p.is_due(i, t) else 'queued, not due'] += 1
print('items', len(I), 'records', res.records, dict(collections.Counter(i['state'] for i in I.values())), dict(b))
EOF
```

Result 2026-11-04 (`main` @ `b78decb3f`):

- **rows:** 1,303 (done 536, queued 283, landed_unproven 281, dropped 145, blocked 20, in_flight 38); open 622; undated 504 (queued 220,
  landed_unproven 255, blocked 16, in_flight 13); id collisions 0.
- **items:** 2,619 over 7,193 records (done 523, routed 427, killed 1,360, queued 309).
- **open buckets:** routed → live row 310, routed → closed row 97, routed → unresolved 14, routed → PR 6, queued and due 175, queued and not
  due 134.

**Two counts reconcile with the deep audit's.**

- The audit's 577 due is now 582, and its 166 unrouted is now 175. Both were read from the same store.
- The audit's 617 open rows is 622 here. Both differences come from rows and items filed after 18:40Z.

## Appendix B — the restart match (re-run)

1. `git log origin/main --since=2026-11-03T23:00Z --format='@@%ct|%s' --name-only`.
2. Keep the commits with a path that `trader_import_closure.NON_RUNTIME_PATHS_RE` does not match.
3. For each of F9's 21 restart times, list those commits 0–7 min before it.

Result: 21 of 21 restarts have one. For 19, every such commit is a data flow. The other 2 are a bot write to `config/economic_calendar.yaml`
and a `comms/prop_survival/` evidence record.
