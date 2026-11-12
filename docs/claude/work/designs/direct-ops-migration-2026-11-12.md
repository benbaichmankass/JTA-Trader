# Direct-ops migration list (lane DIRECT-OPS-SWEEP, 2026-11-12)

> **Doc status:** `live` · category `plan` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md) · owning row `DIRECT-OPS-MIGRATION` · lane DIRECT-OPS-SWEEP

**Gates this adds or changes: none.** Each direct replacement keeps its § 2 tier. Only the pipe changes.

Operator, chat 2026-11-12 ~16:45Z, verbatim: *"The repo is for code. Configuration goes directly, configuration and
actions go directly from Claude to the VM. That is the only sanctioned flow ... Everything, the research queues, the
training VMs, all of those things go directly between Claude and the VM."*

## 1. Inventory (MEASURED 2026-11-12 ~17:00Z)

| Population | Open | Classified direct | Classified code | How classified |
|---|---|---|---|---|
| Work-store items (`GET /api/bot/work/items`, all 4,511 read; open = queued / in_flight / blocked / landed_unproven) | 1,541 | 622 | 919 | Rule-based, not item-by-item. Direct = `next_action: check_observation` (233) + `landed_unproven` builds (304); both are VM reads plus a work-store close. Plus 85 action-keyword candidates (backfill / regrade / retrain / set-env / restart …), which are **noisy** (e.g. ORDER-PATH-RESIDUE-2 matched and is code). |
| Research-queue units (`research/queue/*.yaml`) | 306 (290 queued, 16 blocked) | 306 | 0 | A unit is a run, not code. The harness it calls is code and stays in git. |
| Open issues | 727 | 723 | 0 | 637 `send-ping`, 25 other `system-action`, 2 `vm-diag-request`, 1 `sync-vm-secrets-request`, 58 other label-triggered requests. The remaining 4 are unlabelled logs or records. |
| Open PRs | 99 | 8 | 91 | `automation/*` heads (data commits, receipts, SLO status). |
| Workflows (`.github/workflows/*.yml`, 168) | 123 route actions or data through GitHub | 123 | | 102 trigger on `issues:` (label requests); 39 push `automation/` branches (some do both). |

## 2. Done direct now

- `vm-diag-request` #25327 (tradeify_1 executor `env_mode`) and #25324 (ib_paper open orders): answered directly from
  `/api/diag/journalctl` and `/api/diag/ib_open_orders`. No issue run is needed; the issues can close.
- The direct channel was probed: `POST /api/bot/ops/actions` authenticates and refuses unported actions with a pointer to the workflow.

## 3. Not runnable yet: why

- **#25351 set-env `PROP_PHONE_MODE_BREAKOUT_2=off` was CANCELLED and NOT RUN.** The `system-actions` concurrency group
  displaced it (cancel-guard comment, 15:11Z). The direct `set-env` (PR #25390) merged at ~17:00Z, and the VM answers it
  (a probe with empty params got its 400 validation message). #25390 merged without its § 2.3 row, so
  `tests/ops/test_ops_actions_parity.py` is red on main (2 of 7). #25402 adds the row. Tracked as work item
  `PI-20261112-DOPSSWEEP-0001`.
- `sync-vm-secrets` #24576: the secret values live in Actions secrets. That stays a workflow until secrets have a
  VM-side home. Operator-originated values only.

## 4. Direct actions built (one PR per class, smallest first)

| PR | Class | Actions |
|---|---|---|
| #25402 | notification | `send-ping` (Tier 1; replaces the 637-issue send-ping path, including `pr-landing-hold-merge-alarm.yml`) |
| #25403 (stacked on #25402) | read-only report | `status-check`, `disk-usage-report`, `list-listening-ports` (Tier 1) |
| #25390 (other lane, merged) | config | `set-env` (PROP_PHONE_MODE_* only); its missing § 2.3 row is added in #25402 |

## 5. Classes with no direct path yet, and the next step for each

- **C1 · live-VM actions over SSH (system-actions.yml and 19 other label workflows).** Port them one typed
  `ops_actions` entry at a time, smallest and most-used first. Next after #25403: `get-env` (masked read), `cap-vm-logs`,
  `prune-db-backups`, then the Tier-2 backfill / reconcile family (each with its own validated params). When the last
  caller of an action moves, retire that action's issue arm.
- **C2 · trainer-VM jobs.** The live VM has **no path to the trainer**: the trainer pulls from the live VM
  (`scripts/ops/sync_trainer_data.sh` ssh's trainer→live), and every trainer action today is a GitHub runner
  ssh'ing in. The direct shape is a **trainer-side pull**: a trainer unit polls a live-VM ops queue for typed trainer
  jobs (`train-cycle`, `trainer-diag`, `research-unit-run`) and posts its receipt back. This needs one decision before it
  is built: whether the trainer may hold a work-store-scoped token to poll the live API. That is a new credential path
  and therefore not built here.
- **C3 · runner compute on an issue label (40 workflows, e.g. regime-debt-matrix, gld-compat-matrix, c1-conviction-ab).**
  Research goes to the C2 trainer channel. Do **not** put it on the live VM: it runs CPU p95 99.7-99.9% (row
  LIVE-VM-CPU-SATURATION-1112). Report-shaped ones become VM read routes or ops report actions.
- **C4 · data commits on `automation/*` branches (21 workflows; 8 open PRs, e.g. #25393 / #25321 forecast-grade,
  #25319 live-review mirror, #25316 desk mirror, #25346 research-slo, #25099 receipt).** The data already sits on a VM.
  Serve it from the VM read API and stop committing it. Retire one branch family at a time, once its readers read the API.
- **Research-queue dispatch (`research-queue-dispatch.yml`, hourly on ubuntu-latest).** It dispatches 290 queued units
  through GitHub runners and lands results as commits. Moving it to the C2 trainer queue retires both the dispatch
  workflow and the result commits.
- **Stale issue backlog.** 662 open `system-action` issues are past requests (637 send-ping hold-merge alarms).
  Proposal: a bulk close, once the manager decides. Not done here.

## 6. Every workflow that routes an action or data through GitHub

Class tags come from a keyword scan of each workflow file (`issues:`, `automation/`, `VM_SSH_KEY`/`ssh`, `trainer`).
The `trainer` match is loose (any mention), so C2 overcounts against C1/C3.

| Workflow | Triggers | Class | Direct replacement |
|---|---|---|---|
| `account-broker-reconcile` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `alpaca-options-probe` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `alpaca-settlement-soak-watch` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `arm-candidate-diag` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `bootstrap-labels` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `branch-protection-report` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `broad-paths-corpus` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `broker-bracket-reconcile` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `broker-truth-freshness` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `cancel-queued-runs` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `ci-settled` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `claude-pr-automerge` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `compute-util-telemetry` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `cutover-live` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `dashboard-edge-watch` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `delete-merged-branches` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `deploy-candidate` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `desk-decisions-mirror` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `desk-scan-packet` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `diag-relay-sweep` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `doc-audit-weekly` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `e35-bracket-sweep` | automation branch, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `econ-calendar-produce` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `econ-event-study` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `etf-history-pipeline` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `exit-cell-mandate` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `external-comment-alert` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `external-issue-alert` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `flip-override-walkforward` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `get-diag-token` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `gld-compat-matrix` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `gpu-burst-train` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `grade-closed-trades` | automation branch, VM ssh | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `health-snapshot` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `hf-lake-storage` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `ict-scalp-exit-sweep` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `infra-runner-install` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `infra-runner-smoke` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `init-actions-secrets` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `issue-router` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `journal-offvm-backup` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `kaggle-backups` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `live-replay-parity` | issue label, automation branch, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `live-review-rows-mirror` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `live-review-wake` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `llm-delegate` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `m20-capture-census` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `m20-exit-lever-sweep` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `macro-producer-liveness` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `macro-valuation-backfill` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `macro-valuation-snapshot` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `market-data-lake` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `news-gdelt-panel` | automation branch, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `oci-capacity-report` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `oci-close-api-port` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `oci-grow-boot-volume` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `oci-inventory` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `oci-retire-orphan-volume` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `oi-feed-freshness` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `options-snapshot-capture` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `pr-automerge-disable` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `pr-close` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `pr-landing-hold-merge-alarm` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `pr-opener` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `probes` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `prop-report` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `prop-tp-r-gate` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `provision-live-vm` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `prune-landed-branches` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `prune-merged-claude-branch` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `purge-artifacts` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `pytest-run` | automation branch, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `r4-demotion-gate` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `replay-pregate-nightly` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `research-artifact-rescue` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `research-backtest-augment` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `research-exit-head-build` | issue label, automation branch, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `research-exit-head-replay-trainer` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `research-loss-detector` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `research-queue-dispatch` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `research-queue-grade` | automation branch, VM ssh, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `research-queue-replenish` | automation branch | C4 data commit (runner-produced) | write the output to the VM data dir through a typed ingest action, or keep only if it is code |
| `research-slo` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `research-watchdog` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `reserve-live-ip` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `reset-daily-risk-state` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `reset-instance` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `reset-protocol-backup` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `set-diag-token` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `soak-book-grade-weekly` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `sp500-membership-refresh` | issue label, automation branch | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `stale-automation-sweep` | automation branch, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `strategy-review-packets` | issue label, automation branch, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `sync-vm-secrets` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `system-actions-cancel-guard` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
| `system-actions` | issue label, automation branch, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `terminate-instance` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `trainer-boot-volume` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `trainer-capture-watch` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `trainer-console-connector-install` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `trainer-console-ingress` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `trainer-diag-relay` | automation branch, VM ssh, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `trainer-offload-train` | issue label, trainer | C2 trainer job (runner-side) | trainer job channel (C2) |
| `trainer-vm-diag` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `vm-bybit-diag` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-caddy-deploy` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-diag-snapshot` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `vm-driver` | automation branch, VM ssh, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `vm-fix-devnull` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-git-credential-bootstrap` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `vm-ib-gateway-deploy` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-ib-gateway-live-login-test` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-ib-gateway-recover` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-ib-gateway-selftest` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-ib-gateway-stop` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-ib-gateway-watchdog-enable` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-net-diag` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-net-fix` | issue label, VM ssh | C1 live-VM action over SSH | a typed `ops_actions` entry (one per action, same tier as its § 2 row); retire the issue label |
| `vm-resize-live` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `vm-web-api-recover` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `vwap-backtest` | issue label, VM ssh, trainer | C2 trainer-VM action over SSH | trainer job channel (C2 below): a typed trainer action, not an issue |
| `work-digest` | automation branch, trainer | C4 data commit pulled from a VM | serve from the VM read API; stop committing the data (retire the automation branch) |
| `work-store-outbox` | issue label | C3 runner compute / report on an issue label | research: trainer job channel (C2); report: a VM read route or an ops report action |
