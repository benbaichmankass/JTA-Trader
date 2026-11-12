# GitHub Actions — Canonical Reference

> **Doc status:** `live` · category `unknown` · last verified `2026-09-07` · registered in [`docs/DOCUMENT-INDEX.md`](../docs/DOCUMENT-INDEX.md)

> **Status:** Canonical. Adopted in sprint **S-CANON-1** (2026-05-10).
> Last updated: 2026-05-13 (added trainer-VM workflows, vwap-backtest,
> doc-audit, complete autonomy matrix, exact MCP trigger calls).
> **Repo:** `benbaichmankass/ict-trading-bot`.
> **Authority:** This is the single source of truth for what GitHub
> Actions exist in this repo, how they are triggered, what they do, and
> when Claude may use or modify them. Linked from
> [`CLAUDE-RULES-CANONICAL.md`](CLAUDE-RULES-CANONICAL.md) and
> [`ARCHITECTURE-CANONICAL.md`](ARCHITECTURE-CANONICAL.md).
>
> **Other repo:** `benbaichmankass/ict-trader-dashboard` has **no**
> `.github/workflows/` directory as of this writing.

---

## ⛔ STOP — Read before touching any workflow

**Before creating a new workflow or writing any SSH/diag/backtest
automation, check the catalogue below first.** Most common operations
already have a workflow. Creating a duplicate wastes PRs, clutters the
Actions tab, and adds dead code.

| Need | Existing workflow | Trigger |
|---|---|---|
| Run any command on the **trainer VM** | `trainer-vm-diag.yml` | `trainer-vm-diag-request` label |
| Run any command on the **live VM** (read-only) | `vm-diag-snapshot.yml` | `vm-diag-request` label |
| Mutate the **live VM** (restart, deploy, mode-flip) | `system-actions.yml` | `system-action` label |
| Run a **VWAP backtest** on the trainer VM | `vwap-backtest.yml` | `vwap-backtest-trigger` label |
| Check network reachability from GitHub runner | `vm-net-diag.yml` | `vm-net-diag-request` label |
| Restart the live VM web API | `vm-web-api-recover.yml` | `vm-web-api-recover` label |
| Take a health snapshot of the live VM | `health-snapshot.yml` | `health-snapshot-trigger` label |

If the use case is not in this table, read the full catalogue before
deciding to create a new workflow.

---

## Why this doc exists

Claude is allowed (and expected) to use GitHub Actions as part of the
project's automation surface — for CI, validation, VM ops, training,
and dataset publishing. Earlier sessions sometimes assumed Actions were
unavailable; that assumption is wrong and has cost work. Inspect this
document first, then read the specific workflow file under
`.github/workflows/`.

**Key constraint:** The GitHub MCP tools available to Claude Code on the
web do **not** include `run_workflow`, `download_artifact`, or
`get_run_logs`. All Claude-initiated triggers must use one of the MCP
patterns listed below. The `.mcp.json` in the repo root enables
`workflow_dispatch` via the CLI-side GitHub MCP server (takes effect
after a session restart with `GITHUB_TOKEN` set).

---

## MCP trigger patterns

Claude has three ways to fire a workflow without operator-UI access:

### Pattern A — Issue-driven (preferred for most ops workflows)

Open a GitHub issue with the correct label. The workflow's
`issues: types: [opened]` handler picks it up, runs, comments the
result back on the issue, and closes the issue.

**MCP call:**
```
mcp__github__issue_write
  owner: benbaichmankass
  repo: ict-trading-bot
  title: "[<tag>] <description>"
  body: |
    <key>: <value>
    ...
  labels: ["<label-name>"]
```

The issue `body` is the payload: each workflow documents its expected
keys. Always quote the body through the `body` field — never inline
`${{ github.event.issue.body }}` into shell; the workflow reads through
`ISSUE_BODY` env var to prevent shell injection.

### Pattern B — Push-sentinel (for push-triggered workflows)

Some workflows use `push: paths: [.github/triggers/<name>]` as an
alternative trigger so they can be fired without UI or `gh` access.
Touch the sentinel file to start a run.

**MCP call:**
```
mcp__github__create_or_update_file
  owner: benbaichmankass
  repo: ict-trading-bot
  path: .github/triggers/<workflow-name>
  message: "chore: trigger <workflow-name>"
  content: <base64 of "timestamp\n">
  branch: main
  sha: <current file SHA, if file exists>
```

Get the current SHA first with `mcp__github__get_file_contents` so the
update call doesn't fail. The sentinel file carries no semantic content;
only its mtime matters.

### Pattern C — workflow_dispatch (operator-UI only for now)

Workflows that have only `workflow_dispatch` (no issue trigger, no
sentinel) require an operator to click "Run workflow" in the GitHub
Actions UI. Claude cannot fire these from a web sandbox session.
After a session restart with `.mcp.json` loaded and `GITHUB_TOKEN` set,
the CLI GitHub MCP server exposes `mcp__github__create_workflow_dispatch`
which would unlock these.

---

## Autonomy levels

| Level | Meaning |
|---|---|
| **AUTONOMOUS** | Claude may trigger without operator confirmation. Trainer-VM ops, read-only diag, doc audit, health snapshots, and anything in the sandbox that is read-only or trainer-scoped. |
| **OPERATOR-APPROVAL** | Claude must get operator sign-off in conversation before opening the issue / touching the sentinel. Mutating live-VM ops, OCI infrastructure changes. |
| **AUTO** | Runs automatically (CI guard on PR/push, cron schedule). Claude never needs to trigger these; they self-fire. |

---

## The landing route — how a PR gets from pushed to merged

Full contract: [`.github/pr-landing/README.md`](../.github/pr-landing/README.md).
Enforced on every PR by `pr-landing-guard`
([`scripts/ci/check_pr_landing.py`](../scripts/ci/check_pr_landing.py)).

**Every PR writes `.github/pr-landing/<branch-slug>.json`** declaring its tier
and how it means to land. The guard checks that declaration **against the diff**
— it is not satisfied by the file merely existing.

### The two mechanisms are not alternatives

`docs/CLAUDE-RULES-CANONICAL.md` § Permission Tiers says Tier-1 work needs **no
human OK to merge**. Two separate things must both be true for that to actually
happen, and either alone leaves the work sitting:

| | decides | on its own |
|---|---|---|
| `"draft": false` (in `automation/pr-requests/<name>.json`, or `create_pull_request`) | **readiness** — approved to land | a ready, green PR waiting for a human click |
| `.github/pr-automerge-requests/<slug>.txt` | **landing** — `claude-pr-automerge` enables native auto-merge; GitHub merges only on green | against a **draft** PR it is **refused**, by design |

So **Tier-1 = both**; **Tier-2/Tier-3 = neither**, and the PR stays a draft with
a typed `hold_reason`. That draft refusal in `claude-pr-automerge.yml` is a
correct safety property — do not weaken it, and do not try to route around it.

### Why this exists

Measured 2026-09-03: seven of the night shift's PRs sat open, green and
unlanded, waiting on the manager for work that needed no approval.
`scripts/ops/session_registry.py`'s spawn prompt ended, unconditionally and at
every tier, with *"Open the PR as a DRAFT; the manager merges."* That blanket
line was the cause and is now tier-aware.

⚠️ **Three of those PR bodies blamed `pr-opener.yml` for "creating every PR as a
draft regardless of `draft:false`". That claim is FALSE — do not repeat it.**
`pr-opener.yml`'s draft line is
`[ "$(jq -r '.draft // true' "$req")" = "true" ] && draft_flag="--draft"`:
`draft:false` **is** honoured, `true` is merely the default, and the request
files those sessions wrote asked for `"draft": true`.

### The teeth, and why they can bite

`pr-landing-guard` is a required check and auto-merge merges only on green, so a
branch that arms auto-merge while under-declaring its tier **holds itself out of
`main` by failing its own guard**. The bite is the merge gate the branch already
asked to be judged by, not an alarm somebody has to read.

- **R10** — arming with no valid Tier-1 self-land declaration fails, and is
  **not** grandfathered for old branches. Age excuses not knowing the rule; it
  does not excuse asking to merge without approval.
- **R5** — the Tier-1 surface is an **allowlist**. A path the guard does not
  recognise is not thereby dangerous; it is one it cannot vouch for, so
  self-landing is refused on it rather than granted by default.
- **R12** — a PR that changes the landing machinery may not land itself by it.
- **R13** — a branch that ARMS auto-merge must hold the merge slot in
  `docs/claude/session-board.json`, claimed in its own diff. Arming is not a
  request to merge, it **is** the merge. The `PreToolUse` merge-slot guard in
  `.claude/settings.json` matches only `mcp__github__merge_pull_request` and
  `mcp__github__enable_pr_auto_merge`, and the arming route calls **neither** —
  the merge is performed by `claude-pr-automerge.yml` under `GITHUB_TOKEN`, so
  no hook fires even in the runtimes that do load hooks. R6 therefore mandates
  the one landing route on which the slot guard is structurally silent.
  ⚠️ R13 makes that claim **attributable and fails-closed**; it does **not**
  serialize. A committed claim reaches no other session until the branch merges
  (`BL-20260810-MERGE-SLOT-MIRROR-UNWRITABLE-PRE-MERGE`), so concurrent-merge
  safety still rests on branch-protection required status checks.
- **R8** — `changes_landing_machinery` is verified against the diff, with the
  branch's own declaration excluded from the evidence.

Branches cut before the guard existed report `undeclared_predates_guard` — a
**pass on age**, printed loudly. The guard arms itself as they drain; there is
no flag to unset.

⚠️ **A PR opened through `pr-opener` starts with ZERO checks** (GitHub fires no
workflows for `GITHUB_TOKEN` pushes) and auto-merge merges on **green**, so it
waits forever until checks exist. Push one ordinary commit **after** the PR
exists to arm CI, and read CI with `get_check_runs`, never `get_status`.

---

## Quick-reference cheat sheet

| Workflow | Autonomy | Trigger pattern | Label / sentinel |
|---|---|---|---|
| `guards.yml` | AUTO | PR/merge_group/schedule `29 */2 * * *` (no push since CI-STREAMLINE 2026-11-03) | — (**required check**; runs every id below) |
| `pytest-collect.yml` | AUTO | PR (no push since CI-STREAMLINE 2026-11-03) | — |
| `ruff-lint` | AUTO | PR/push | — |
| `secret-scan` | AUTO | PR/push | — |
| `dry-run-guard` | AUTO | PR | — |
| `env-gate-guard` | AUTO | PR | — |
| `silent-empty-guard` | AUTO | PR | — |
| `arch-doc-guard` | AUTO | PR | — |
| `repo-inventory.yml` | AUTO | daily schedule `47 4 * * *` + dispatch (off PRs and push since CI-STREAMLINE 2026-11-03) | — |
| `bootstrap-labels.yml` | AUTO / AUTONOMOUS | push (paths: this file) + B-sentinel or `workflow_dispatch` | `.github/triggers/bootstrap-labels` |
| `branch-protection-sync.yml` | AUTO | push to `main` + workflow_dispatch | — |
| `health-snapshot.yml` | AUTONOMOUS | A or E (every 6h) | `health-snapshot-trigger` |
| `dashboard-edge-watch.yml` | AUTONOMOUS | A or E (hourly) | `dashboard-edge-watch-now` |
| `vm-diag-snapshot.yml` | AUTONOMOUS | A | `vm-diag-request` |
| `trainer-vm-diag.yml` | AUTONOMOUS | A | `trainer-vm-diag-request` |
| `vm-web-api-recover.yml` | AUTONOMOUS | A | `vm-web-api-recover` |
| `vm-net-diag.yml` | AUTONOMOUS | A | `vm-net-diag-request` |
| `prune-merged-claude-branch.yml` | AUTONOMOUS | A or `workflow_dispatch` | `prune-merged-branch` |
| `doc-audit-weekly.yml` | AUTONOMOUS | A or E (Mon 12:00 UTC) | `doc-audit-now` |
| `vwap-backtest.yml` | AUTONOMOUS | A | `vwap-backtest-trigger` |
| `system-actions.yml` | OPERATOR-APPROVAL | A | `system-action` |
| `system-actions-cancel-guard.yml` | AUTO | `workflow_run` (system-actions completed, cancelled) | — |
| `infra-runner-install.yml` | OPERATOR-APPROVAL | A (owner-opened) or `workflow_dispatch` | `infra-runner-install` |
| `infra-runner-smoke.yml` | AUTONOMOUS | A (owner-opened) or `workflow_dispatch` (runs ON the self-hosted `jta-infra` runner; arms `vars.INFRA_RUNS_ON` on green) | `infra-runner-smoke` |
| `infra-runner-health.yml` | AUTO | E (every 15 min; hosted fallback for `vars.INFRA_RUNS_ON` when no `jta-infra` runner is online) | — |
| `vm-net-fix.yml` | OPERATOR-APPROVAL | A | `vm-net-fix-request` |
| `training-rerun-5m.yml` | OPERATOR-APPROVAL | push to experiment paths | — |
| `purge-artifacts.yml` | AUTO | E (daily 03:00 UTC) + C (workflow_dispatch) + A (`purge-artifacts-now`) | `purge-artifacts-now` |
| `prune-landed-branches.yml` | AUTONOMOUS | C (workflow_dispatch) + A (`prune-landed-branches`) | `prune-landed-branches` |

---

## Workflow Catalogue

### CI / PR guards (all AUTO)

These run on every PR or push to `main`. Claude never triggers them;
they self-fire. Touching a guard's own logic is **Tier 3**.

> ⚠️ **These are guard *ids*, not workflow files.** Every static guard below
> runs as a step inside the single **`guards.yml`** job — its registry is
> [`scripts/ci/run_guards.py`](../scripts/ci/run_guards.py) and its failure-path
> self-tests are in [`scripts/ci/guard_selftests.py`](../scripts/ci/guard_selftests.py).
> The per-guard workflow files this table used to name (env-gate-guard.yml,
> secret-scan.yml, … — deliberately unbackticked here, because they are not
> files) **do not exist**: they were consolidated into one job by
> BL-20260806-CI-FANOUT-AMPLIFIES-ACTIONS-OUTAGES, after a single PR asking for
> ~29 hosted runners left 28 of them queued through an Actions incident. The
> `.yml` suffixes were left behind in this table until 2026-08-21, so a reader
> looking for the file that runs a guard found a plausible name, no file, and no
> pointer to the real one. The `workflow-catalog` guard now fails CI on a name
> here that is not a real file.

| Guard id (runs inside `guards.yml`) | Trigger | Purpose | Required on `main`? |
|---|---|---|---|
| `pytest-collect.yml` | PR (push `main` removed 2026-11-03, CI-STREAMLINE: the PR run already collected the merged tree; the pytest-run backstop collects `main`) | `pytest --collect-only` — surfaces import/collection failures. | Yes |
| `pytest-run.yml` | PR, schedule `13 */2 * * *` (push `main` removed 2026-11-03, CI-STREAMLINE: it re-tested an already-approved tree; the schedule is now the ONLY post-merge full run) | `pytest -q tests/` — runs the **full** suite (collection only checks imports) unless the diff is **data-only** (only the test files that read those trees; CI-DIET, 2026-10-13) or, on a **pull_request**, a code diff the import graph can place (only the affected test files; GH-CAPACITY-PR-CI-FANOUT, 2026-10-15). The schedule is the post-merge backstop: full suite on `main`'s HEAD unless its code is already graded. See below. Required since 2026-05-22 (#1721). | Yes |
| `ruff-lint` | PR, push `main` | `ruff check` with rules from `ruff.toml`. | Yes |
| `secret-scan` | PR, push `main` | `scripts/secret_scan.py` over every tracked file. | Yes |
| `dry-run-guard` | PR to `main` | Fails PRs that flip dry-run flags, silently downgrading live mode. Telegrams operator on hit. | Yes |
| `env-gate-guard` | PR to `main` | Fails PRs adding env-gate reads in protected files without `# allow-silent: <reason>`. | Yes |
| `silent-empty-guard` | PR to `main` | Fails PRs adding broad `except` handlers in protected read-paths without justification. | Yes |
| `canonical-config-loaders` | PR to `main` | Fails PRs that add a hand-rolled parser for `config/accounts.yaml` outside the canonical loader module. | Yes |
| `canonical-db-resolver` | PR to `main` | Fails PRs that add an inline `trade_journal.db` path fallback outside the canonical resolver. | Yes |
| `arch-doc-guard` | PR to `main` | Emits `::warning` when high-impact subsystems change without an architecture-doc update. Always exits 0 (advisory). | No |
| `repo-inventory.yml` | daily schedule on `main` + dispatch (PR and push removed 2026-11-03, CI-STREAMLINE: its per-PR run was cancelled in checkout under load and ci_settle read that as no verdict) | Uploads `scripts/repo_inventory.py` output as build artifact. Advisory only. | No |

`REQUIRED_CONTEXTS` in `branch-protection-sync.yml` is the authoritative
list of blocking checks — **read it there, this copy is a convenience mirror.**
As of 2026-08-21 there are **three**:
`["pytest-collect","pytest-run","guards"]`.

#### `pytest-run` scope (CI-DIET, 2026-10-13)

`pytest-run` decides, per diff, how much of the suite to execute (`scripts/ci/pytest_run_scope.py`, pinned by
`tests/test_pytest_run_scope.py`). The job id, name and required context are unchanged, so branch protection and
`claude-pr-automerge` treat it exactly as before; every run states its scope in the job summary.

| mode | when | what runs |
|---|---|---|
| `none` | no changed path matches the relevance filter in the workflow (`tests/test_pytest_run_filter.py`) | nothing; the summary says it passed without running tests, by design |
| `data` | every suite-relevant changed path is on the explicit data allowlist: `docs/claude/work/checklist/`, `docs/claude/work/pipeline/`, `docs/claude/work/PIPELINE.jsonl`, `research/queue/*.yaml`, `research/results/`, `comms/` (not `comms/schema/`), `.github/pr-landing/`, `.github/pr-automerge-requests/`, `.github/merge-slots/` | every test file whose text mentions those trees (`--select-tests`; 155 of ~1,440 files on 2026-10-13), selected by content, never by a hand list |
| `full` | anything else: `.py`, `config/`, `src/`, `scripts/`, `tests/`, `.github/workflows/`, `comms/schema/`, the enumerated docs the suite reads (`docs/ARCHITECTURE-CANONICAL.md`, ...) | the whole suite, as before |
| `affected` | **pull_request only**, a code diff with no fallback trigger (GH-CAPACITY-PR-CI-FANOUT, operator 2026-10-15: "Yes, affected tests on PRs") | the test files the import graph says can observe the change: transitive importers, dotted-string and `import_module` prefix loaders, path/basename readers, plugin-fixture users, tree scanners. **Falls back to `full`** on conftest, requirements/pyproject, `.github/`, `scripts/ci/`, guard scripts, config-named modules, every-test (conftest-eager) modules, fan-in or selection >50% of test files, or any selector error. Pinned by `tests/test_pytest_run_affected.py` |

**Post-merge backstop** (`schedule`, every 30 min, `scripts/ci/pytest_run_backstop.py`, pinned by
`tests/test_pytest_run_backstop.py`). Push runs alone do not grade every merge: an auto-merged (`GITHUB_TOKEN`) merge
commit starts no run, and the next push run's `before...sha` range begins at that commit. Each tick runs the full suite on
`main`'s HEAD unless a completed full run on an ancestor is followed only by suite-neutral or data-only commits (or a full
run on HEAD is in flight); "could not look" runs the suite. A red push/schedule run on `main` pages via
`claude-run-failure-alert`. Bound: a post-merge break is detected within ~30 min + the suite's run time + runner queueing.

Measured motive: 179 of 233 commits that landed on `main` in the 48h to 2026-10-13 (77%) were data-only and each paid the
full ~36-minute suite twice (PR, then push). The `guards` job is not scoped by this and still runs on every PR and push.
Widening the allowlist widens what skips the full suite; state why in the PR.

Both `full` and `data` runs execute under `pytest-xdist` (`-n auto --dist loadfile`, 4 vCPU on the hosted runner): the same
tests, scheduled across workers with every test file kept whole on one worker. Measured on three probe runs of the full
suite: 11.7 / 13.0 / 20.5 min wall against 33-46 min serial. It is a scheduling change only (pinned by
`tests/test_pytest_run_scope.py`: no `-k`/`-m`/`--deselect`); parallel scheduling exposed two cross-test pollution bugs
(a `sys.modules` deletion and a Bybit tick/lot cache poisoned by mock clients), fixed in the tests rather than by
deselecting. A new order-dependent test will now fail intermittently: fix the test's isolation, do not rerun until green.


> ⚠️ **This mirror said "15 required contexts" until 2026-08-21 and had been
> wrong since the guard consolidation.** The 13 individual guard contexts it
> listed were replaced by the single `guards` context in the same commit that
> created `guards.yml` — a required context that no longer exists leaves every
> PR hanging forever, so `branch-protection-sync.yml` had to be updated
> atomically with it, and this mirror was simply missed. A stale mirror of a
> gating list is the dangerous direction: it invites a session to expect checks
> that cannot run. `repo-inventory` also runs on every PR but is **advisory**
> and deliberately NOT required — folding it into the required set would start
> gating merges on an artifact upload.

---

### Repo / branch admin

#### `prune-landed-branches.yml`

**Autonomy:** AUTONOMOUS (Claude dispatches via labelled issue; operator
may dispatch via the Actions UI).

**Trigger:** `workflow_dispatch` + `issues.opened` filtered to label
`prune-landed-branches`.

**Purpose:** Deletes remote branches listed in
`docs/claude/pruned-branches-manifest.txt`.

⚠️ **It exists because a Claude web session CANNOT delete a ref.**
Measured 2026-08-24: `git push origin --delete <branch>` returns **HTTP
403** from the session's git proxy while ref *creation* works, and the
hosted GitHub MCP ships `create_branch` with no delete counterpart. So
every session adds branches and none can remove them — which is how the
bot repo reached **282**, 149 of them provably landed
(`BL-20260824-SESSION-GIT-PROXY-CANNOT-DELETE-A-REMOTE-BRANCH`). A
runner's `GITHUB_TOKEN` has the `contents: write` the delete needs.

**Four guards, and the SHA one is the point:**
1. **SHA-pinned.** A branch whose tip has MOVED since the manifest was
   written is SKIPPED, never deleted — `--force-with-lease` applied to
   deletion. Without it a manifest generated days earlier silently
   authorises deleting work added since.
2. **Open-PR guard.** Any branch that is the head of an open PR is
   skipped even if the manifest names it.
3. **Default-branch guard.** `main` / `master` / the repo's actual
   default are refused unconditionally.
4. **Dry run by default.** On BOTH triggers. Only a literal
   `dry_run: false` applies; anything else — including a typo — fails
   SAFE. Opening the issue can never itself destroy anything.

It also **refuses a manifest that parses to zero rows**, rather than
reporting a successful run that deleted nothing — the failure mode the
guard family calls an unasserted denominator.

**Recovering a deletion:** every tip SHA is in the manifest and GitHub
retains the head SHA of a closed PR, so
`git push origin <sha>:refs/heads/<branch>` restores any row.

**Verifying it worked:** re-count the remote (`git ls-remote --heads`),
never the workflow's own summary. The 403 above prints
`Everything up-to-date` immediately after `fatal:`, and a batch loop that
pipes the push into `tail` tests *tail's* exit code — that combination
reported "deleted: 146" having deleted zero.

#### `purge-artifacts.yml`

**Autonomy:** AUTO (daily cron) / AUTONOMOUS (Claude dispatches via
labelled issue; operator may dispatch via the Actions UI for a custom
window).

**Trigger:** `schedule` (daily 03:00 UTC) + `workflow_dispatch` +
`issues.opened` filtered to label `purge-artifacts-now`.

**Purpose:** Reclaims GitHub Actions storage by deleting build
artifacts. The free plan ships **0.5 GB** of Actions storage; once
that fills, GitHub bills overage (or blocks the account if a $0 budget
is set). Lowering `retention-days` on a producing workflow only affects
*future* uploads — already-uploaded artifacts keep their original
retention until expiry. This workflow deletes them now.

**Behaviour:**
- **Scheduled run** (03:00 UTC daily) deletes artifacts older than
  **7 days**. Acts as a safety net so storage stays trimmed even if a
  future workflow re-introduces a long retention.
- **Manual dispatch** takes two inputs:
  - `older_than_days` — `0` deletes ALL artifacts (one-shot recovery
    when storage is full). `N > 0` deletes anything older than N days.
  - `dry_run` — `true` logs the candidate set without calling DELETE.
- **Issue-driven** (Claude path, since the hosted GitHub MCP has no
  `workflow_dispatch`): open an issue with label
  `purge-artifacts-now`. Empty body → one-shot total purge
  (`older_than_days=0`, `dry_run=false`); body may override with
  `older_than_days: <N>` / `dry_run: <true|false>` lines. Result table
  posts back as an issue comment, then the issue is closed. The reply
  step uses `if: always()` so cancelled runs (e.g. job timeout) still
  emit a `⏱` status note — never silently hung.

**Performance:** deletes run in **parallel chunks of 10** via
`Promise.all`. Job timeout is **60 minutes**, sized for the one-shot
total-purge recovery scenario (thousands of artifacts on a maxed-out
500 MB cap); scheduled daily runs at 7-day retention finish in
seconds.

**Companion:** every artifact-uploading workflow in this repo is now
capped at ≤ 7 days retention (most at exactly 7; `repo-inventory.yml`
at 3; `get-diag-token.yml` at 1). Run logs persist 90 days
independently and are the durable audit trail; artifacts are bounded
working state, not records.

---

#### `bootstrap-labels.yml`

**Autonomy:** AUTO (self-fires on merge of this file) / AUTONOMOUS (Claude
may re-run via B-sentinel if a label gets deleted).

**Trigger:** `push` to `main` (paths: this file) + `workflow_dispatch`.

**Purpose:** Idempotently creates all labels that other workflows filter
on. Safe to re-run at any time; existing labels are left alone.

**MCP trigger (re-run if label deleted):**
```
mcp__github__create_or_update_file
  path: .github/triggers/bootstrap-labels
  message: "chore: re-sync labels"
  branch: main
```
Or just touch `.github/workflows/bootstrap-labels.yml` in a PR to main.

**Current label set:** `vm-diag-request`, `vm-web-api-recover`,
`system-action`, `vm-net-diag-request`,
`vm-net-fix-request`, `health-snapshot-trigger`, `cf-worker-deploy`,
`doc-audit-now`, `doc-drift`,
`vwap-backtest-trigger`, `trainer-vm-diag-request`.

---

#### `branch-protection-sync.yml`

**Autonomy:** AUTO (self-fires on every push to `main`) + `workflow_dispatch`.

**Trigger:** `push` to `main` (every merge) and `workflow_dispatch`. A
change to `REQUIRED_CONTEXTS` takes effect automatically on the next push
to `main` — no operator click required. This is how the 2026-05-22
`pytest-run` promotion (#1721) applied: the merge to `main` ran this
workflow, which PUT the updated contexts.

**Purpose:** PUTs the branch-protection spec for `main` idempotently.
Hardcoded `REQUIRED_CONTEXTS` is authoritative.

**Secrets:** `BRANCH_PROTECTION_TOKEN` (classic PAT, `repo` scope —
**operator-stated 2026-09-29, not measured**; earlier text here and in the
secrets table said fine-grained `administration:write`, which the operator
corrected). ⚠️ A classic `repo` token grants admin on every repo the owner
administers, so it is broader than a fine-grained `administration:write` token;
the operator chose to keep ONE token across all its workflows (JC-SA-05 option
b, 2026-09-29: "Leave it as one token, I'm not splitting it"). Unset → the
workflow no-ops (skips the PUT and leaves protection unchanged).

**MCP trigger:** none needed — it self-fires on merge to `main`.
`workflow_dispatch` is available to the operator in the Actions UI as a
manual re-sync. To read the live protection state from a PM-side session,
fire the `branch-protection-report.yml` relay (open a `[bp-report]` issue).

---

### Health & diagnostics

#### `health-snapshot.yml`

**Autonomy:** AUTONOMOUS.

**Trigger:** Schedule every 6h (cron `0 */6 * * *`), `workflow_dispatch`,
and `issues.opened` with label `health-snapshot-trigger`.

**Purpose:** SSHes into the **live VM**, runs
`scripts/collect_health_snapshot.sh`, uploads artifact. The
`/health-review` skill reads pasted-by-operator artifact content (not
repo-resident), so no merge step is needed.

**MCP trigger (autonomous, Pattern A):**
```
mcp__github__issue_write
  title: "[health-snapshot] on-demand snapshot"
  body: "reason: Claude-initiated snapshot for health review"
  labels: ["health-snapshot-trigger"]
```
Workflow SSHes, uploads artifact, comments result URL, closes issue.

**Secrets:** `VM_SSH_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

---

#### `dashboard-edge-watch.yml`

**Autonomy:** AUTONOMOUS — read-only outside-in probe, no operator approval
needed.

**Trigger:** Schedule hourly (`12 * * * *`), `workflow_dispatch`, and
`issues.opened` with label `dashboard-edge-watch-now`.

**Purpose:** E52 — the outside-in probe of the three links in front of
`ict-web-api-watchdog`'s coverage on the SPA's only path to the API
(GitHub Pages -> HTTPS -> `ict-bot.duckdns.org` -> Caddy -> `ict-web-api`):
(1) a cheap ungated `GET /api/health` returns 200 over a chain that verifies;
(2) days remaining on the served TLS certificate (warn < 14, alert < 7); (3)
the DuckDNS `A` record for `ict-bot.duckdns.org` still equals the canonical
live VM IP (`vars.VM_SSH_HOST`, see
[`docs/runbooks/live-vm-ip-single-source.md`](runbooks/live-vm-ip-single-source.md));
and (4, optional, always run) the CORS preflight from the Pages origin still
allows `Authorization` (the same check
[`docs/runbooks/webapp-https-caddy.md`](runbooks/webapp-https-caddy.md) §
Verify documents by hand). Runs entirely from the GitHub-hosted runner — no
SSH, so a wedge that also breaks VM-side monitoring is still observed.

**Collapsed-state contract:** every check grades into `ok` / `warn` / `alert`
/ `unreachable`, never collapsed — "the probe did not run" (DNS timeout,
socket refused, an uncaught exception mid-check) is its own state and is
never folded into `ok`. Every run uploads a JSON receipt artifact
(`dashboard-edge-watch-receipt-<run_id>`, 7-day retention) so "ran and found
healthy" stays distinguishable from "did not run" even when the alert path
itself is silent. See `scripts/ops/dashboard_edge_watch.py`'s module
docstring for the full contract; `--self-test` plants an expired-cert fixture,
a wrong-IP fixture, a non-200 fixture and a missing-`Authorization`-header
fixture and asserts each produces its alert, with no network. Job fails
(red in the Actions UI) whenever the overall verdict is not `ok`, alongside
a Telegram ping and a deduped `dashboard-edge-watch-alert`-labelled issue
(opened once, commented on while still broken, auto-closed on recovery) — the
same shape as `macro-producer-liveness.yml`. Also watched by
`claude-run-failure-alert.yml` — a silent watchdog is worse than none.

**MCP trigger (autonomous, Pattern A):**
```
mcp__github__issue_write
  title: "[dashboard-edge-watch] on-demand probe"
  body: ""
  labels: ["dashboard-edge-watch-now"]
```

**Secrets:** `CLAUDE_TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (alert path
only — the checks themselves need no secret, since the target endpoints are
public).

---

#### `vm-diag-snapshot.yml`

**Autonomy:** AUTONOMOUS — read-only relay, no operator approval needed.

**Trigger:** `issues.opened` (label `vm-diag-request`), `workflow_dispatch`.

**Purpose:** Hits `/api/diag/<path>` on the live VM via SSH tunnel, posts
the JSON response as an issue comment, closes the issue. The PM-side
session's primary window into the live VM.

**Issue format:**
```
title: "[diag-request] <path-and-query>"
body: (empty body is fine; the path comes from the title)
labels: ["vm-diag-request"]
```

Examples:
```
title: "[diag-request] snapshot?limit=200"
title: "[diag-request] audit?limit=50"
title: "[diag-request] status"
title: "[diag-request] journalctl?unit=ict-trader-live.service&lines=100"
```

**Full pattern:** [`docs/claude/diag-relay.md`](claude/diag-relay.md).

**Secrets:** `VM_SSH_KEY`, `DIAG_READ_TOKEN`.

---

#### `trainer-vm-diag.yml`

**Autonomy:** AUTONOMOUS — trainer VM is fully autonomous Claude territory.
Claude may open these issues at any time without operator approval.

**Trigger:** `issues.opened` (label `trainer-vm-diag-request`),
`workflow_dispatch`.

**Purpose:** Unrestricted SSH relay into the **trainer VM**
(`158.178.209.121`). Runs any bash command, posts full output as issue
comment, closes issue. Commands delivered via stdin (no shell injection).

**Issue format:**
```
title: "[trainer-diag] <description>"
body: |
  cmd: <bash command>
labels: ["trainer-vm-diag-request"]
```

Multi-line commands:
```
body: |
  cmd: |
    cd /home/ubuntu/ict-trading-bot
    tail -n 200 runtime_logs/trainer/dataset_builds.jsonl
```

**MCP trigger (Pattern A):**
```
mcp__github__issue_write
  title: "[trainer-diag] check trainer service status"
  body: "cmd: journalctl -u ict-trainer.service -n 100 --no-pager"
  labels: ["trainer-vm-diag-request"]
```

**Common commands Claude uses autonomously:**
- `journalctl -u ict-trainer.service -n 100 --no-pager` — service log
- `cat runtime_logs/trainer/dataset_builds.jsonl | tail -50` — build log
- `python -m ml.registry list` — registry state
- `ls -la ml/models/` — model artifact inventory
- `systemctl status ict-trainer.service ict-trainer.timer` — service state
- `df -h && free -m` — resource usage
- `cat /etc/ict-trainer-vm.role` — role marker verification

**Full permission scope:** `docs/claude/trainer-vm-mode.md` § 9.

**Secrets:** `VM_SSH_KEY`. **Variables:** `TRAINER_VM_IP` (default
`158.178.209.121`), `TRAINER_VM_USER` (default `ubuntu`).

---

### VM operations

#### `system-actions-cancel-guard.yml`

**Autonomy:** AUTO — runs on its own; never executes or re-files an action, it only comments
and alerts.

**Trigger:** `workflow_run` on `system-actions` completing with conclusion `cancelled`
(issue-triggered runs only).

**Purpose:** OA-17 (2026-10-04). GitHub keeps one pending run per concurrency group, so a newer
request in the shared mutating lane cancels an older pending one. This reads the issue number the
run's `route` job uploaded (`system-action-request` artifact) and runs
`scripts/ops/system_action_cancel_guard.py`: a run whose main job never started and whose issue is
still open gets a **"CANCELLED, NOT RUN"** comment naming the displacing run and one direct
Telegram alert, and is NOT re-queued (that would invert request order); a run that had started is
commented on only; a closed issue is left alone. See `docs/claude/system-actions.md` § 7.2.

#### `system-actions.yml`

**Autonomy:** OPERATOR-APPROVAL — always confirm with operator before opening
this issue. Tier-1 actions (`status-check`, `pull-latest-logs`) need only
in-conversation approval; Tier-2 actions (`pull-and-deploy`,
`restart-bot-service`, `reboot-vm`, `set-account-mode`) need explicit
operator ack.

**Trigger:** `issues.opened` (label `system-action`), `workflow_dispatch`.

**Purpose:** Single bridge for the allowlisted mutating live-VM operations.
Runs via SSH; logs a JSON audit artifact (pre-/post-state). The issue body
is passed verbatim through `ISSUE_BODY` env var.

**Issue format:**
```
title: "[system-action] <action-name>"
body: |
  action: <name>
  reason: <text>
labels: ["system-action"]
```

For `set-account-mode`:
```
body: |
  action: set-account-mode
  account: bybit_2
  mode: live
  reason: <operator-approved reason>
```

**Allowlisted actions:**
- `status-check` — read-only health dump (Tier 1)
- `pull-latest-logs` — fetch recent log files (Tier 1)
- `pull-and-deploy` — git pull + restart services (Tier 2)
- `restart-bot-service` — `systemctl restart ict-trader-live.service` (Tier 2)
- `reboot-vm` — full VM reboot (Tier 2)
- `set-account-mode` — flip `mode: live|dry_run` in `accounts.yaml` (Tier 2, sanctioned wire)

**Full contract:** [`docs/claude/system-actions.md`](claude/system-actions.md).

**Secrets:** `VM_SSH_KEY`, `DIAG_READ_TOKEN`.

---

#### `prune-merged-claude-branch.yml`

**Delete a stray `claude/**` branch whose content is already on `main`.**
Dry-run by default; `apply: true` deletes.

Exists because a session's git credential can create and update refs but is
**refused on delete** — measured 2026-08-25, `git push origin --delete`
returned `HTTP 403` on four attempts with backoff while a normal push from the
same credential in the same minute succeeded. A stray branch was therefore
handed to a human by two separate sessions. No human judgement is required, no
secret must be minted, no broker is involved: a runner's own `GITHUB_TOKEN` can
do it and nobody had built the wire, which is precisely the
`defaulted_to_human` class in
[`docs/claude/operator-owed-register.json`](claude/operator-owed-register.json).

Guards, because deleting a ref is not reversible from here: `claude/**` only
(anything else is refused before the checkout is used); dry-run unless
`apply: true`; a typo'd `apply`/`force` value is REFUSED rather than read as
off; and the run **prints** the unmerged-commit list plus `git cherry`
patch-equivalence and refuses when commits remain unless the body carries BOTH
`force: true` AND a `reason:` naming what carried the content. That waiver
exists because this repo **squash-merges** — a squashed branch never becomes an
ancestor of `main`, so an ancestor-only test would refuse every genuine
request. It is the `cancel-ib-order` shape: a documented override with its
reason in the run log, never a silent default. The post-delete check re-reads
the ref and reports `deleted_unconfirmed` rather than success if it still
resolves.

Issue body:

```
branch: claude/some-stray
apply: true
force: true
reason: content landed via PR #10276 — both rows byte-identical on main
```

#### `vm-web-api-recover.yml`

**Autonomy:** AUTONOMOUS — self-heal when the web API is down (curl exit 7).
No operator approval needed; restart-only, no edits.

**Trigger:** `issues.opened` (label `vm-web-api-recover`).

**Purpose:** `systemctl restart ict-web-api.service` + health probe on the
live VM. Fires when `/api/diag/*` returns curl exit 7 (FastAPI down).

**MCP trigger (Pattern A):**
```
mcp__github__issue_write
  title: "[vm-web-api-recover] web API is down — exit 7"
  body: "Diag relay returning curl exit 7; restarting ict-web-api.service."
  labels: ["vm-web-api-recover"]
```

**Secrets:** `VM_SSH_KEY`.

---

#### `sync-vm-secrets.yml`

**Autonomy:** TIER-2 (one operator OK in chat). **Canonical broker-credential
propagation path** (added 2026-06-02). One workflow mirrors the full declared
set of broker-credential Actions secrets to the live trader's `.env` and
restarts the trader. Adding a new broker = append env-var names to
`REQUIRED_SECRETS` or `OPTIONAL_SECRETS` in the workflow + `SYNC_REQUIRED`/
`SYNC_OPTIONAL` in `scripts/ops/sync_vm_secrets.sh`. No per-broker workflow
file.

**Trigger:** `workflow_dispatch` (operator UI / Claude via Actions API).

**Purpose:** Idempotent Actions → VM env-file mirror via SSH `SendEnv` —
secret values never reach run logs or audit artifacts. Restart fires only
when the `.env` actually changed. Replaces the per-account pattern of the
legacy `rotate-account-keys.yml` (still in place as the Bybit-only path
pending migration).

**Secrets:** `VM_SSH_KEY`, all entries in `REQUIRED_SECRETS` (currently
`BYBIT_API_KEY_1/2`, `BYBIT_API_SECRET_1/2`), and OPTIONAL ones for any
broker that's been onboarded (the broker-credential vars for any onboarded broker).

---

#### `init-actions-secrets.yml`

**Autonomy:** AUTONOMOUS — creates empty placeholder Actions secrets only.
Never reads, logs, or operates on values.

**Trigger:** `workflow_dispatch` (UI / Actions API), `issues.opened` (label
`init-actions-secrets`, added 2026-06-02 / PR #2652).

**Purpose:** Pre-create empty placeholder Actions secret slots so the
operator pastes values into pre-existing slots (Settings → Secrets →
Update) instead of clicking "New repository secret" N times for each new
broker. Already-set names are skipped, never overwritten.

**MCP trigger (Pattern A — issue-label):**
```
mcp__github__issue_write
  title: "[init-actions-secrets] pre-create <broker> placeholders"
  body: |
    names: BROKER_USERNAME,BROKER_PASSWORD,...
    reason: pre-create empty <broker> placeholders for operator-paste flow
  labels: ["init-actions-secrets"]
```

**Secrets:** `BRANCH_PROTECTION_TOKEN` (PAT with `repo` scope — already
provisioned for `branch-protection-sync.yml`; covers Actions-secret writes).

---

#### `vm-net-diag.yml`

**Autonomy:** AUTONOMOUS — read-only network diagnostics.

**Trigger:** `issues.opened` (label `vm-net-diag-request`),
`workflow_dispatch`.

**Purpose:** SSH + port-reachability checks; tests TCP/8001 from the
runner. Posts results as issue comment.

**MCP trigger (Pattern A):**
```
mcp__github__issue_write
  title: "[vm-net-diag] check port 8001 reachability"
  body: "Checking TCP/8001 access from external runner."
  labels: ["vm-net-diag-request"]
```

---

#### `vm-net-fix.yml`

**Autonomy:** OPERATOR-APPROVAL — modifies the live VM's local firewall.

**Trigger:** `issues.opened` (label `vm-net-fix-request`),
`workflow_dispatch`.

**Purpose:** Opens TCP/8001 via `ufw allow` + `iptables -I INPUT ACCEPT`;
verifies post-fix.

**MCP trigger (Pattern A, after operator approval):**
```
mcp__github__issue_write
  title: "[vm-net-fix] open port 8001"
  body: "Operator approved. Opening ufw + iptables for dashboard API port."
  labels: ["vm-net-fix-request"]
```

---

### Trainer VM lifecycle

### Backtesting

#### `vwap-backtest.yml`

**Autonomy:** AUTONOMOUS — backtests on the trainer VM are fully autonomous.

**Trigger:** `issues.opened` (label `vwap-backtest-trigger` or title prefix
`[vwap-backtest]`), `workflow_dispatch`.

**Purpose:** SSHes into the **trainer VM**, fetches fresh 5m BTCUSDT data
from Bybit, runs the VWAP HTF-filter comparison backtest, posts results
as an issue comment. Runs on the trainer VM to avoid compute contention
on the live trader.

**Issue format:**
```
title: "[vwap-backtest] HTF filter comparison — BTCUSDT 5m"
body: |
  compare: true
  days: 365
  num_windows: 8
  window_days: 30
labels: ["vwap-backtest-trigger"]
```

All body keys are optional (all have defaults). Dispatch variant uploads
an artifact.

**MCP trigger (Pattern A):**
```
mcp__github__issue_write
  title: "[vwap-backtest] HTF comparison — latest data"
  body: "compare: true\ndays: 365\nnum_windows: 8\nwindow_days: 30"
  labels: ["vwap-backtest-trigger"]
```

**Secrets:** `VM_SSH_KEY`. **Variables:** `TRAINER_VM_SSH_HOST` (default
`158.178.209.121`).

---

### Documentation

#### `doc-audit-weekly.yml`

**Autonomy:** AUTONOMOUS — Claude may fire an on-demand audit at any time.

**Trigger:** Schedule Monday 12:00 UTC, `workflow_dispatch`, and
`issues.opened` (label `doc-audit-now`).

**Purpose:** Runs `scripts/ops/audit_verification_checklist.py` against
`docs/ARCHITECTURE-CANONICAL.md`. If any `[x]` line references a path
that no longer exists, files a new issue tagged `doc-drift`.

**MCP trigger (Pattern A, autonomous):**
```
mcp__github__issue_write
  title: "[doc-audit] on-demand architecture doc audit"
  body: "reason: Claude-initiated audit — checking for stale paths"
  labels: ["doc-audit-now"]
```

---

### OCI block storage

### Training / ML

#### `training-rerun-5m.yml`

**Autonomy:** OPERATOR-APPROVAL.

**Trigger:** `push` (paths in `experiments/2026-05-07-vwap-accuracy/`),
`workflow_dispatch`.

**Purpose:** Re-runs the VWAP-accuracy experiment at the production 5m
timeframe on a runner with live market-data egress.

---

### Session continuity

## How Claude should use these workflows

**Reading live VM state:**
```
mcp__github__issue_write
  title: "[diag-request] snapshot?limit=200"
  labels: ["vm-diag-request"]
```
Full pattern: [`docs/claude/diag-relay.md`](claude/diag-relay.md).

**Reading trainer VM state (any command):**
```
mcp__github__issue_write
  title: "[trainer-diag] <description>"
  body: "cmd: <bash command>"
  labels: ["trainer-vm-diag-request"]
```
Full pattern: [`docs/claude/trainer-vm-mode.md`](claude/trainer-vm-mode.md) § 9.

**Restarting the web API (live VM, autonomous):**
```
mcp__github__issue_write
  title: "[vm-web-api-recover] web API down"
  labels: ["vm-web-api-recover"]
```

**Triggering a Tier-2 operator action (live VM, approval required):**
1. Confirm operator approval in conversation.
2. Open issue:
```
mcp__github__issue_write
  title: "[system-action] restart-bot-service"
  body: "action: restart-bot-service\nreason: <operator-approved reason>"
  labels: ["system-action"]
```

**Running a VWAP backtest (trainer VM, autonomous):**
```
mcp__github__issue_write
  title: "[vwap-backtest] <description>"
  body: "compare: true\ndays: 365"
  labels: ["vwap-backtest-trigger"]
```

**Firing an on-demand doc audit (autonomous):**
```
mcp__github__issue_write
  title: "[doc-audit] on-demand"
  labels: ["doc-audit-now"]
```

**Adding a CI check:**
Edit/create a workflow under `.github/workflows/`. If it should be a
required status check, add its job ID to `REQUIRED_CONTEXTS` in
`branch-protection-sync.yml` in the same PR.

**Checking workflow output:**
The hosted GitHub MCP does **not** expose `download_artifact` or
`get_run_logs`. For autonomous workflows: consume results from the issue
comment (the workflow posts output there and closes the issue). For
operator-dispatched workflows with artifacts: ask the operator to
download + paste the artifact content.

---

## Modification policy

- Every change to a workflow under `.github/workflows/` must mention
  this doc in the PR body when it changes triggers, secrets, allowed
  actions, or tier classification.
- **New workflows must be listed in this catalogue before merge.**
- New issue-driven workflows must have their label added to `bootstrap-labels.yml`
  in the same PR.
- Removing or weakening a guard workflow (`dry-run-guard`, `env-gate-guard`,
  `silent-empty-guard`, `arch-doc-guard`) is Tier 3 and requires explicit
  operator approval.

---

## Required secrets quick reference

| Secret | Scope | Used by |
|---|---|---|
| `VM_SSH_KEY` | repo | All VM SSH workflows (live VM and trainer VM) |
| `DIAG_READ_TOKEN` | repo | `vm-diag-snapshot`, post-action verification in `system-actions` |
| `BRANCH_PROTECTION_TOKEN` | repo | `branch-protection-sync` and ~40 other workflows (classic PAT, `repo` scope — operator-stated 2026-09-29, not measured; one token by operator decision, JC-SA-05) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | repo | `dry-run-guard`, `env-gate-guard`, `silent-empty-guard` |
| `OCI_CLI_USER`, `OCI_CLI_FINGERPRINT`, `OCI_CLI_TENANCY`, `OCI_CLI_REGION`, `OCI_CLI_KEY_CONTENT` | repo | (none: every consumer, `vm-cloud-fix`, `oci-storage`, `provision-training-vm`, `provision-training-vm-auto-retry`, was deleted 2026-11-06; check whether the secret is still needed) |
| `HF_TOKEN` | repo | (none: `hf-cron` and `training-run` were deleted 2026-11-06; check whether the secret is still needed) |

## Optional repo variables

| Variable | Default | Used by |
|---|---|---|
| `VM_SSH_HOST` | `141.145.193.91` | Live VM SSH workflows |
| `VM_SSH_USER` | `ubuntu` | Live VM SSH workflows |
| `TRAINER_VM_IP` | `158.178.209.121` | `trainer-vm-diag.yml`, `deploy-trainer-bootstrap` (deleted 2026-11-06) |
| `TRAINER_VM_USER` | `ubuntu` | `trainer-vm-diag.yml` |
| `TRAINER_VM_SSH_HOST` | `158.178.209.121` | `vwap-backtest.yml` |

## Complete workflow index (catalog completeness — BL-20260602-003)

The cheat-sheet above covers the day-to-day workflows; this index lists the
**remaining** workflow files so every `.github/workflows/*.yml` is named in this
doc (autonomy levels are the same scale as above — verify against the workflow
header before triggering a mutating one).

| Workflow | Category | Autonomy | Trigger | Purpose |
|---|---|---|---|---|
| `work-store-outbox.yml` | Ops relay | AUTONOMOUS | `issue_comment` on the issue titled `work-store outbox` + cron `41 * * * *` backstop + dispatch | WSD-S3-CLI-OUTBOX (design `docs/plans/WORK-STORE-DESIGN-2026-11.md` § 2.3): applies `scripts/ops/work.py --via outbox` op comments to `POST /api/bot/work/items*` with `WORK_STORE_TOKEN`, idempotent by `op_id`. Applies ONLY comments whose `author_association` is OWNER/MEMBER/COLLABORATOR; marks an applied comment with a rocket, a refused one with confused + a reply. No PR, no repo write. |
| `account-class-guard` | CI guard | AUTO | PR | Fails PR when an accounts.yaml account is missing account_class. |
| `canonical-doc-coherence` | CI guard | AUTO | PR/push | Mechanical guard against governance-doc drift (the doc-coherence 'teeth'). |
| `new-table-wiring-guard` | CI guard | AUTO | PR | Fails+pings when a PR adds a persistent table without wiring it into the canonical store. |
| `writer-conformance-guard` | CI guard | AUTO | PR | Fails+pings when a PR adds a journal writer that bypasses the canonical resolver/conformance. |
| `pytest-rerun.yml` | CI helper | AUTO | `workflow_run` of `pytest-run` (completed) | AUTO-PYTEST-RERUN: reruns a `pytest-run` ONCE per head sha when it was cancelled at the job timeout or died before the tests started (decision: `scripts/ci/pytest_rerun.py`). Never reruns a failed test step. |
| `options-snapshot-capture.yml` | Data pipeline | AUTONOMOUS | cron 21:25 UTC Mon-Fri + dispatch + label `options-snapshot-request` (`mode: capture\|verify\|probe`) | Daily end-of-day option-chain snapshot (bid/ask, IV, greeks; near-the-money strikes, first 3 expiries) for SPY QQQ IWM GLD TLT SLV USO from Alpaca into the trainer's `data/options_history/<UND>/<date>.parquet` (`scripts/ops/capture_options_snapshot.py`). Accrues our own IV history because no keyless one exists (row `OPTIONS-IV-HISTORY-GAP`). Market data only, no order path. A stale/missing underlying turns the run RED (one flag); nothing halts. |
| `sp500-membership-refresh.yml` | Data pipeline | AUTONOMOUS | cron 03:41 UTC on the 2nd of Jan/Apr/Jul/Oct + dispatch + label `sp500-membership-now` | Quarterly rebuild of `config/data_universe/sp500_membership.csv` (point-in-time S&P 500 membership since 2016, removed names kept) from the fja05680/sp500 Updated file (`scripts/ops/build_sp500_membership.py`), landed via `commit-to-main` with `verify-merged`; no PR when unchanged. The source's own newest-snapshot date bounds how fresh the table is. Feeds `config/data_universe.yaml`. |
| `etf-history-pipeline.yml` | Data pipeline | AUTONOMOUS | cron 02:17 UTC Tue-Sat + dispatch + label `etf-history-request` (`mode: probe\|backfill\|refresh\|verify`) | Equity/ETF **1m base** bars (operator 2026-11-01: keep the smallest timeframe; 5m/1h/4h are DERIVED on read) for the ~1,000-symbol universe in `config/data_universe.yaml` (Alpaca Market Data, SIP preferred / IEX fallback, split-adjusted; dividends + splits in a SEPARATE `corporate_actions.csv`), built on a runner that holds the Alpaca secrets and synced in chunks to the trainer's `data/etf_history/<SYM>/1m/<YYYY-MM>.parquet` (`scripts/ops/fetch_etf_history.py`; read-back + freshness `scripts/ops/etf_history_verify.py`; reader `fetch_etf_history.read_bars`). Measures trainer free disk first (needs >=15 GB to start, stops <10 GB mid-run, with numbers). Registered with `schedule_keeper.py`; emits `health.json`. Row `ETF-HISTORY-PIPELINE`. Market data only, no order path. A stale/missing series or failed fetch turns the run RED (one flag); nothing halts, the next run resumes. |
| `diag-relay-sweep.yml` | Ops relay | AUTONOMOUS | label `vm-diag-request` + cron | Sweeps stale, never-answered diag-relay issues (dropped-webhook backstop). |
| `branch-sync.yml` | CI helper | AUTO | push to `main` + dispatch | AUTO-BRANCH-SYNC: after a 90 s debounce, merges `main` into open same-repo `claude/*` PRs that are only behind and declare tier 1 self (`scripts/ci/branch_sync.py`). Needs `BRANCH_PROTECTION_TOKEN`; never rebases or force-pushes. |
| `probes.yml` | Observability | AUTONOMOUS | cron 05:20 UTC + dispatch + issue label `probes-now` | Runs the declared probes on `OPEN-ITEMS.json` `monitoring` rows (`scripts/ops/run_probes.py`, soak predicates via `scripts/ops/probe_soak.py`) and lands `docs/claude/PROBES.json`, then refreshes the due-list so a FAILED probe reaches the duty pass. W2 of the operations plan — it moves the LOOKING off the review session. ⚠️ **A probe REPORTS; a session CLEARS the row** — nothing here writes `verified_at`/`observation` (asserted by an AST control in the runner's self-test), and every probe declares `is_not`: what a PASS still does not establish. Three states never collapsed (`pass`/`fail`/`could_not_run`); a `fail` does NOT fail the run, because most of these rows are open precisely because the thing has not been observed yet and alarming on that is the desensitized-alarm P1. Read-only diag GET. |
| `main-tree-watch.yml` | Observability | AUTONOMOUS | cron hourly at :37 + dispatch | Grades the DEFAULT BRANCH's tree on a cadence, which nothing else did. `guards.yml` carries `push: branches: [main]`, but an auto-merged PR's merge commit is created by `GITHUB_TOKEN` and GitHub starts **no workflow run for it** — MEASURED 2026-09-17 on two disjoint populations: by merge CREDENTIAL, user 5 of 5 produce a push run and `GITHUB_TOKEN` 0 of 24; by commit KIND over a later 5.1h window, PR merges 0 of 31 and `chore(ops)` pushes 9 of 9. ⚠️ **The blind landings are LATE, not uncovered** — `main` is linear so a later run grades the whole tree, all 24 were covered at a median lag of 34.4 min; what this bounds is the gap between consecutive GRADED runs, measured at up to **442.6 min**. ⚠️ **The argument is CORRELATION, not length**: that coverage rides on `chore(ops)` pushes (95 of the last 100 push runs), which stop exactly when the repo is unhealthy. ⚠️ **It runs ONLY the diff-independent probes** (`check_main_tree_health.py`: register-ids R1, backlog-refs `--all`, open-items) — scheduling `run_guards --base main` on a run OF `main` would diff it against itself and pass every diff-scoped guard over an empty diff, a green that checked nothing. ⚠️ **It cannot claim `main` is healthy and says so**: each sub-tool prints which of its rules did NOT run without a `--base`, those statements pass through verbatim, and the runner prints its own caveat under the verdict. ⚠️ **It FAILS ON PURPOSE** — exit 1 a real finding, exit 2 a probe that COULD NOT RUN (*we did not look*, never a clean tree) — so a red run is the mechanism WORKING, the same reading `pr-queue-watch` carries; read the log before filing one as broken. Watched by `claude-run-failure-alert.yml`, enforced by `check_cron_failure_watch.py`. ⚠️ **The cadence is a ceiling, not a promise** — this repo's crons fire late and erratically (`probes.yml`'s first scheduled run was ~4h50m late), so read the run history, never the cron line. Read-only: `permissions: contents: read`, commits nothing. |
| `work-digest.yml` | Observability | AUTONOMOUS | cron 06:20 UTC + dispatch | Renders Phase B's ONE rolled-up daily summary of autonomous work (`scripts/ops/work_digest.py`) and queues it to `docs/claude/pending-pings.jsonl`; the VM's `notify_on_pull.py` drains it on the next `ict-git-sync`. **STATE CHANGES ONLY, NEVER ACTIVITY** — the event definition is IMPORTED from `work_phase_ping.PING_WORTHY` so the per-event path and this roll-up cannot drift; a digest that narrated activity would rebuild the desensitized-alarm failure on a daily cadence. ⚠️ **It sends nothing** — it fails BACK, so an uncommitted row is a digest that never happened, never one wrongly shown as delivered; hence `commit-to-main` with `verify-merged`. ⚠️ **DEPLOYED, NOT OBSERVED**: the script shipped in #10654 with NO trigger (0 of 125 workflow files referenced it) and this is the cron, chosen by the operator 2026-09-01. Its existence is not evidence it fires — `probes.yml` and `due-list` (deleted 2026-11-06) are both enabled with correct cron and have never once fired. Runs at 06:20, after those two, so a digest renders against registers they have already refreshed. |

| `work-digest.yml` | Observability | AUTONOMOUS | cron 06:20 UTC + dispatch | Renders Phase B's ONE rolled-up daily summary of autonomous work (`scripts/ops/work_digest.py`) and queues it to `docs/claude/pending-pings.jsonl`; the VM's `notify_on_pull.py` drains it on the next `ict-git-sync`. **STATE CHANGES ONLY, NEVER ACTIVITY** — the event definition is IMPORTED from `work_phase_ping.PING_WORTHY` so the per-event path and this roll-up cannot drift; a digest that narrated activity would rebuild the desensitized-alarm failure on a daily cadence. ⚠️ **It sends nothing** — it fails BACK, so an uncommitted row is a digest that never happened, never one wrongly shown as delivered; hence `commit-to-main` with `verify-merged`. ⚠️ **DEPLOYED, NOT OBSERVED**: the script shipped in #10654 with NO trigger (0 of 125 workflow files referenced it) and this is the cron, chosen by the operator 2026-09-01. Its existence is not evidence it fires — `probes.yml` HAS since fired on cron (run #34, `event=schedule`, success, 2026-09-01T10:12:17Z) — but ~4h50m LATE against its `20 5 * * *` cron, and once rather than daily. Correct cron syntax is still not evidence of a run; read the run history. Runs at 06:20, after those two, so a digest renders against registers they have already refreshed. |
| `r4-demotion-gate.yml` | Ladder | **Tier-2 runner; its output is a HELD Tier-3 roster PR** | cron `41 7 * * *` + dispatch (`window`, `apply`) | B3: R4 as the Stage-2 DEMOTION gate. Fetches `GET /api/bot/performance?window=30d`, runs `scripts/ops/r4_demotion_gate.py --apply` (R4 `would_block` AND `totalR < 0` -> mirror-window record -> `mandate_resolver` MD-DEMOTE-S2-S1). On a FIRE it pushes an `automation/r4-demotion-<run>` branch with the roster cut (live account + mirror, removal only, never `execution: shadow`) and its evidence, opens a non-draft PR declared `landing: hold`, and opens a `system-action` send-ping issue. ⚠️ It never merges. On no FIRE it writes nothing; the per-leg verdict table is in the step summary. |
| `exit-cell-mandate.yml` | Ladder | **Tier-2 runner; its output is a HELD Tier-3 config PR** | cron `23 8 * * *` + dispatch (`apply`) | PATHB-MANDATE (2026-09-30). Runs `scripts/ops/exit_cell_runner.py`: per leg picks ONE pure-stop `path_b_wf_pass` cell from `docs/research/e35-bracket-corpus.jsonl` (B4 rule), asks `mandate_resolver.resolve_exit_cell` under the GRANTED `MD-SOAK-EXIT-CELL-PATHB` (soak-only legs). On a FIRE: edits ONE key (`atr_stop_mult`) on that leg, flips its coverage-matrix cell, rebuilds its Stage-0 evidence, opens a non-draft `landing: hold` PR and a `send-ping` issue. NEVER merges (no `autoland`). NEEDS-DATA files one pipeline row per clause. Schedule-keeper target. NOT YET OBSERVED RUNNING. |
| `pr-landing-hold-merge-alarm.yml` | Alerting | AUTO | push to `main` | JC-CA-04 (`docs/audits/code-audit-2026-09-27.md` §6, `A09-hold-merge-unenforced`, operator decision 2026-09-28: "Post-merge alarm", option B only). Nothing mechanical stops a session merging a Tier-2/3 PR declared `landing: "hold"` — it can be green on every required check, and merge tools are pre-allowed. This is a DETECTOR, not a gate (option A, a branch-protection/CODEOWNERS block, was declined as too disruptive to every legitimate operator-approved merge). On every push to `main` it finds the PR(s) associated with the pushed commit(s) via the GitHub API, reads each merged PR's `.github/pr-landing/<slug>.json` (already in the tree, the same file `check_pr_landing.py` required pre-merge) and its GitHub reviews, and grades both with the pure decision logic in `scripts/ops/pr_landing_hold_alarm.py`. On ALARM (tier 2/3, `landing: "hold"`, no human `APPROVED` review recorded — a bot's own approval never counts) it opens a `system-action`/`send-ping` issue naming the PR number and title. ⚠️ **Three states, never collapsed**: `clean` / `alarm` / `unreadable` — if the declaration or reviews could not be fetched the JOB FAILS (visible red) rather than silently passing, but does NOT additionally page the operator for a transient API read failure (alarm-fatigue avoidance); a missing declaration on a merged PR is itself graded ALARM (the pre-merge guard may have been bypassed), never read as clean. |
| `schedule-keeper.yml` | Ladder | Tier-1 | push to `main` + cron `7 * * * *` (dispatch floor) + `53 */6 * * *` (paging run) + dispatch | W6-OPS-R (2026-09-27). GitHub creates this repo's scheduled runs ~4-6h late (step change 2026-08-27) and drops many hourly slots. For each target in `scripts/ops/schedule_keeper.py::TARGETS` (r4-demotion-gate, replay-pregate-nightly, strategy-review-packets, grade-closed-trades, soak-book-grade-weekly, live-replay-parity, …) it `workflow_dispatch`es the target on main once its slot is >30 min old with no run since; each target's `dedupe` job skips the late scheduled run of a slot the keeper already ran. The 6-hourly run pages (Telegram) when a target has no completed run inside its window (26h daily / 170h weekly). Changes WHEN targets run, never what they compute. |
| `alpaca-settlement-soak-watch.yml` | Observability | AUTONOMOUS | cron weekdays 14:30 UTC + dispatch | Watches the T+1 cash-settlement soak until it has been EXERCISED, then reports `would_have_reduced_usd` — the figure the operator reads before any Tier-2 flip of `ALPACA_CASH_SETTLEMENT_MODE` to `apply`. Grades against the newest alpaca dispatch so an empty soak is never collapsed: `not_yet_exercised` (no dispatch since deploy — silent, not a failure) vs `never_wrote` (a dispatch DID happen — the finding). Read-only diag GET + one issue comment. |
| `mirror-orphan-watch.yml` | Observability | AUTONOMOUS | cron daily 15:40 UTC + dispatch | Compares each Stage-2 mirror (`alpaca_portfolio`, `bybit_portfolio`) to its live account via `exchange_positions` and fails on a mirror position with no live twin that is not acknowledged in `config/mirror_window_exclusions.yaml` (`scripts/ops/check_mirror_orphans.py`). Unreadable ≠ clean. Read-only diag GET. |
| `broker-bracket-reconcile.yml` | Ops audit | AUTONOMOUS | cron (6h) + dispatch | Runs `scripts/ops/broker_bracket_reconcile.py` against the live book (declared vs resting IB protection). Read-only. RECORDS every run to tracking issue #10089 and COMMENTS only when the graded state moves -- both of the detector's alarm-shaped outputs are true in the steady state, so pinging on either would fire constantly. Silence there means "the same problems", never "no problems". |
| `account-broker-reconcile.yml` | Ops audit | AUTONOMOUS | cron (6h) + dispatch | W6-RECON (2026-09-28, `OI-20260826-JOURNAL-TRUST-COVERS-ONE-ACCOUNT`, operator "Build automated reconcile"). Runs `scripts/ops/account_broker_reconcile.py` for `alpaca_live` / `breakout_1` / `bybit_2` (as far as its API allows): open positions, protective-leg coverage, and realized P&L (alpaca reports `not_exposed` -- no broker-side realized-P&L read exists in this codebase; breakout_1 is a DAILY figure via `realized_today`, not last-N-trade; bybit_2 reuses the `bybit_wallet_truth` measured_api floor already documented as SUB-subaccount-partial by `PI-20260924-ZROYCDY4-0001`). Read-only. Same record-every-run / comment-only-on-fingerprint-change design as `broker-bracket-reconcile.yml`, its own tracking issue (label `account-broker-reconcile`). |
| `broker-truth-freshness.yml` | Ops audit | AUTONOMOUS | cron (6h) + dispatch | LEDGER-REFRESH (2026-10-10). Grades `comms/broker_truth_ledger.json` freshness via `scripts/ops/broker_truth_freshness.py` (fresh / declared_gap / stale / could_not_look; a stale record with no declared gap, or whose live API block is silent, is the one finding) and records the daily journal-vs-wallet delta for `bybit_1` / `bybit_portfolio` (`scripts/ops/journal_vs_wallet_delta.py`). Read-only; one tracking issue (label `broker-truth-freshness`), comment only on fingerprint change. |
| `oi-feed-freshness.yml` | Ops audit | AUTONOMOUS | cron (2h) + dispatch | E4-DEMO-LEG (2026-10-30). Grades the live open-interest feed the `e4_oi_shock_1h` leg reads (`/api/diag/log_file?name=oi_feed_status`) per declared symbol via `scripts/ops/oi_feed_freshness.py` (fresh / cold / stale / could_not_look; a missing symbol is could_not_look, never fresh). Read-only; one tracking issue (label `oi-feed-freshness`), comment only on graded-state change. |
| `arm-candidate-diag.yml` | Migration relay | AUTONOMOUS | label `arm-candidate-diag-request` | SSH diag/verification relay for the Ampere migration candidate VM. |
| `vm-bybit-diag.yml` | Ops relay | AUTONOMOUS | label `vm-bybit-diag-request` | One-shot bybit_2 ErrCode 10010 ('Unmatched IP') diagnostic. |
| `prop-report.yml` | Ops relay (write) | OPERATOR-APPROVAL | label `prop-report` | Inbound Breakout prop fill/close report-back → POST /api/bot/prop/report (Tier-2). |
| `get-diag-token.yml` | Secret→owner | OPERATOR-APPROVAL | label `get-diag-token` / dispatch | Deliver the DIAG_READ_TOKEN value to the repo owner (run artifact / issue comment). ⚠️ **GATED ON `repository.private`, FAIL-CLOSED — refuses on a PUBLIC repo AND on an unreadable visibility.** This repo is public, so it refuses today; that is the feature. Until 2026-08-25 it wrote a live bearer to a world-readable surface (BL-20260818-GET-DIAG-TOKEN-EMITS-SECRET-TO-PUBLIC-SURFACE). It had **no row in this table** before that date — it was "named" only by an incidental artifact-retention line, which the catalog guard counts (Direction A matches a bare filename anywhere). |
| `set-diag-token.yml` | Secret→VM | OPERATOR-APPROVAL | label `set-diag-token` | Push DIAG_READ_TOKEN secret onto the live VM + restart web-api. Reports a four-state `rotation_state` (`rotated`/`unchanged`/`unknown_before`/`failed`) from a before/after fingerprint of what the VM SERVES — read that, never the run being green (BL-20260818-SET-DIAG-TOKEN-REPORTS-NEW-ON-UNCHANGED-VALUE). |
| `cancel-queued-runs.yml` | Repo housekeeping | AUTONOMOUS | label `cancel-queued-runs` / dispatch | Bulk-cancel stale `queued` runs that never got a runner. |
| `branch-protection-report.yml` | Ops relay (read-only) | AUTONOMOUS | label `bp-report` | Report GitHub **admin** state the hosted MCP cannot surface — branch protection, required status checks, `enforce_admins`. A PM-side session has no tool for this and no admin token in its shell, so without it a session is blind to whether a required check is actually enforcing. Read-only; changes nothing. |
| `rotate-account-keys.yml` | Secret→VM (legacy) | OPERATOR-APPROVAL | `workflow_dispatch` | The Bybit-only key-rotation path (2026-05-18, replaced the SOPS/Colab/age-key flow). **Superseded by `sync-vm-secrets.yml`**, which declares the full multi-broker secret set; kept in place pending a migration PR. Operator adds/updates the Actions secrets first, then dispatches. |
| `delete-merged-branches.yml` | Repo housekeeping | AUTONOMOUS | label `delete-merged-branches` | Stale merged-branch cleanup (web sessions can't delete branches directly). |
| `pr-opener.yml` | Control path | AUTONOMOUS | push-sentinel | Git-push-triggered PR opener — the MCP-independent PR-creation path. |
| `vm-driver.yml` | Control path | AUTONOMOUS | push-sentinel | Git-push-triggered remote driver — MCP-independent control path. |
| `e35-bracket-sweep.yml` | Research | AUTONOMOUS | dispatch | E3.5 bracket-geometry sweep, sharded one leg per job on free GitHub runners; candles from data.binance.vision, so no VM and no trainer contention. |
| `broad-paths-corpus.yml` | Research | AUTONOMOUS | issue label `broad-paths-corpus-request`, dispatch | Corpus v2 (lane ML-DATA-BROAD-PATHS): the six money-leg configs run config-exact on a frozen 60-perp Binance Vision universe with `--emit-trades/paths/features`, de-duplicated on `trade_key`; shards on free runners, rows stay an Actions artifact, only `comms/research/broad_paths/<corpus_id>/manifest.json` lands on main. |
| `pullback-frac-cross-leg-sweep.yml` | Research | AUTONOMOUS | dispatch | `pullback_frac` cross-leg sweep, sharded one leg per job on free GitHub runners; 19 legs in TWO strata that are never blended. Planner is CONFIG-gated (leg CSVs are gitignored, so a data-gated planner cannot schedule on a fresh checkout — the defect that leaves `e35-bracket-sweep` unable to plan). Crypto pins binance_vision (Bybit US-geoblocks runners); everything else pins the yfinance lane. No VM, no trainer contention. |
| `provision-live-vm.yml` | VM provisioning | OPERATOR-APPROVAL | label / dispatch | Provision the CANDIDATE live-trader VM (Ampere 2 OCPU/12 GB). |
| `deploy-candidate.yml` | Migration | OPERATOR-APPROVAL | label / dispatch | Phase-2 migration: deploy the bot stack onto the Ampere candidate. |
| `cutover-live.yml` | Migration | OPERATOR-APPROVAL | label / dispatch | Cut the live trader over to the Ampere candidate VM. |
| `reserve-live-ip.yml` | Infra | OPERATOR-APPROVAL | label / dispatch | Make the live trader's public IP a reserved (static) IP. |
| `terminate-instance.yml` | Infra | OPERATOR-APPROVAL | label / dispatch | Terminate an OCI instance by display name (frees Always-Free budget). |
| `trainer-boot-volume.yml` | Infra | OPERATOR-APPROVAL | label `trainer-boot-volume` / dispatch | Measure tenancy block storage (boot + block volumes vs Always Free 200 GB); grow the TRAINER boot volume online + growpart/resize2fs. Resize needs `confirm: yes` and is refused past 200 GB. |
| `oci-retire-orphan-volume.yml` | Infra | OPERATOR-APPROVAL | label `oci-retire-orphan-volume` / dispatch | Back up (FULL, must reach AVAILABLE) then delete the ONE pinned orphan block volume `ict-bot-data-vol`. `plan` is read-only and prints the OCID; `execute` needs `volume_id` + `confirm: yes`; refuses on any attachment record or listing error. |
| `oci-grow-boot-volume.yml` | Infra | OPERATOR-APPROVAL | label `oci-grow-boot-volume` / dispatch | Grow the LIVE VM boot volume 47->53 GB (never past 53). `plan` read-only (+ VM sudo preflight); `execute` needs `confirm: yes`: FULL backup, resize, growpart + resize2fs/xfs_growfs, verify. No reboot/restart. Exit 5 = sudo missing (prints sudoers line). Operator decision 2026-11-02 "Free +6 GB only". |
| `oci-close-api-port.yml` | Infra | OPERATOR-APPROVAL | label `oci-close-api-port` / dispatch | SEC-8001-LOCKDOWN (operator decisions page m3, 2026-11-12). Removes ONLY the OCI ingress rules that are exactly TCP / 0.0.0.0/0 / 8001 from the live trader's subnet security lists and VNIC NSGs (`scripts/ops/cloud_close_port.py`, the inverse of `cloud_open_port.py`); a wider range covering 8001 is reported, not touched. Dry run by default, which also probes whether the key can write; `apply: true` needs a `reason:` and refuses while raw :8001 still answers /api/health. Prints display names only, no OCIDs. |
| `vm-resize-live.yml` | Infra | OPERATOR-APPROVAL | label / dispatch | Resize the live trader VM within the OCI Always-Free pool. |
| `vm-fix-devnull.yml` | One-shot repair | OPERATOR-APPROVAL | label / dispatch | One-shot repair of a broken /dev/null on the live trader VM. |
| `vm-ib-gateway-deploy.yml` | IB-gateway ops | AUTONOMOUS | label / dispatch | Autonomous code deploy for the dedicated IB-Gateway VM. |
| `vm-ib-gateway-recover.yml` | IB-gateway ops | AUTONOMOUS | label `vm-ib-gateway-recover` | Autonomous self-heal (docker restart) for the IB Gateway container. |
| `vm-ib-gateway-selftest.yml` | IB-gateway ops | OPERATOR-APPROVAL | label / dispatch | Controlled end-to-end test of the reactive IB-gateway self-heal. |
| `vm-ib-gateway-stop.yml` | IB-gateway ops | OPERATOR-APPROVAL | label / dispatch | Decommission the IB Gateway container on the target host. |
| `vm-ib-gateway-watchdog-enable.yml` | IB-gateway ops | OPERATOR-APPROVAL | label / dispatch | Re-enable the IB-gateway watchdog (counterpart to vm-ib-gateway-stop). |
| `vm-git-credential-bootstrap.yml` | One-shot repair | AUTONOMOUS | label `vm-git-credential-bootstrap` / dispatch | One-shot bootstrap to break the git-fetch-auth chicken-and-egg after the repo went private (BL-20260706-GITSYNC-AUTH-BROKEN) — sets a global git credential on the VM from the outside so the existing (even pre-fix) deploy script's fetch starts authenticating immediately. Also doubles as the recovery step for a stale on-disk deploy script: after its own verification fetch, if the worktree reads behind `origin/main` it `git reset --hard origin/main` + runs `scripts/deploy_pull_restart.sh` directly, so a broken on-disk deploy script can't block itself from being fixed. Resolved + live-verified 2026-07-06. |
| `vm-ib-gateway-live-login-test.yml` | IB-gateway ops | OPERATOR-APPROVAL | label / dispatch | One-shot: verify LIVE IBKR login + 2FA without disturbing the running gateway. |

<!-- The 51 rows below closed a measured 45.9% gap in this index on 2026-08-21
     (BL-20260821-WORKFLOW-CATALOG-CLAIMS-COMPLETE-AND-IS-47PCT-MISSING). The
     completeness claim above is now enforced by the `workflow-catalog` guard
     (scripts/ci/check_workflow_catalog.py) rather than maintained by hand, so
     a new workflow that lands without a row here FAILS CI. Do not add a row
     for a workflow that does not exist — the guard checks that direction too. -->

| Workflow | Category | Autonomy | Trigger | Purpose |
|---|---|---|---|---|
| `guards.yml` | CI guard | AUTO | PR, `merge_group`, schedule `29 */2 * * *` (`--all` on `main`, never cancelled; replaced the per-push `--all` run, CI-STREAMLINE 2026-11-03), dispatch | **A REQUIRED status check**, and the single job that runs *every* fast static guard in the repo (registry: `scripts/ci/run_guards.py`; failure-path self-tests: `scripts/ci/guard_selftests.py`). Consolidated ~29 per-guard workflows into one runner acquisition after the 2026-08-06 Actions incident left 28 of 29 queued jobs runner-less (BL-20260806-CI-FANOUT-AMPLIFIES-ACTIONS-OUTAGES). Carries no `paths:` filter, deliberately — a required check must never hang "pending" on a non-matching PR. |
| `account-mode-verify.yml` | Observability | AUTONOMOUS | `push` to `main` touching `config/accounts.yaml` | **Did the account-mode change on main actually reach the running trader?** (JC-CA-01, 2026-09-28.) Parses the old and new `accounts.yaml` with PyYAML (`scripts/ops/account_mode_commit.py changes`). For each account whose parsed `mode:` changed, it dispatches the Tier-1, read-only `verify-account-mode` system-action, which polls the VM over SSH for up to 600 s and pages URGENT if it does not converge. It keys on the DIFF, so it covers every route a mode change can take to main: the `set-account-mode` hold PR, a hand-written PR, or an R16 mandate PR. A comment-only edit dispatches nothing. It dispatches with `GITHUB_TOKEN`, which is allowed to trigger `workflow_dispatch`. Writes nothing, merges nothing. Tier-1. |
| `armed-branch-push-watch.yml` | Control path | AUTONOMOUS | `push` to `claude/**` | **Did the commit you just pushed actually land?** `claude-pr-automerge` arms native auto-merge, and from that moment the branch is CLOSED TO NEW CONTENT — but nothing says so and `git push` reports success either way. FIVE commits have been silently dropped this way (`BL-20260908-CLAUDE-PR-AUTOMERGE-OPENS-A-PR-WITH-NO-CI-AND-ARMS-A-RACE-THAT-DROPS-COMMITS-FOUR-SESSIONS-IN-ONE-DAY`). The worst, **#11846 on 2026-09-12**, carried the `SESSIONS.json` row for a sub-session **that was already running**, so a live lane existed on the fleet with no record on `main` for nine minutes — the `MI-15` registry-incompleteness class, reached by a route the registry's own machinery cannot see — and its author's status update told the operator *"the checklist is pushed"*, which was true of the BRANCH and false of `main`. ⚠️ **IT PREVENTS NOTHING AND SAYS SO**: it fires AFTER the push. Its value is that #11846 went nine minutes undetected and was then found by hand; this makes it a failing run within seconds, on the channel `claude-run-failure-alert.yml` already watches. The PREVENTION half (open the PR under a PAT so CI attaches on the first head; arm only after a check exists) lives in `claude-pr-automerge.yml`, which `check_pr_landing.py::R12` refuses to let a branch self-land — a different PR and a different landing route. ⚠️ **CONTAINMENT IS DECIDED BY `pr.head.sha`, NEVER BY ANCESTRY**: this repo squash-merges, so `merge-base --is-ancestor` answers NO for EVERY correctly-merged commit and an ancestry-based detector would report a drop on the healthy case — the desensitised-alarm P1. The question asked is *is the head GitHub squashed the head that is there now?* ⚠️ **`state=all`, not `state=open`**, because the whole #11846 case is a push to a branch whose PR had ALREADY merged, and an open-only query grades that `no_pr` — *pushing is safe* — on the one state that is definitely not. ⚠️ **Six states, never collapsed** — `no_pr` / `unarmed` / `armed` (**WARN, never an error**: arming is legitimate and the push may well land, and failing the run here would train everyone past the channel) / `dropped` (**ERROR** — the run fails) / `merged_contained` / `unknown` (**WE COULD NOT LOOK** — reported, and deliberately does NOT fail the run, so a flaky API cannot become a daily alarm). `auto_merge` is read BY VALUE, never by key presence: GitHub returns `auto_merge: null` on every unarmed PR, so a `in pr` test would grade the entire repo as armed. ⚠️ **Self-tests its own grader before trusting a live run.** Blast radius: ONE `gh api` read of the branch's own pull request. It writes nothing, merges nothing, comments on nothing, touches no VM and is NOT a landing route — it can neither open, arm nor merge a PR. Tier-1. |
| `trainer-console-ingress.yml` | Infra | OPERATOR-APPROVAL | label `trainer-console-ingress` / dispatch (`mode: plan` or `apply`) | Opens public HTTPS to the console connector on the trainer VM (row UI-CONSOLE-V1; operator decision 2026-11-05 "Open 443 + Google OAuth (Recommended)"): adds TCP 80/443 from 0.0.0.0/0 to the trainer subnet's OCI security list only where missing (`scripts/ops/oci_console_ingress.py`, never removes), host iptables ACCEPT 80/443 persisted, Caddy serving `158-178-209-121.sslip.io` with only the connector's paths proxied (else 404), then verifies `/healthz` 200 from the runner. Idempotent; revert steps in the workflow header. Tier-2. |
| `trainer-console-connector-install.yml` | Infra | OPERATOR-APPROVAL | label `trainer-console-connector-install` / dispatch | Installs the persistent `jta-console-connector` systemd unit on the trainer VM (`deploy/trainer/jta-console-connector.service`; env file `/etc/jta-console/connector.env` written from repo secrets, never committed), swaps out the transient unit with one restart, retires the quick tunnel `jta-mcp-tunnel`, and prints enabled/active state, env var names (no values), token-store before/after and an unauthenticated `/mcp` status. Row UI-CONSOLE-CONNECTOR-PERSIST. Tier-2. |
| `trainer-capture-watch.yml` | Observability | AUTONOMOUS | cron `23 */6 * * *` + dispatch + issue label `trainer-capture-watch-now` | **The alarm on the trainer VM's forward-only L2 order-flow capture.** The operator DECIDED on 2026-08-29 to keep the trainer for that capture, which made the box a STATED DEPENDENCY for a stream nothing can re-derive — and nothing watched it (`OI-20260829-TRAINER-IS-NOW-A-DECIDED-DEPENDENCY-AND-IS-UNMONITORED`). ⚠️ **IT GRADES THE DATA'S FRESHNESS, NEVER THE UNIT'S `ActiveState`** — that is the whole design constraint. Measured on the box: the capture catches its own poll errors and continues, so `active (running)` is reachable while it writes nothing; `journalctl -u ict-orderflow-capture` reads `-- No entries --` for a healthy service and a wedged one alike; and `ict-trainer-publish.timer`'s mirror mtime advances normally with the capture dead. **Every cheap signal on that box is green through the exact failure this watches.** So the observable is the mtime of `datasets-out/market_microstructure/BTCUSDT/5m/v001/data.jsonl` — the path confirmed three ways (the unit's own `--out`, an `ls`, and the newest rows carrying 5m bar timestamps), because guessing it already cost a false alarm (probe #10422 looked in `runtime_logs/orderflow/`, which does not exist, and an empty result there is byte-identical to a dead capture). ⚠️ **IT RE-PROVES IT CAN FIRE, ON EVERY RUN, AGAINST PLANTED STALENESS** — each run plants two control files on the trainer (one backdated, one just touched) and grades them through the SAME transport and the SAME grader as the real capture; a misgrade FAILS the run and writes NO receipt, because a grader that silently stopped firing passes a deployment check and fails this. The fresh control is not redundant: without it an alarm that screams at everything would satisfy the stale one — the desensitised-alarm P1. The plants live in `/tmp` and **the live capture is never touched**. ⚠️ **Four states, never collapsed** — `fresh` / `stale` / `absent` / `unreadable`, the last being *we could not look* and alerting under its own name; collapsing it into `fresh` makes a broken watcher indistinguishable from a healthy capture. Threshold 1800s (6 missed 5m bars) is **CHOSEN against a single 67s reading, not tuned**. ⚠️ **A CRON IS NOT EVIDENCE OF A RUN**, so every run writes `docs/claude/work/TRAINER-CAPTURE-WATCH.json` and `scripts/ci/check_trainer_capture_watch.py` grades its AGE in `run_guards.py` on every PR (`never_ran` PASSES until it first fires, then the guard arms itself). ⚠️ **NO `push:` TRIGGER, deliberately** — it commits its receipt to `main`. Escalates twice over: a Telegram page, and a deliberate job failure picked up by `claude-run-failure-alert.yml`, so a Telegram outage does not silence the finding. ⚠️ **KNOWN BOUND**: at 6h cadence a stall is detected up to ~6h after it starts on a forward-only stream; 6h matches `pr-queue-watch` (deleted 2026-11-06) because each receipt costs an auto-merge PR through full CI. Blast radius: SSH `stat` + two `/tmp` touches on the trainer, one JSON file under `docs/claude/work/`; no order path, no config, no live VM. Tier-1. |
| `stale-automation-sweep.yml` | Control path | AUTONOMOUS | cron `17 */2 * * *` + dispatch | **The owner an automation PR does not have once its producing run exits.** `.github/actions/commit-to-main` already does everything a producer CAN do for its own PR — all **25 of 25** call sites set `verify-merged: true` (measured 2026-09-09 by parsing every workflow referencing the action), and `refresh-stale-branch` merges `main` in once when the wait stops progressing. ⚠️ **But all of it lives inside the PRODUCING RUN'S OWN LIFETIME** — one `verify-timeout-minutes` window (default 30), one refresh attempt — so a blocker outliving that window strands the branch PERMANENTLY while the producer's next cron opens another that strands identically. **MEASURED 2026-09-09, population = all 52 open PRs: 50 had `automation/*` head refs and 47 of those carried no R13 merge-slot claim**, cut before MI-208/#11494 taught the action to write one (#11493 opened 06:00:16Z has none; #11499 opened 06:38:14Z, twenty seconds after #11494 landed, has one). That is **one missing lifecycle stage, not 47 bugs**. ⚠️ **IT REFRESHES AND NEVER CLOSES, which is a safety property**: supersession is NOT decidable from a timestamp, and a first pass at this triage called 22 PRs cleanly superseded when the true figure was 15 — seven work-digest PRs each carried a `docs/claude/pending-pings.jsonl` row absent from `main`, so auto-closing would have dropped seven operator notifications (the hazard `OPEN-PRS.json`'s #10902/#10908/#10914 rows already record). Closing stays a human act with a recorded `disposition`. ⚠️ **AND IT REFUSES TO REFRESH A SUPERSEDED PR** — every one of these has auto-merge ARMED, so refreshing is not *letting it be judged again*, it is **LANDING it on green**; refreshing a PR whose register is older than main's would REWIND main, which is worse than the strand. ⚠️ **Eight states, never collapsed** — `refresh` / `superseded_identical` / `superseded_older` / `superseded_by_open_pr` / `carries_append_only` / `absent_on_main` / `undated_payload` (*we could not tell*, *never* "safe") / `no_payload`; only `refresh` is actionable and a test pins that. ⚠️ **`carries_append_only` is detected as a PROPERTY, not from a path list** — MEASURED 2026-09-09 by hand-triaging #11475, which the `APPEND_ONLY` list did not cover: `comms/macro/econ_calendar_snapshots.jsonl` there is `main` plus **427 rows main does not have**. It graded `undated_payload` and so was never actionable, but only BY ACCIDENT — JSONL does not parse as a JSON object, so `dated_at` returned None. Stamping `generated_at` on that generator is exactly the remedy filed for the 13 undated PRs, and it would have ARMED the row-dropping bug; the sweeper now tests whether `main`'s bytes are a strict PREFIX of the branch's, which can only ever move a PR toward *a human must look*. ⚠️ **`absent_on_main` is its own state because `dated_at` returns None for two different reasons** — *main has never had this file* and *neither side carries a date* — and reporting the first as "no comparable timestamp" names a cause no code path tested. Live: #11361 and #11525 each carry a `comms/strategy_reviews/<date>/INDEX.json` main does not have. ⚠️ **THE CADENCE IS SET OFF THE GUARD WINDOWS, NOT THE QUEUE** — four always-run (`when: None`) guards grade a dated receipt that must LAND on `main` (`check_digest_liveness` 6h, `check_trainer_capture_watch` 15h, `check_pr_queue_watch` 30h, `check_manager_queue_watch`), each a REQUIRED check, so a receipt that cannot land reds **every open PR in the repo** — which is what happened 07:44:31Z→07:56:53Z on 2026-09-09. 2h gives ~3 sweeps inside the tightest window. ⚠️ **Pushes with the PAT, not `GITHUB_TOKEN`** — a `GITHUB_TOKEN` push creates no workflow runs, so the refresh would mint a head sha **nothing grades**, turning *stranded with stale red checks* into *stranded with no checks at all*, which reads as progress. ⚠️ **NO `push:` trigger**, deliberately: it pushes to branches with open PRs. ⚠️ **`COULD NOT LOOK` (exit 2) is never reported as success** — an unreadable open set is not an empty queue. Blast radius: merges `origin/main` into `automation/*` branches and re-asserts their own R13 claim; never merges, closes, un-drafts or comments on a PR, and touches no branch outside `automation/*`. Tier-1. |
| `ci-settled.yml` | Control path | AUTONOMOUS | push-sentinel | Session-invokable CI READER — grades a PR's WHOLE head into one verdict. ⚠️ Pair it with `subscribe_pr_activity`: that wake is the TRIGGER and costs no polling, but a `check_suite.completed` success is per-SUITE and NOT per-PR (`BL-20260821-CHECK-SUITE-EVENT-IS-PER-SUITE-NOT-PER-PR`, open/high), so it is not a verdict. Run `scripts/ops/ci_settled.sh <PR> once` when the wake arrives. The waiting mode is a FALLBACK for an unsubscribed PR, not the headline. `api.github.com` is HTTP 403 inside a Claude sandbox (re-confirmed 2026-09-02), so a session cannot script a CI poller and must call `mcp__github__pull_request_read` repeatedly while a suite runs. Push `automation/ci-watch/<name>.json` (`{"pr": N}`) and read `automation/ci-results/<name>.json` back; `scripts/ops/ci_settled.sh <PR>` does both in one command. The payload carries `mergeable_state`, the check roll-up, unresolved review threads and — when red — a bounded failing-log excerpt, so a red verdict does not then cost a `get_job_logs`. Seven states, never collapsed (`scripts/ops/ci_settle.py`); zero check runs grades `no_checks`, NEVER green. Reports only: cannot merge, cannot push to `main`, never reaches `src/`, `config/` or either VM. |
| `pr-close.yml` | Control path | AUTONOMOUS | push-sentinel | Git-push-triggered PR closer — the third leg of the MCP-independent PR path alongside `pr-opener.yml` (opens) and `claude-pr-automerge.yml` (merges). |
| `trainer-diag-relay.yml` | Control path | AUTONOMOUS | push-sentinel | Git-push-triggered TRAINER-VM diag relay — the MCP-independent read path when a session's GitHub MCP is 403 on issue writes and it therefore cannot open a `trainer-vm-diag-request` issue. Drop a script at `automation/trainer-diag-requests/<fresh>.sh`, read the answer back from `automation/trainer-diag-results/<fresh>.txt`. The file IS the script (no `cmd:` parser), and the result header carries a never-collapsed `state` (`ran`/`unreachable`/`refused_empty`/`refused_scope`) plus a real `remote_exit`. Trainer VM only — a script naming a live-trader/gateway host is refused. |
| `claude-pr-automerge.yml` | Control path | AUTONOMOUS | push (`.github/pr-automerge-requests/<branch-slug>.txt`) | Opens (or finds) a `claude/**` branch's PR and enables native squash auto-merge — the durable path when the GitHub MCP is read-only. CI is never bypassed; branch protection still gates. ⚠️ **The `paths:` filter is NOT the gate** — it cannot distinguish "I asked" from "I merged someone else's ask", and merging `main` puts other branches' request files in your push diff. Three PRs were armed that way on 2026-09-02 (`BL-20260902-THE-PER-REQUEST-GLOB-IS-ITSELF-DRAGGED-IN-BY-A-MERGE-OF-MAIN`). The job body proves the ask against the branch's OWN name and refuses to un-draft a PR it did not open; `automerge-trigger-guard` holds both. |
| `pr-automerge-disable.yml` | Control path | AUTONOMOUS | push (`automation/pr-automerge-disable/*.json`) | The OFF switch for the row above: disables a PR's auto-merge request and optionally converts it back to draft. Exists because the repo could arm a merge from a runner and could **not** disarm one — `update_pull_request` 403s from a read-only-MCP session, `pr-close.yml` cannot reopen, and no `disablePullRequestAutoMerge` existed anywhere. Requires the request to name the PR's **current** head (`pr-close.yml`'s optimistic-concurrency guard, copied not reinvented) and grades `disable_state` / `draft_state` **separately**, so a half-applied disarm cannot read as clean. Every effect it has makes a merge LESS likely. |
| `claude-run-failure-alert.yml` | Alerting | AUTO | `workflow_run` | The loud failure flag for Claude-driven VM / relay / heavy-compute workflows (operator directive 2026-07-28) — pings instead of letting a failed run be discovered hours later. |
| `external-issue-alert.yml` | Security | AUTO | `issues` | Early warning on the issue-driven-automation attack surface: flags issues opened by a non-owner, since every privileged relay here triggers on `issues.opened` + a label. |
| `issue-router.yml` | Infra | AUTO | `issues` (opened) | Issue fan-out fix (PI-20260927-W6OPSR-0004): sends one `repository_dispatch` per label on each opened issue, so label-routed workflows (`repository_dispatch: types: [<label>]`, see `scripts/ops/issue_router_migrate.py`) get a run only when the issue names their label. Before: ~89 runs per issue, all but a few skipped. Adds no gate. |
| `external-comment-alert.yml` | Security | AUTO | `issue_comment` | The comment-vector half of the above — flags comments from non-owner / non-automation accounts on any issue or PR. |
| `feature-impact.yml` | ML research data | AUTONOMOUS | cron (weekly Thu 05:23) + dispatch | FEATURE-IMPACT-MAP v0: M1 per-feature split/gain share from the committed `ml/served` + `ml/candidates` LightGBM artifacts, written as a long table to `comms/feature_impact/<run_id>.jsonl` + `latest.json` via commit-to-main. Logic in `scripts/research/feature_impact.py`; no VM, no Claude. |
| `compute-util-telemetry.yml` | Infra audit | AUTONOMOUS | cron (daily 06:37) + label / dispatch | Read-only daily CPU/memory/network/disk ledger for the live, trainer and gateway VMs (OCI Monitoring + one SSH df/proc sample), Oracle idle-reclaim alert, per-VM spare capacity for the research router, and the OCI A1 limits read (`comms/cloud/`). Logic in `scripts/ops/compute_util.py`. |
| `research-watchdog.yml` | Research ops | AUTONOMOUS | cron (every 15 min) + dispatch | Token-free research pipeline watchdog: dispatcher job start/stuck, queue floor, per-backend idle, collector, stranded stamps; self-heals once, then escalates on the draft PR `ops-flags (do not merge)` + send-ping + `comms/research/ops/watchdog_incidents.jsonl`. Logic in `scripts/research/research_watchdog.py`. |
| `reset-protocol-backup.yml` | Manager loop | AUTONOMOUS | cron (Wed `15 18` + `0 19`) + dispatch | RESET-PROTOCOL (2026-11-02): backup trigger for the weekly reset protocol. 18:15Z posts ONE `RESET: weekly usage reset at <ts>; run reset protocol` comment on the ops-flags PR (#17895) unless a receipt for that reset is already on `main`; 19:00Z, if there is still no receipt, posts a RED-FLAG comment and sends a `send-ping` system-action. Hidden per-date markers make each post once-only. Token-free (no Claude/API spend); no gate. Jobs/receipts: `config/reset_protocol.yaml`, `scripts/ops/reset_protocol.py`. |
| `live-review-wake.yml` | Live trade review | AUTONOMOUS | cron (every 5 min) + dispatch | LTR-1B: token-free wake. Reads `/api/diag/live_review_due` (DIAG_READ_TOKEN via `diag_fetch.sh`) and posts ONE comment (hidden `ltr-wake` marker) on the draft PR `ops-flags (do not merge)` per newly due real-money/prop event, so the subscribed manager dispatches a LIVE-REVIEW lane. Paper and `daily_floor` never wake; dedupe/cooldown from its own markers. LTR-PACKET-ECHO (2026-10-27): before posting, commits each built packet + outcome table to `live-review/rows` byte-exact (one fast-forward git-data commit, `contents: write`); a package whose evidence could not land is posted as `could_not_commit` with no packet block. Logic in `scripts/ops/live_review_wake.py`. |
| `counterfactual-grade-closed.yml` | Live trade review | AUTONOMOUS | cron (`17 * * * *`) + dispatch | TRADE-COUNTERFACTUAL-GRADER: grades every newly CLOSED order package (idempotent by file name, cap 20 per run) with `scripts/research/counterfactual_grader.py --live --all-closed --write`: original brackets, alt SL/TP grid, less/more management, unapplied review calls and a matched random control, net of fee+slippage+funding, $ and % per account and R; lands one self-landing commit-to-main PR under `comms/research/counterfactual_grades/`. A grading failure is a warning, never a stop. |
| `forecast-grade.yml` | Live trade review | AUTONOMOUS | cron (`41 * * * *`) + dispatch | FORECAST-GRADE-FIRST-PASSAGE: hourly, token-free first-passage grade (target_first / invalidation_first / expired, plus pending and tie_unresolved) of every price forecast (live-review rows, desk entry proposals) with `scripts/research/forecast_first_passage.py --live --write`; commits `comms/desk/forecast_grade.json` + `forecast_ledger.jsonl` when a forecast changed state or the committed grade is >6h old; the same run also executes `scripts/research/desk_am_judgement_grade.py --live --write` (RULE-DESK-AM-JUDGEMENT-V1 net-of-cost d_hold/d_mech package grade, previously never run) and commits `comms/desk/am_judgement_grade.json` when its content changes. Grades only; gates nothing. |
| `live-review-rows-mirror.yml` | Live trade review | AUTONOMOUS | push to `live-review/rows` + cron (`41 * * * *`) + dispatch | LTR-APPLY-AUTOFLOW (iv): copies rows on the append-only `live-review/rows` branch that main's `comms/live_review/reviews.jsonl` lacks onto main, merged BY `review_id` (never text concat; a re-run is a no-op), plus the packets and outcome tables they cite, in ONE self-landing commit-to-main PR. Each row is validated by `check_live_review_records.row_problems` (called, not copied): a row that fails is skipped as `schema: <message>` and logged, the rest still mirror (one corrupt row on the append-only branch must not strand every later one; schema skips keep the run green, other skips stay red). A cited file differing on main is never overwritten (row skipped, run red). A `packet_sha` mismatch is `packet_sha: ...`: `::error` plus ONE `ltr-mirror-refused` comment per review_id on the ops-flags PR, run stays green; rows listed in `comms/live_review/killed_rows.json` are reported as `killed` (LTR-PACKET-ECHO). Also dispatched from main by `branch-mirror-heartbeat.yml` (a `push` run uses the branch's stale copy of this file). Logic in `scripts/ops/live_review_rows_mirror.py`. |
| `desk-scan-packet.yml` | Trading desk | AUTONOMOUS | cron (`3 * * * *`) + dispatch | DESK-6-SHADOW-PILOT: builds ONE 1h scan packet with `scripts/ops/desk_scan_packet.py` (DIAG_READ_TOKEN read path; validated by desk-records-guard inside the builder) and commits it plus the pointer `comms/desk/latest_scan.json` to the append-only `desk/decisions` branch (`scripts/ops/desk_branch.py publish`); never force-pushes. A repo-less desk wake (`.claude/skills/trading-desk/DESK-BRIEF.md`) reads the pointer and appends ONE decision row. Record-only: no order path. |
| `desk-decisions-mirror.yml` | Trading desk | AUTONOMOUS | push to `desk/decisions` + cron (`48 * * * *`) + dispatch | DESK-6-SHADOW-PILOT: copies rows on `desk/decisions` that main's `comms/desk/decisions.jsonl` lacks onto main, BY `decision_id`, plus the packet each cites (`scripts/ops/desk_branch.py mirror`); replays every due shadow proposal on real candles net of the full cost stack into `comms/desk/outcomes.jsonl` (`scripts/ops/desk_outcomes.py`); validates with desk-records-guard; ONE self-landing commit-to-main PR. |
| `branch-mirror-heartbeat.yml` | Trading desk | AUTONOMOUS | push to `main` + dispatch | Runs `desk-decisions-mirror.yml` and `live-review-rows-mirror.yml` from MAIN's files via `workflow_dispatch --ref main` on every main push (throttled: skipped when a run is queued or the last one finished < 10 min ago). Why: a `push` to `desk/decisions` / `live-review/rows` runs the workflow file as it exists on that branch (stale, so the DESK-9 / LTR-5 grading steps never ran from a push), and the cron schedules fire late or not at all. Measured 2026-10-27. |
| `research-slo.yml` | Research ops | AUTONOMOUS | cron (`41 */2 * * *`) + dispatch | RESEARCH-PIPELINE-SLO (operator 2026-10-16): measures the research-pipeline SLOs in `scripts/research/research_slo.yaml` (floor, fires, lands, grading latency, undispositioned results, authoring supply, programme coverage, theme share, blocked age, stage liveness, hold-PR wait, research-ops completeness), writes `comms/research/health/<date>.json` via commit-to-main, and on a change of the not-ok set sends ONE message to the system Telegram channel + ONE `research-slo` comment on the ops-flags PR (reminder at most every 24 h; recovery message). Leaves out SLOs the watchdog already escalated. Never halts anything. Logic in `scripts/research/research_slo.py`. |
| `oci-capacity-report.yml` | Infra audit | AUTONOMOUS | label `oci-capacity-report` / dispatch | Read-only (list_*/get_* only) OCI report: boot + block volumes with attachments, backups, tenancy Limits API values/availability for block-storage and A1 compute, object-storage usage; per-section read_state, unreadable = `could_not_look`. Added by lane OCI-FREE-CAPACITY 2026-11-02; script `scripts/ops/oci_capacity_report.py`. |
| `oci-inventory.yml` | Infra audit | AUTONOMOUS | cron (weekly Mon 06:00) + label / dispatch | Read-only OCI compute inventory diffed against the topology this repo declares (`comms/cloud/expected_topology.json`) — the canonical docs described VM topology in prose and nothing checked it. ⚠️ Currently watched by nothing (`BL-20260821-OCI-INVENTORY-CRON-UNWATCHED`). |
| `journal-offvm-backup.yml` | Infra backup | AUTONOMOUS | cron (daily 03:23) + label / dispatch | Versioned, private off-VM backup of the live `trade_journal.db`: read-only online-backup snapshot over SSH, integrity check, upload to the OCI bucket `ict-journal-backups` (NoPublicAccess, versioning on), 30-day daily + 12-week weekly pruning, restore test every run. Modes `backup` / `status` / `restore-test`. Output is sizes and counts only. JOURNAL-OFFVM-BACKUP (Tier 2, operator-approved 2026-10-13). |
| `macro-producer-liveness.yml` | Ops audit | AUTONOMOUS | cron (daily 12:00) + label / dispatch | Dead-man switch for the scheduled macro producers — kills the "silently-skipped scheduled job" class by alarming when a registered producer stops landing rows. |
| `replay-pregate-nightly.yml` | ML | AUTONOMOUS | cron (daily 04:00) + label / dispatch | Session-independent runner for the ML replay pre-gate (RG3): baselines the shadow-stage regime fleet on the trainer VM and commits the report. |
| `soak-book-grade-weekly.yml` | Research | AUTONOMOUS | cron (weekly Sun 03:00) + label / dispatch | Checklist row R5 — grades every Stage-1 soak leg (`bybit_1`, `alpaca_paper`) on mechanics (reuses E18's `leg_flow_report`) and cost fidelity (reuses R3's `r3_cost_fidelity`) into healthy/tweak/kill/insufficient-data via `scripts/ops/soak_book_grade.py`. Not expectancy — Stage 1 never decides edge. Lands the result under `comms/research/soak_book_grade/` via the shared `research-result` action. |
| `gpu-burst-train.yml` | ML | AUTONOMOUS | label `gpu-burst-train` | M19 Tier-1 ledger-gated, teardown-guaranteed spot-GPU burst training. Spend-gated against the $10/month cap and appended to `comms/gpu_spend_ledger.json` (surfaced at `/api/bot/gpu/spend`). |
| `kaggle-gpu-pilot.yml` | ML | AUTONOMOUS | `workflow_dispatch` | COMPUTE-KAGGLE-GPU pilot: pushes a tiny private Kaggle GPU kernel (nvidia-smi + matmul benchmark, public data only), polls it, uploads output + `kaggle quota` as an artifact. Holds `KAGGLE_API_TOKEN` only. |
| `trainer-offload-train.yml` | ML | AUTONOMOUS | label `trainer-offload-train-request` / dispatch | Free-runner offload for OOM-prone ML manifests — the 1-OCPU/6-GB trainer OOM-quarantines the heavy ones, so they train on a hosted runner instead. |
| `research-loss-detector.yml` | Research | AUTONOMOUS | cron (every 12h at :23) + dispatch | **E57 — makes a research result that did not reach `main` impossible to miss**, independent of any manager session. `scripts/ops/research_loss_detector.py` asks three questions over stated populations: (A) open `automation/*` research PRs older than 6h; (B) runs of every workflow calling `./.github/actions/research-result` (derived from the tree) whose record is not on `main`; (C) research-workflow artifacts expiring within 72h with no landed copy. Alerts the operator's Telegram channel on findings AND on could-not-read. ⚠️ **Each run lands `docs/claude/work/RESEARCH-LOSS-RECEIPT.json`, graded by `check_cadence_liveness.py` on every PR**, so a detector that stops running reds CI instead of reading as "nothing lost". Never merges, closes or re-runs anything. |
| `gitleaks-history-weekly.yml` | Security | AUTONOMOUS | cron (Mondays 05:17 UTC) + dispatch | **FIX-SA-13 / SA-AUD-7-secret-scan-head-only — the history-wide secret scan `scripts/secret_scan.py` (HEAD only, 3 patterns) cannot be.** Runs gitleaks v8.24.3 (binary pinned by version + sha256; checkout pinned by commit sha) with default rules over full history (`fetch-depth: 0`, so every fetched branch), `--redact=100`, no `-v`. `scripts/ops/gitleaks_summarize.py` reads the JSON report and prints **only rule / file / 12-char commit / line**, then deletes the report; there is no artifact upload and no comment step, because a matched value must never reach a public log. `contents: read` only. Fails on any finding not in an optional committed `.gitleaks-baseline.json`. ⚠️ **First run is expected RED** (356 findings measured 2026-09-29, mostly entropy matches in `docs/claude/work/`) — triage first, baseline second (PI-20260929-SASEC-0001). Failure notifies via `claude-run-failure-alert`. |
| `research-artifact-rescue.yml` | Research | AUTONOMOUS (manual dispatch) | dispatch (`run_ids`) | Rescue for the research-loss-detector's section C (operator 2026-11-08: *"let's save those. No reason to let those go to waste"*). For each named run id, `gh run download` copies its artifacts to `comms/research/rescued/<run_id>/` plus a `RESCUE-run.json` with the run metadata, then lands them through `commit-to-main` (`verify-merged`, `close-on-fail`). Data only; it never re-runs, merges or deletes anything. |
| `research-queue-dispatch.yml` | Research | AUTONOMOUS | cron (HOURLY at :20 since 2026-10-06; was every 6 h) + dispatch | R5 of the research-workflow architecture — the scheduler. Reads `research/queue/*.yaml`, grades each job against the R4 power gate, routes it by its DECLARED resource needs (runner / trainer / GPU / unroutable) and dispatches. Hourly on operator direction 2026-10-06 (*"the git infrastructure should be what keeps the queue moving"*, not a session); the caps (`--max-research-inflight 3`, `--max-repo-queued 10`, per-run GPU 1, monthly ledger), the replenisher's 6 h runnable horizon and the 12 h idle alarm are unchanged. ⚠️ **The SCHEDULED run FIRES FOR REAL** (since 2026-08-30 — this row said "DRY RUN" until 2026-10-06, stale against the workflow's own header; *field beats comment*); only a hand `workflow_dispatch` defaults to a dry run, `fire` opt-in. Exits 2 when it could not READ the queue, which is deliberately distinct from an empty one. Backpressure (2026-09-29): every fire is DEFERRED while >= 3 research compute runs are queued/in progress or > 10 runs are queued repo-wide, so research never starves a system-action; and it first batch-lands the token-free runner's results (one PR per cycle). A run still queued/in progress > 24 h after creation is STUCK, not load, and counts against neither cap (2026-09-29: all 36 "queued" runs dated 2026-05-15 deferred every fire). Its alarm step REFILLS before it pages: health exit 3 (runnable < 25 but the templates can fill the gap) dispatches `research-queue-replenish.yml`; only an unfillable gap or a 12 h idle pages. |
| `llm-delegate.yml` | Tooling | AUTONOMOUS | dispatch | Bursty LLM worker for delegated, bounded coding/research subtasks. The runner *is* the worker: it starts, does one subtask, and is destroyed. Scope guard: public repo code + docs only. |
| `m20-capture-census.yml` | Research | AUTONOMOUS | dispatch / push | M20 exit-capture census — the measure-first pass. Applies **no** lever and grades nothing; runs each live leg's config-exact base to size the design work. |
| `ranking-key-ab.yml` | Research | AUTONOMOUS | dispatch / push | The trade-prioritisation A/B — four ranking-key arms (`confidence_first` / `priority_first` / `recent_pnl_first` / `random_tiebreak`) over one N-book replay, on free GitHub runners (candles from data.binance.vision, since Bybit US-geoblocks runners; no VM, no trainer contention). Fires `scripts/research/nbook_portfolio.py` and grades with `scripts/research/rank_arm_report.py`. ⚠️ **ONE job, four arms, deliberately NOT a matrix** — the arms differ ONLY in the election key while the expensive signal streams are identical, so a matrix would re-derive every stream four times for no change in the streams. ⚠️ The CONTROL (`random_tiebreak`) is ALWAYS added even if the caller omits it: it is the floor every other arm must clear, and a report without it grades nothing. ⚠️ Every headline is the **CONTESTED SUBSET ONLY** and stratified by `decided_by`; the run asserts a plausible candle count before replaying, so a thin fetch cannot produce a null that is an artefact of an empty file. Results land under `docs/research/ranking-key-ab/` via `commit-to-main`, because an expired CI artifact is not a durable locator (`BL-20260823-E35-SWEEP-EVIDENCE-HAS-NO-DURABLE-PATH`). ⚠️ It MEASURES the live ranking key and never changes it — flipping it is Tier-3. |
| `m20-exit-lever-sweep.yml` | Research | AUTONOMOUS | dispatch / push | M20 exit-lever sweep — the design pass the capture census sized. |
| `ict-scalp-exit-sweep.yml` | Research | AUTONOMOUS | push / dispatch | M27 `ict_scalp` crypto exit-lever sweep, one matrix job per live crypto leg on free 4-core runners so the heavy sweep stays off the 1-core trainer. |
| `research-exit-head-build.yml` | Research | AUTONOMOUS | label `research-exit-head-request` / dispatch | M30 × M20 per-bar in-trade EXIT-HEAD discovery run — the exit-frontier sibling of `research-panel-build` (deleted 2026-11-06). |
| `research-harness-dispatch.yml` | Research | AUTONOMOUS | dispatch only | E7 — the one dispatchable workflow for the ten `scripts/backtest_*.py` harnesses that had no runner at all (chop_scalp, fade, fvg_range, orb, pullback, squeeze, funding_carry, pairs, xsec_momentum, vol_target). Fetches a real, non-fixture corpus for the chosen harness (`fetch_backtest_corpus.py`), runs it, and lands a `research_result.py` record via the shared `.github/actions/research-result` action. |
| `research-script-run.yml` | Research | AUTONOMOUS | dispatch only (from the queue dispatcher) | RQ-RUN — the TOKEN-FREE research runner. Takes ONLY `research_unit` (+ the dispatcher's `power_state` label), reads that unit's `run.command` from `research/queue/<id>.yaml` on the checked-out ref, refuses any script outside `scripts/research/` / `scripts/backtest*.py` (`scripts/research/script_run.py`, guarded by `research-script-run-guard`), runs it with no secret beyond `GITHUB_TOKEN`, uploads the outputs plus `record-inputs.json` as a 14-day artifact and lands NOTHING itself (manager review 2026-09-29): `scripts/research/collect_runner_results.py`, at the top of every `research-queue-dispatch` cycle, lands every completed run's outputs under `comms/research/<unit>/<run_id>/` and its E5 record in ONE batch PR. A green script that wrote no `verdict.json` lands as `producer_failed`, never `measured`. |
| `ml-entry-retrain.yml` | ML | AUTONOMOUS (candidate only; Tier-2 PR) | cron Sun 04:00Z (first run 2026-11-08) + dispatch | ML-ENTRY-RETRAIN-CADENCE — weekly CANDIDATE refit of the live ENTRY model (`scripts/research/ml_entry_retrain.py`, the registered c692-01 recipe, all data through the previous UTC day minus the embargo). Uploads `candidate_model.json` + `freshness.json` (feature list, sha256, data-through) as a 90-day artifact. Never writes `ml/served/` or config: serving is the operator's call. No halting: a failed run keeps the previous artifact and is the ONE red flag via `claude-run-failure-alert`. No secrets. |
| `research-script-run-trainer.yml` | Research | AUTONOMOUS | dispatch only (from the queue dispatcher) | ML-RQ-RUNNER (2026-10-11) — the TRAINER-VM twin of `research-script-run.yml`, for ML units that need trainer-resident data / the trainer venv. Same two inputs (`research_unit`, `power_state`; guard `research-script-run-guard` R2), same allowlisted `run.command`, re-checked on the runner first. SSHes to the trainer, waits (≤25 min) until the trainer's checkout holds byte-identical copies of the unit file and the scripts it runs (the trainer force-syncs `main` every ~15 min — never old code under a new rule), runs `script_run.py --run` there under the trainer venv (the engine `ml_bakeoff.py` takes the shared heavy-job lock), copies the outputs back, derives `record-inputs.json` and uploads `research-script-run-trainer-<unit>-<run_id>`; the SAME collector lands it. Holds `VM_SSH_KEY` and nothing else; constant concurrency group = one trainer research run at a time (the dispatcher serializes it). IPv4 addresses are scrubbed from the session log before it is uploaded. |
| `research-script-run-kaggle.yml` | Research | AUTONOMOUS | dispatch only (from the queue dispatcher) | RESEARCH-ROUTER (2026-10-13) — the KAGGLE-GPU twin of `research-script-run.yml`, for units declaring `compute: gpu` (`scripts/research/research_compute.yaml`). Same two inputs (`research_unit`, `power_state`; guard `research-script-run-guard` R2) and the same allowlisted `run.command`, re-checked on the runner and again inside the kernel. Gates on `kaggle quota` (floor in the config), bundles the tracked `scripts/ src/ config/ ml/` + the unit file into a private dataset (public repo, nothing private), pushes the static kernel `scripts/research/kaggle_unit/kernel_main.py` (2x T4, internet off), polls, pulls `comms/research/<unit>/<run_id>/` back and derives `record-inputs.json`; uploads `research-script-run-kaggle-<unit>-<run_id>` and the SAME collector lands it. Holds `KAGGLE_API_TOKEN` only; one Kaggle research run at a time (constant concurrency group). The Kaggle username is masked and scrubbed. |
| `research-script-run-kaggle-cpu.yml` | Research | AUTONOMOUS | dispatch only (from the queue dispatcher) | KAGGLE-CPU-ROUTE (2026-10-14) — the Kaggle CPU twin of `research-script-run-kaggle.yml`, for units declaring `routing.published_data` (backend `kaggle_cpu`, `scripts/research/research_compute.yaml`); kaggle 2.2.4 `DownloadDataset` 404s for the private dataset from a GitHub runner but a Kaggle kernel mounts it. Same two inputs, allowlist re-check and collector as the GPU twin; the kernel has `enable_gpu=false`, so there is NO quota gate (not metered by the 30 h/week GPU quota). Own bundle/kernel slugs (`metis-research-bundle-cpu` / `metis-research-run-cpu`) and concurrency group, so a CPU and a GPU run can be in flight together. Uploads `research-script-run-kaggle-cpu-<unit>-<run_id>`. Holds `KAGGLE_API_TOKEN` only. |
| `research-candles-kaggle.yml` | Research | AUTONOMOUS | dispatch + PRs touching the pipeline | KAGGLE-CANDLES (2026-11-02) — builds the public candles the run-time-fetching exit-lever units need (HF lake first, network fallback) and publishes them as the private Kaggle dataset `metis-research-candles`, so those units can run on `kaggle_cpu` (internet off). Tier 1; holds `KAGGLE_API_TOKEN` + `HF_TOKEN`; uploads `research-candles-<run_id>` (manifest + coverage record). No cron. |
| `research-script-run-data.yml` | Research | AUTONOMOUS | dispatch only (from the queue dispatcher) | ML-DATA-OFF-TRAINER (2026-10-13) — the PUBLISHED-DATA twin of `research-script-run.yml`: same two inputs and allowlisted command, plus one fetch step that downloads the private Kaggle dataset `metis-market-data`, re-hashes it against its MANIFEST and exports `ML_DATA_ROOT` (`scripts/research/published_data.py`). Holds `KAGGLE_API_TOKEN` in the fetch step only; the unit's command runs without it. Selected by the router for units declaring `routing.published_data` (backend `github_runner_data`). Artifact `research-script-run-data-<unit>-<run_id>`, landed by the same collector. |
| `cf-bulk-backtest.yml` | Research | AUTONOMOUS | `workflow_dispatch` (`run_id`, `batches`, `n_random`) | CF-B1-BULK-BACKTEST (2026-11-01) — plan → matrix of balanced shard batches → reduce. Runs `scripts/research/cf_bulk.py` over every distinct backtest replay job on hosted runners (no secrets, no Claude, read-only on the repo, keyless Binance Vision bars); uploads artifacts `<run_id>-plan`, `-shards-<n>`, `-result` (manifest.json + summary.json). Adds no gate. |
| `market-data-lake.yml` | Data pipeline | AUTONOMOUS | cron 03:41 UTC daily (schedule-keeper target, `dedupe` job) + dispatch (`mode: refresh\|backfill\|preflight`) + label `market-data-lake-request` + pull_request (preflight only) | MARKET-DATA-LAKE (2026-11-01) — the pooled-ML market data lake on the PRIVATE HF dataset `bentzbk/jta-market-lake`, captured/processed/validated with no Claude session in the loop: every Binance USD-M perp incl. delisted at **1m** + funding + 5m metrics, 27 spot majors at 1m (`scripts/data_lake/binance_vision_lake.py`, incremental by month), 5m-1d DERIVED by `resample.py`; universe snapshots, FRED, CFTC COT, CBOE IV, Yahoo futures fronts, the ETF/option stores, Alpaca 1d for every US stock/ETF incl. inactive, DoltHub stocks/options weekly (`free_sources.py`). `validate.py` writes the health record (HF `health/latest.json` + repo `comms/data_lake/health_latest.json`) and raises ONE ops-flags/Telegram flag after 3 consecutive failing runs. Reader `ml/datasets/lake.py`. Needs `HF_TOKEN` (write). Market data only; nothing halts. |
| `hf-lake-storage.yml` | Data pipeline | AUTONOMOUS | label `hf-lake-storage-request` (body `mode: measure\|squash`) + pull_request (measure only) | HF-LAKE-STORAGE-403 (2026-11-05) — measures private HF storage per repo and the lake's current-revision vs total bytes; `squash` runs `super_squash_history` on `bentzbk/jta-market-lake` (irreversible, operator-approved) and verifies `MANIFEST.json` resolves 200. The daily `market-data-lake.yml` only MEASURES and warns at 85 GB (never auto-squashes). Needs `HF_TOKEN`. |
| `hf-lake-kaggle-pilot.yml` | Data pipeline | AUTONOMOUS | pull_request (same-repo) touching the pilot files | HF-LAKE-STORAGE-403 pilot (operator 2026-11-05: "Kaggle 1 GB pilot first (Rec.)") — stages ~1 GB of frozen crypto 1m partitions into a PRIVATE Kaggle dataset `metis-market-lake` on the existing account (`KAGGLE_API_TOKEN`), versions it twice, probes the top-level file-count limit, reads it back on a runner and in a Kaggle kernel. Read-only on HF; never creates an account. Heavy jobs run only when the PR head commit message carries `[kaggle-pilot]` (0.9 GB) or `[kaggle-trial]` (10 GB trial, operator 2026-11-05 "10 GB trial (Rec.)"). |
| `kaggle-backups.yml` | Data pipeline | AUTONOMOUS | cron 04:23 UTC daily (models) + cron 09:41 UTC Sundays (db) + label `kaggle-backup-request` (body `mode: models\|db\|dbsize`) + pull_request (token-gated: `[kaggle-backup-models]` / `[kaggle-backup-dbsize]` in the head commit) | KAGGLE-BACKUPS (operator 2026-11-05: "Ok, let's also keep backups on kaggle (on private)") — mode `models`: the trainer registry-store (read-only SSH pull) + `ml/served` as versions of ONE private Kaggle Model `metis-ml-backup`, credential-scanned (a hit refuses the backup), re-downloaded and re-hashed, loaded in a CPU Kaggle kernel, freshness stamp `comms/backups/kaggle_latest.json` landed for the health review, ONE red flag after 2 consecutive failed runs, never halts. Mode `db` (weekly, operator 2026-11-05 "Trainer copy, weekly x8 (Rec.)"): a consistent snapshot (SQLite backup API, read-only source, nice 19) of the TRAINER's nightly replica `data/trade_journal.db` (never the live VM, never the stale root-level file), gzip, whole-file credential scan (a hit refuses), integrity_check + table counts, ONE new private dataset `metis-trade-journal-YYYYMMDD` per snapshot, a Kaggle kernel re-check and a runner SHA-256 read-back; the stamp keeps the snapshot list, keep-last 8, anything older is only LISTED (`beyond_retention`), never deleted. Mode `dbsize`: read-only size of `trade_journal.db`/`trainer_store.db` on the trainer (no upload). Copy only; nothing deleted on Kaggle or anywhere without the operator; never read on the trade path. |
| `kaggle-cold-lake-copy.yml` | Data pipeline | AUTONOMOUS | pull_request (token-gated: `[kaggle-copy-plan]` plans only, `[kaggle-copy-go]` plans + copies + verifies, `[kaggle-copy-verify]` re-runs only the verify matrix against the uploaded parts, optionally `[kaggle-copy-parts:p000,p003]`) | HF-LAKE-STORAGE-403 (operator 2026-11-05: "Go, full copy (Rec.)") — COPY of the FROZEN crypto history of the HF lake to private Kaggle datasets `metis-market-lake-pNNN`: plan from the HF tree listing (sliced by symbol into parts <= 22 GB, fails closed above 150 GB), one part per runner rebuilt from data.binance.vision (HF reads are refused at the cap) with a SHA-256 per member, a CPU Kaggle kernel (internet off) re-hashing every member, a runner sample re-hash, and an INDEX.json. Nothing is deleted anywhere (HF deletion needs a separate operator OK). |
| `ml-data-export-kaggle.yml` | Research | AUTONOMOUS | daily 06:40Z + dispatch | ML-DATA-OFF-TRAINER (2026-10-13) — publishes the MARKET-ONLY ML shards (`scripts/research/market_data_export.py::ALLOW`: BTC/ETH/SOL 15m+1h `market_features`/`market_raw`) as the PRIVATE Kaggle dataset `metis-market-data`. The runner pulls the allowlisted files from the trainer over the existing SSH route (nice 19, 20 MB/s; no VM timer, no credential on the VM), stages them with MANIFEST (sha256, rows, first/last ts, `stale_shards`, `withheld` for shards that disagree with their metadata), versions the dataset, then `verify-runner` (download + re-hash on a GitHub runner) and `verify-kaggle` (CPU kernel mounts + re-hashes) prove the published copy. OURS data is not in the allowlist and the dataset is never public. |
| `research-queue-chain.yml` | Research | AUTONOMOUS | `workflow_run` (research-queue-dispatch completed) + dispatch | PIPELINE-HEALTH-1021 — event-driven cadence for the dispatcher. MEASURED 2026-10-21: GitHub created the dispatcher's `20 * * * *` schedule runs 3-5 h apart and the keeper's own cron likewise, so cadence was bounded by pushes to main; a quiet main left 75-135 min gaps with 20-70 units runnable (watchdog `dispatcher` / `github_runner` self-heals 10-19, 10-21; 3.5 h `dispatcher_age_h`). When a dispatch run completes it waits until 60 min after that run was CREATED, then `gh workflow run research-queue-dispatch.yml` unless a newer run exists (cron/keeper carried it). Changes WHEN a cycle starts only; the dispatch concurrency group and stamp-PR checks are unchanged; cron + schedule-keeper stay as fallbacks. |
| `research-queue-replenish.yml` | Research | AUTONOMOUS | cron (daily 05:50) + dispatch | RQ-RUN — the queue REFILLS ITSELF: `scripts/research/queue_replenish.py` expands the pre-registered families under `research/templates/` into concrete units until >= 25 runnable units are queued -- runnable = the dispatcher would fire it within the next 6 h cycle, never bare `status: queued` (dedupe by `generated.key`, families by the operator's 30/25/20/15/10 weights) and lands them via `commit-to-main`; the PR self-lands only while `--verify` reproduces every unit byte-for-byte at the merge-base (`check_pr_landing.py` E58). schedule-keeper target with a `dedupe` job. |
| `research-queue-grade.yml` | Research | AUTONOMOUS | cron (every 6 h at :50) + dispatch | RQ-RUN — results are GRADED WITHOUT A SESSION: `scripts/research/queue_grade.py` reads each ran, mechanically-gradable unit's committed E5/corpus rows, applies its pre-registered rule (unanimity), and lands `status: done` / a confirmatory re-queue on a first FAIL / `grading.needs_review: true` for anything ambiguous. Self-lands only while `--verify` reproduces the edits (E58). |
| `research-store-admin.yml` | Research | AUTONOMOUS (manual dispatch) | dispatch | WSD-S6D (design D7) — admin commands of the trainer-VM research results store (`scripts/research/research_store.py`) over ssh via `.github/actions/research-store-ship`: `stats`, `parity --since` (report-only), `backfill` (loads main's history as `git_backfill`). The shadow dual-write itself rides `research-queue-dispatch.yml` / `research-queue-grade.yml` (`research-store` job). |
| `yfinance-lane-proof.yml` | Research | AUTONOMOUS | dispatch only | Proves the NON-CRYPTO candle lane (`fetch_backtest_candles.py --source yfinance`) on a real network — Yahoo 429s the dev sandbox, so the source is implementable but unverifiable there. Asserts a real book (rows > 0, schema, high ≥ low, no NaN closes) rather than a green exit, and REPORTS the span obtained against the span requested, since yfinance caps intraday history (~730 d at 1h, ~60 d at 15m) and a silent truncation reads exactly like a complete window. Dispatch-only; never runs on push. |
| `dukascopy-coverage-probe.yml` | Research | AUTONOMOUS | dispatch only | Asks whether Dukascopy covers the 18 symbols behind the blocked backtest cells. Driven by a MEASURED finding: yfinance REFUSES a >730 d 1h request outright (zero rows, proof run 32734360738), so the 8 x 1h legs cannot get their ~1825 d span there at any request size, and Dukascopy — years of 1m for FX/metals/index/ETF CFDs — is the candidate. ⚠️ It dumps the instrument CATALOGUE and name-matches; it does NOT declare coverage. `SPY -> ETF_CFD_US_SPY_US` is the same underlying, `MES -> an index CFD` is a DIFFERENT instrument tracking the same index, and merging those is the semantic substitution `diagnostic-provenance-guard` sub-class A forbids — so the mapping is left to a reader and unmatched symbols are printed explicitly rather than left as an absence. Read-only: lists names, fetches no candles, writes no data. Dispatch-only. |
| `dukascopy-span-probe.yml` | Research | AUTONOMOUS | dispatch only | How FAR BACK Dukascopy actually serves each blocked symbol's instrument. The sibling `dukascopy-coverage-probe.yml` answered EXISTENCE and `docs/research/dukascopy-coverage-adjudication-2026-08-24.md` adjudicated the mapping; both closed on an explicit caveat recorded in `ROADMAP.md` — *"Existence is not span, and span is the actual question — Dukascopy depth remains unmeasured."* This measures it, because the consumers ask for DEPTH: `e35-bracket-sweep.yml` fetches `days: 1830` per leg and yfinance REFUSES a >730 d 1h request outright (proof run 32734360738). An instrument that exists but carries 18 months of 1h bars does not unblock a 1830-day sweep. ⚠️ **FOUR states, never collapsed** — `bars` / `empty` (we looked, the venue has nothing) / `error` (**we did not look** — never folded into `empty`, since "no 2015 data" and "our request blew up" are opposite statements) / `unknown_instrument` (a MAPPING bug, not a depth fact). `earliest_bars_anchor` therefore always ships beside `anchors_errored`, and a run with any error is graded `lower_bound_some_anchors_errored` rather than `measured` — the number cannot be picked up without its caveat. ⚠️ It does NOT decide whether an instrument may stand in for our symbol; every row carries the adjudicated `relation` so a proxy's depth is never read as the real instrument's, and the two leveraged ETFs (`QLD`/`TQQQ`) are absent deliberately — the adjudication REFUSED a proxy because a daily leverage reset means the path is not N× the underlying. Its selftest gates the probe in-job (injected fake fetcher, no venue call), so a broken state machine cannot emit an authoritative-looking depth table. Directly feeds `BL-20260824-E35-SWEEP-FEED-IS-BINANCE-ONLY-FOR-A-MOSTLY-NON-CRYPTO-MATRIX`: whether that row's fix is a per-leg source resolver or a plan-time refusal depends on this answer. Read-only, free lane: ~66 three-day requests, no VM, no trainer, writes no repo data. Dispatch-only. |
| `egress-chromium-landing-probe.yml` | Research | AUTONOMOUS | PR touching `.github/egress-probe/run-request.txt`; dispatch (the temporary hourly schedule was removed 2026-09-30: PROP-TERM egress is parked, see pipeline row PI-20260930-3ZFMYYI4-0004) | Landing-only headless-Chromium reachability probe of Breakout's two terminal hosts from a GitHub-hosted runner's (Microsoft/Azure) egress (PROP-TERM egress scoping, 2026-09-30). Answers whether a real browser is SERVED, CHALLENGED or BANNED there; a plain `curl` can be scored differently. Fixed host allowlist inside `scripts/research/egress_chromium_landing_probe.py` (no url input), no credentials, nothing clicked or typed, prints the egress ORGANISATION only, never an address. Tier-1, no VM, no trading credential. Sessions cannot `workflow_dispatch`, so a session asks for a fresh measurement by bumping the request file in a PR; the run log is the result. **Optional proxy (2026-09-30):** the secret `EGRESS_PROBE_PROXY`, when set, sends the browser ONLY through that proxy, FAIL-CLOSED (`proxy_unreachable`, never a direct fallback); nothing about the proxy is printed; the secret is withheld from pull_request and non-main runs; the script evaluates the PASS rule itself (`--evaluate`, over schedule/dispatch runs on main only: three passing proxied runs at least an hour apart, same known egress organisation; the first failure, an errored run or a failed workflow run ends the route). **Levers (2026-09-30):** the dispatch input `variants` (comma-separated: `baseline`, `wait`, `newheadless`, `headed`) tries several ways of running the same unmodified Chromium through the same proxy in one run and prints a per-lever summary (first-load vs after-waiting result, `cleared_after_s`, challenge kind, exit country); the PASS rule counts only the default (`baseline`) lever; the others are diagnostics; nothing that hides automation is included. Permissions: contents read, actions read; no write. |
| `research-exit-head-replay-trainer.yml` | Research | AUTONOMOUS | label `exit-head-replay-request` / dispatch | The exit-head REPLAY leg, deliberately on the TRAINER VM rather than a free runner — it is one of only two hosts holding the published exit-head artifact. |
| `research-backtest-augment.yml` | Research | AUTONOMOUS | label `research-backtest-augment-request` / dispatch + cron (weekly) | A1 research-backtest-augment runner: the pinned pooled harness roster per symbol on a free runner. |
| `flip-override-walkforward.yml` | Research | AUTONOMOUS | label `flip-override-walkforward-request` / dispatch | Walk-forwards the flip-confidence override against the incumbent `hold` policy on the same folds (BL-20260811-FLIP-OVERRIDE-NEVER-WALKFORWARDED — the run that disarmed it). |
| `gld-compat-matrix.yml` | Research | AUTONOMOUS | label `gld-compat-matrix-request` / dispatch | GLD Track B (M36) per-account compatibility gate on a free runner (operator-approved 2026-08-02). |
| `prop-tp-r-gate.yml` | Research | AUTONOMOUS | label `prop-tp-r-gate-request` / dispatch | Prop EV/survival gate for the two LIVE Breakout donchian legs, swept across `tp_r` on free runners (operator decision 2026-08-24: "measure first, then decide"). Exists because `tp-sentinel-cap-venue-scope-PROPOSAL.md` option C describes itself as documentation-only and **is not**: the effective target is `min(cap_r, tp_r)` with `cap_r = 0.099*entry/risk`, a percent-of-entry against a multiple-of-risk, so NO `tp_r` reproduces the clamp and lowering it to 3.22/4.08 tightens the real target on **half the trades by the definition of the median** — on a prop account whose breach is TERMINAL, against an EV gate measured at 6.0. ⚠️ **The 6.0 arm in the SAME run is the control, never #8975's +$483/+$883 headline** (different data vintage + window; comparing across them compares two populations). The grid `{6.0,5.0,4.0,3.0,2.5}` and the accept criterion are fixed in the workflow header BEFORE any result, per criterion-first discipline. Fetches its own 5m candles per symbol and REFUSES a file under 100k rows (a short file is how a gate becomes a confident wrong answer); a 5m base is required because 1h would make the strategy/clock resamples no-ops and silently drop the intra-bar exit resolution a `tp_r` change moves. Each arm asserts its override reached the payload — a result labelled with an arm it did not run under is the class this exists to avoid. Verdict is `tee`d so the dispatching session can actually read it (BL-20260824-A-STEP-SUMMARY-IS-INVISIBLE-TO-THE-ACTIONS-API). Read-only: no push, no deploy, never touches `config/strategies.yaml` — the Tier-3 flip is the operator's separate call ON this evidence. |
| `macro-valuation-snapshot.yml` | Macro producer | AUTONOMOUS | cron (daily 07:30) + label / dispatch | M28 P1 — the off-VM FRED valuation-snapshot PRODUCER; appends the point-in-time log `comms/macro/valuation_snapshots.jsonl`. |
| `macro-valuation-backfill.yml` | Macro backfill | AUTONOMOUS | label `macro-valuation-backfill-now` / dispatch | M28 P1 "test now" loop — reconstructs historical point-in-time valuation snapshots from FRED so the gate can be graded without waiting for forward accrual. |
| `grade-closed-trades.yml` | Decision preparation | Tier-2 (SSH read of the live journal; commits data only) | cron (daily 03:10) + dispatch (`dry_run`, `since`) | **The GRADED hop of the trade pipeline, on a cadence (JC-SA-01, 2026-09-29).** It runs `scripts/ops/grade_closed_trades_action.sh` on the live VM with `ACTION_BY_TRADE=1`: sqlite mode=ro, the `_grade_package` rubric, one row per closed trade keyed on `linked_trade_id`. It then appends the delta to `comms/claude_strategy_scores.jsonl` through commit-to-main. It refuses a package-keyed (pre-deploy) grader and a truncated delta. Before this, grading ran only by hand inside `/system-review`, and it stopped 2026-09-08. The freshness check is the `grading-freshness` guard in `run_guards.py`, **ALERT-ONLY** since 2026-09-29 (operator, "let's do b"): `max(reviewed_at)` older than 3 days (or an unreadable file) prints a `::warning::` on a PR and exits 0. The daily alarm is `grading-freshness-alert.yml` (cron 04:10, after this workflow) — one `send-ping` per day while stale or unreadable, silent when fresh. |
| `grading-freshness-alert.yml` | Decision preparation | Tier-1 (reads the score file; dispatches `send-ping`) | cron (daily 04:10) + dispatch | Runs `scripts/ci/check_grading_freshness.py --alert` on `main`. Stale (>3d) or unreadable → ONE Telegram ping via `system-actions.yml` `send-ping`; fresh → silent. One run/day, so never one ping per PR. |
| `live-replay-parity.yml` | Verification | AUTONOMOUS | cron (daily 06:35) + label `live-replay-parity` / dispatch | **Live-vs-replay parity (LIVE-PARITY, 2026-10-03).** Opens an SSH tunnel to the live web-api and, on the runner, replays the LIVE `order_package()` of every execution:live real-money leg (+ cheap paper legs) over the same bars, diffing it per eval against `trade_journal.db::signals` (missed / live-only / side / candle mismatch, lost bars, dropped downstream). Commits `comms/live_parity/latest.{json,md}`; the brief §4 shows one line from it. Files a pipeline row per new finding and pings via send-ping on any real-money finding. Positive controls (planted defect, historical positive, end-to-end liveness) run every time. An issue-body `ref: <branch>` runs that branch's script without committing. |
| `strategy-review-packets.yml` | Decision preparation | AUTONOMOUS | cron (daily 04:40) + label `strategy-review-packets` / dispatch | **M7 decision packets, C3 of the operating-layer build.** Runs the review generator over every ENABLED strategy on the live VM and lands the result under `comms/strategy_reviews/<date>/`. ⚠️ `INDEX.json` is committed ALWAYS and carries every strategy graded including every HOLD — it is the DENOMINATOR; full packets are committed only where an action is proposed, because 52 strategies × daily would be ~19k files/yr. Before this, the generator had no cron and wrote to a gitignored path: `git log --all` over it returned 0 commits. |
| `econ-calendar-produce.yml` | Macro producer | AUTONOMOUS | cron (daily 22:30) + label / dispatch | ROADMAP_MACRO M1 — the economic-calendar spine producer's deterministic re-parse-and-land path (FMP + FRED). |
| `news-gdelt-panel.yml` | Research data producer | AUTONOMOUS | cron (daily 03:17) + dispatch | NEWS-ALPHA-CORPUS-SLICE1 — folds the GDELT 2.0 GKG 15-min files into the aggregate-on-ingest hourly news panel `comms/news_alpha/gdelt_panel/` (2023-10 onward, month matrix, raw files never stored, frozen map `research/news_alpha/entity_map_v1.json`); read by `scripts/research/news_alpha_ic.py`. |
| `econ-event-study.yml` | Macro research | AUTONOMOUS | cron (weekly Sun 23:10) + label / dispatch | ROADMAP_MACRO M1 — the economic-surprise → forward-price event study; joins point-in-time release history to the traded price series. |
| `alpaca-options-probe.yml` | Ops relay | AUTONOMOUS | `issues` (label) | Read-only Phase-0 probe for the Alpaca L3 options build — GETs only, places no order. |
| `reset-daily-risk-state.yml` | Ops action | OPERATOR-APPROVAL | label `reset-daily-risk-state` | One-shot: delete today's `daily_risk_state` row(s) so the RiskManager resets its intraday drawdown counter immediately rather than at midnight UTC. DB write — Tier 2. |
| `reset-instance.yml` | Infra | OPERATOR-APPROVAL | label `reset-instance` / dispatch | Out-of-band OCI instance RESET by display name — recovers a hung / SSH-dead VM when the in-band reboot path cannot be reached (built for the 2026-07-08 trainer OOM). |
| `vm-caddy-deploy.yml` | Ops deploy | OPERATOR-APPROVAL | label `vm-caddy-deploy` / dispatch | Installs / reloads the Caddy HTTPS front on the live VM (`ict-bot.duckdns.org` → `localhost:8001`) — the transport the Svelte SPA depends on and Streamlit does not. |
| `phone-probe-apk.yml` | Build | AUTONOMOUS (Tier 1) | push to `tools/phone-probe/**` / dispatch | Builds the phase-1a Android WebView probe (`tools/phone-probe/`) as a debug APK artifact and runs its page-side check in headless Chromium. Read-only app; touches no VM, order path or secret. Design: `docs/integrations/breakout-phone-executor-DESIGN.md` § 7.2. |
| `phone-executor-apk.yml` | Build | AUTONOMOUS (Tier 1) | push to `tools/phone-executor/**` / dispatch | Builds the phase-1b Breakout phone executor (`tools/phone-executor/`) as a RELEASE APK signed with a STABLE key held only in Actions secrets `PHONE_EXEC_KEYSTORE_B64` / `PHONE_EXEC_KEYSTORE_PASSWORD` (generated once by the workflow itself via `BRANCH_PROTECTION_TOKEN`, never printed), and runs the page-side check (`tools/phone-executor/test/exec_check.js`) in headless Chromium. Two jobs since 2026-10-15 (PI-20261015-QC5PFG9A-0001): `check` (debug compile, JVM unit tests, page-side check) on every push in a per-ref concurrency group; `apk` (signed release + upload) only on `main` / dispatch, in the shared `phone-executor-apk-signing` group, so branch pushes no longer cancel each other's pending jobs. Touches no VM. Design: `docs/integrations/breakout-phone-executor-DESIGN.md` § 7.11. |
| `phone-exec-js-sign.yml` | Build | AUTONOMOUS (Tier 1) | push to `main` touching `tools/phone-executor/app/src/main/assets/exec.js` (or itself) / dispatch | **Added 2026-10-18 (PHONE-EXEC-OBSERVABLE-1018, piece 4).** Signs the phone executor's page-side script with an ed25519 key held ONLY in the Actions secret `PHONE_EXEC_JS_SIGNING_KEY` (generated once by the workflow itself via `BRANCH_PROTECTION_TOKEN`, never printed) and publishes `{version, sha256, sig}` to the live API (`POST /api/bot/prop/phone/exec-js-signature`, `DASHBOARD_API_TOKEN`). The phone fetches the script from `GET /phone/exec.js`, verifies it against the public key the APK job embeds (`assets/exec_pubkey.b64`, derived from the same secret) and swaps it in without a reinstall; the server serves it only while its working tree matches the signed bytes (git-sync lag = `match: false`, re-served once it catches up). Prints the public key; refuses an unversioned script. Touches no VM state beyond one signature file beside the journal. |
