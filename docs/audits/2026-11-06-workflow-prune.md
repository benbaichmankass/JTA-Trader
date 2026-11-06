# Workflow prune, 2026-11-06 (lane WORKFLOW-PRUNE)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · a **proposal** (nothing here is applied until the operator approves; the four approvals are recorded on PRs #23594 and #23600) · lane of Manager Session 2026-11-05b · measured 2026-11-06 · operator direction 2026-11-06 ~00:52Z, verbatim: *"Yes, let's continue the sweep"*, to the standard *"make sure that what left is designed optimally and efficiently and not redundant or repetitive"*.

**Gates this adds or changes: none.** Every row below is a proposal. **Nothing is deleted, merged or edited until the operator approves.** The only files this PR adds are this doc, the inventory script and its JSON.

## 1. Population, method, and what could not be read

- **Population:** all **212** files in `.github/workflows/`, each measured. The repo's `actions/workflows` listing returned 218 rows with duplicates (its pagination overlapped) and missed 17 files; those 17 were fetched by file name, so no workflow is missing. 6 entries the listing still shows have no file (`econ-source-probe`, `fmp-stable-probe`, `lake-parity`, `ping-relay`, `probe-vm-git-deploy-token-scope`, `pytest-diag`): they are deleted files, nothing to do. The dispatch said "about 192"; the measured count is 212.
- **Runs:** exact counts from `actions/workflows/<id>/runs` over 90 d (`created>=2026-08-08`). The API reports `total_count` capped at **2,500**, so any window that reached 2,500 was split in halves until it did not (the first pass without splitting under-counted; it was discarded). **Could-not-look: 0 failed reads** (`read_failures` is empty in the JSON).
- **Totals:** 535,502 runs in 90 d; 62,903 in the last 7 d, of which **32,702 (51%) were skipped**.
- **Job-hours/wk:** mean job-minutes over up to 6 non-skipped runs from the last 7 d, times the 7-d non-skipped run count. Sum **2,110 job-h/wk** over the workflows sampled. **11 workflows have no job sample** (their 7-d runs were all skipped, or none), shown as `-`, not 0. **Upper bound:** a cancelled run (concurrency cancel) counts as a full mean run, so the PR checks (`pytest-run`, `guards`) are over-stated. The sample is 6 runs, so a workflow with bimodal run lengths can be off by 2x. Rates are 7-d (the 90-d conclusion mix would need ~10x the reads).
- **Writes** come from a static read of each YAML (`git push`, `gh pr`, issue calls, `ssh`, ping calls); it can miss a write that sits in a helper script. **Readers** = the number of files in `.github/ scripts/ src/ config/ deploy/ .claude/` that mention the workflow's filename. Docs are excluded (every workflow is listed in `docs/github-actions-workflows.md`, so a doc hit proves nothing). A label-dispatched relay is invoked by an issue label, not by filename, so a low reader count for a relay means *not referenced by code*, not *nobody uses it*; the executed-run count is the stronger signal there.
- **Repro:** `python3 scripts/ops/workflow_prune_inventory.py --out comms/ci/workflow-prune-inventory-<date>.json` (read-only, `gh api` GETs). Data: `comms/ci/workflow-prune-inventory-2026-11-06.json`.

## 2. Headline

| class | workflows | job-h/wk | what it means |
|---|---|---|---|
| DELETE | 49 | 0 | never ran, retired by the reset, or only ever skipped. Saves **run-count noise, not runner time** (job-h is ~0) |
| DELETE? (operator call) | 21 | 0 | dormant (<=5 executions in 90 d) or a credential tool |
| MERGE | 41 | 345.0 | of which the two mirrors are 218.0 h/wk and retire with WORK-STORE S7, not before |
| SIMPLIFY | 7 | 260.0 | cheaper trigger or cadence; `work-digest` alone is 140.7 h/wk |
| KEEP | 94 | 1505.2 | includes the never-touch set; `pytest-run` + `guards` are 1023.1 h/wk of it |

**Where the runner time goes (MEASURED, 7 d):** `pytest-run` and `guards` (required PR checks) are the largest consumers and stay. The next four are all things this prune can address: `work-digest` (push-triggered, though its header says a daily roll-up), the two mirror workflows (WORK-STORE retires them), and `research-script-run`. **Deleting the dead workflows frees almost no runner time**; the real savings are in SIMPLIFY and in S7. The DELETE class is worth doing for the reason the operator gave (not redundant, not repetitive; ~105 relays each get a skipped run on every issue event), not for cost.

## 3. Findings that are not prune proposals (filed here, each needs an owner)

1. **`branch-protection-sync` is RED on ~45% of its runs** (724 of 1,610 in 7 d); the failing step is `PUT branch protection on main`. Its own header says protection is live and load-bearing since 2026-07-30 and that a missing `BRANCH_PROTECTION_TOKEN` fails it red on purpose. I did not read the job log to the root cause: that is the next step for whoever owns it, and the token is an operator action if that is the cause. It also runs on every push to `main` though it only needs to run when its own file changes (S3).
2. **`sp500-membership-refresh` has 183 runs/wk and 0 executed in 90 d**: a scheduled data pull that only ever skips. Either its `if:` can never be true, or the pull does not run. It is on the never-touch list (data pulls), so it is flagged, not proposed.
3. **`schedule-keeper` is red on 218 of 1,758 runs/wk (12%).** It is built to page when a validator stops, so some red may be intended; unverified.
4. **Issue-event fan-out.** About 105 workflows listen on `issues`. Each issue event starts a run of every one of them and ~all skip: 216 issue events/wk (430 with label events) produce the ~30,500 skipped runs/wk. A single router on `issues` that calls the relay it needs would remove that. Not proposed as a row: it changes the dispatch mechanism for every relay, including the never-touch ones, so it needs its own design and operator OK.
5. **`repo-inventory` (RESOLVED, an artifact of my 7-day window, not a live trigger).** The API shows its last `pull_request` run at 2026-11-03T23:40Z and last `push` run at 23:38Z; since 2026-11-04 it has 0 PR and 0 push runs and 2 `schedule` runs (latest 11-05T12:45Z), matching its cron-only YAML (a test pins that). The ~2,450 runs and 36.3 job-h in my 7-day window (10-30 to 11-06) are the days before the trigger was removed. **Every 7-day run and job-h figure in this doc is overstated for any workflow whose trigger changed inside that window**; the post-merge re-measure is the clean read. Proposal changed from SIMPLIFY to KEEP.

## 4. The four decisions for the operator (nothing happens until each is answered)

**P1. Delete the workflows with no life left: 21 files.** 8 never ran in 90 d (`continue-work`, `deploy-trainer-bootstrap`, `hf-cron`, `oci-storage` …) and 13 were retired by the 2026-09-21 operating reset or E29 and have not executed in 7 d (`board-heartbeat`, `board-post`, `board-rotate`, `constraint-readout` …). Each has its retirement stated in its own header or 0 runs. Runner time freed: ~0; the point is that nothing reads them.

**P2. Delete the relays that only ever skip: 28 files** (one-shot backfills, regime/mNN grade relays, provision/test relays that listened on every issue event and executed 0 times in 90 d): `c1-conviction-ab`, `cot-positioning-backfill`, `crypto-signals-backfill`, `econ-calendar-backfill`, `econ-calendar-survey-backfill`, `ict-scalp-backtest` …. Kept out of this group on purpose: the two external-activity tripwires (an alarm that never fired is not dead), `cancel-queued-runs`, `reset-daily-risk-state`, `vm-caddy-deploy`, `sp500-membership-refresh`. Optional add-on, your call per row: **21 dormant or credential tools** (executed <=5 times in 90 d, e.g. `ci-settled`, `dukascopy-coverage-probe`, `dukascopy-span-probe`, `egress-chromium-landing-probe`, `ict-scalp-exit-sweep` …), including `rotate-account-keys` (0 runs, but it is the key-rotation break-glass).

**P3. Merge duplicates: 41 workflows into ~8 groups.** research-script-run ×5 → 1 with a `target` input; 3 branch pruners → 1; 9 VM/OCI lifecycle relays → 1; 5 runner/console install-smoke-health relays → 1; two external alerts → 1; ~13 freshness/liveness watchdogs → 1 list-driven watcher (needs its own design lane); the VM diag/fix overlap; and the **two mirror workflows (218.0 job-h/wk, the biggest single saving)**, which I propose to retire together with WORK-STORE S7 because their readers (`src` 6 + `scripts` 19, WORK-STORE-DESIGN § 1) still read the mirrored files until S6B lands. Merges touching relays on the never-touch list are limited to the rarely-used ones.

**P4. Simplify 7 workflows (~260.0 job-h/wk now; `repo-inventory` was dropped from the 8, see finding 5):** `work-digest` 140.7 h/wk (cadence instead of every main push), `pr-landing-hold-merge-alarm` / `armed-branch-push-watch` / `branch-mirror-heartbeat` (add the bookkeeping `paths-ignore`; the 2026-09-28 'post-merge alarm' ruling is unchanged), `branch-protection-sync` (own-file path scope + fix the red), `research-queue-chain` and `research-slo` (long hosted-slot holds). Savings are estimates until the trigger change is measured.

## 5. Never touched, and why

Per the dispatch: deploy/git-sync, `system-actions` (+ its cancel guard), trading-path relays (`vm-diag-snapshot`, `trainer-vm-diag`, `trainer-diag-relay`, diag-token relays, `health-snapshot`), the gateway and web-api recovery relays, data pulls the trader needs, the required PR checks, and anything under an operator ruling: `forecast-grade` (operator 2026-11-01, *"run at least hourly and grade all decisions"*), the mirrors (operator 2026-10-26 design, changed only by WSD D4 once approved), `pr-landing-hold-merge-alarm` (operator 2026-09-28, option B), and the research loop (OPERATING-PLAN). Their rows say `KEEP, never-touch: <reason>`. A row may carry both a never-touch reason and a SIMPLIFY/MERGE when the change leaves what the ruling protects intact; those are called out in the reason.

## 6. All workflows

`writes`: commit = pushes to a branch, pr = opens/merges PRs, issue = issue/comment calls, vm = ssh/VM, ping = Telegram. `-` = not measured/none. `readers` = code files naming it (docs excluded).

| workflow | trigger | runs/90d | runs/7d (skipped) | job-h/wk | fail/7d | writes | readers | proposal | reason |
|---|---|---:|---:|---:|---:|---|---|---|---|
| `board-heartbeat` | dispatch | 50 | 0 (0) | 0.0 | 0 | issue | 1 (merge-claim-audit.yml) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `board-post` | push | 409 | 0 (0) | 0.0 | 0 | commit/issue | 23 (mi-182-board-cap-successor.j) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `board-rotate` | push,dispatch | 7 | 0 (0) | 0.0 | 0 | commit/issue | 6 (mi-182-board-cap-successor.j) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `c1-conviction-ab` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `constraint-readout` | dispatch | 19 | 0 (0) | 0.0 | 0 | - | 13 (SKILL.md) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `continue-work` | repository_dispatch,dispatch | 0 | 0 (0) | 0.0 | 0 | commit | 3 (session-reaper.yml) | **DELETE** | 0 runs in 90 d |
| `cot-positioning-backfill` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `crypto-signals-backfill` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `deploy-trainer-bootstrap` | push,dispatch | 0 | 0 (0) | 0.0 | 0 | issue/vm | 1 (research-exit-head-replay-tr) | **DELETE** | 0 runs in 90 d |
| `due-list` | issue-label,dispatch | 1,422 | 216 (216) | 0.0 | 0 | issue | 27 (mi280-due-list-token-blindne) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `econ-calendar-backfill` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `econ-calendar-survey-backfill` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `error-feed-digest` | dispatch | 112 | 0 (0) | 0.0 | 0 | - | 9 (lane4-sweep-cadence-20260910) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `hf-cron` | dispatch | 0 | 0 (0) | 0.0 | 0 | - | 0 | **DELETE** | 0 runs in 90 d |
| `ict-scalp-backtest` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 3 (research-panel-build.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `m28-value-grade` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | commit/issue | 1 (m31-implied-vol-grade.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `m31-implied-vol-grade` | issue-label,dispatch | 2,697 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `m32-credit-curve-grade` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `m33-seasonality-grade` | issue-label,dispatch | 2,697 | 215 (215) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `m34-xfamily-grade` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `merge-claim-audit` | dispatch | 1,533 | 0 (0) | 0.0 | 0 | issue | 5 (mi83-board-ceiling-addendum.) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `news-key-check` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `oci-storage` | dispatch | 0 | 0 (0) | 0.0 | 0 | vm | 1 (journal_offvm_backup.py) | **DELETE** | 0 runs in 90 d |
| `oci-storage-verify` | dispatch | 0 | 0 (0) | 0.0 | 0 | issue/vm | 0 | **DELETE** | 0 runs in 90 d |
| `pr-queue-watch` | dispatch | 74 | 0 (0) | 0.0 | 0 | - | 13 (mi279-ci-skip-directive-dete) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `provision-gateway-vm` | issue-label,dispatch | 5,381 | 430 (430) | 0.0 | 0 | issue/vm | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `provision-ib-gateway` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 2 (vm-ib-gateway-stop.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `provision-training-vm` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 4 (provision-gateway-vm.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `provision-training-vm-auto-retry` | dispatch | 0 | 0 (0) | 0.0 | 0 | issue/vm | 0 | **DELETE** | 0 runs in 90 d |
| `reconcile-open-prs` | dispatch | 898 | 0 (0) | 0.0 | 0 | commit | 4 (pr-queue-watch.yml) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `regime-adx-cutpoint-sweep` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 1 (regime_adx_cutpoint_sweep.py) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `regime-cell-walkforward` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 1 (regime_cell_walkforward.py) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `regime-debt-matrix` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 1 (regime_debt_matrix.py) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `research-e2-horizon-arm` | dispatch | 0 | 0 (0) | 0.0 | 0 | - | 0 | **DELETE** | 0 runs in 90 d |
| `research-panel-build` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 2 (research-exit-head-build.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `research-symbol-p0-build` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `scope-overlap-audit` | dispatch | 1,851 | 0 (0) | 0.0 | 0 | issue | 9 (mi83-board-ceiling-addendum.) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `session-reaper` | dispatch | 2,394 | 0 (0) | 0.0 | 0 | commit | 13 (mi280-sunset-pass-push-route) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `sunset-pass` | dispatch | 3 | 0 (0) | 0.0 | 0 | commit | 6 (mi279-workflow-push-target-g) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `sysdyn-gas-calibrate` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 1 (m28-value-grade.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `test-alpaca-creds` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | issue | 1 (alpaca-options-probe.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `test-alpaca-from-vm` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `training-run` | push,dispatch | 0 | 0 (0) | 0.0 | 0 | commit/pr | 2 (hf-cron.yml) | **DELETE** | 0 runs in 90 d |
| `vix-term-backtest` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `vm-cloud-fix` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 1 (vm-cloud-open-ib-port.yml) | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `vm-cloud-open-ib-port` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `vm-devnull-deploy-bootstrap` | issue-label,dispatch | 5,381 | 430 (430) | 0.0 | 0 | issue/vm | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `vm-devnull-source-diagnose` | issue-label,dispatch | 5,381 | 430 (430) | 0.0 | 0 | issue/vm | 0 | **DELETE** | listed on every issue event but 0 executed runs in 90 d (all skipped); one-shot/backfill/test/provision relay |
| `work-decision-commit` | dispatch | 109 | 0 (0) | 0.0 | 0 | vm | 3 (mi279-u5-decision-roundtrip-) | **DELETE** | retired by the 2026-09-21 operating reset / E29 (own header); 0 executed runs in 7 d |
| `ci-settled` | push,dispatch | 8 | 0 (0) | 0.0 | 0 | commit | 1 (ci_settled.sh) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `dukascopy-coverage-probe` | dispatch | 5 | 0 (0) | 0.0 | 0 | - | 2 (dukascopy-span-probe.yml) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `dukascopy-span-probe` | dispatch | 1 | 0 (0) | 0.0 | 0 | commit | 5 (check_research_workflow_land) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `egress-chromium-landing-probe` | PR,dispatch | 21 | 0 (0) | 0.0 | 0 | - | 1 (lane-egress-park.json) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `ict-scalp-exit-sweep` | push,dispatch | 12 | 0 (0) | 0.0 | 0 | issue/vm | 4 (SKILL.md) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `kaggle-gpu-pilot` | dispatch | 2 | 0 (0) | 0.0 | 0 | - | 1 (research-script-run-kaggle.y) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `llm-delegate` | dispatch | 25 | 0 (0) | 0.0 | 0 | issue | 1 (SKILL.md) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `m20-capture-census` | push,dispatch | 8 | 0 (0) | 0.0 | 0 | issue/vm | 1 (m20-exit-lever-sweep.yml) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `phone-probe-apk` | push,dispatch | 21 | 0 (0) | 0.0 | 0 | - | 0 | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `pr-automerge-disable` | push | 1 | 0 (0) | 0.0 | 0 | commit/pr | 0 | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `pr-close` | push | 10 | 0 (0) | 0.0 | 0 | commit | 3 (merge-claim-audit.yml) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `pullback-frac-cross-leg-sweep` | dispatch | 3 | 0 (0) | 0.0 | 0 | - | 0 | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `ranking-key-ab` | push,dispatch | 3,476 | 0 (0) | 0.0 | 0 | - | 3 (mi280-u127-ranking-key-ab-fi) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `research-script-run-data` | dispatch | 6 | 0 (0) | 0.0 | 0 | - | 6 (collect_runner_results.py) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `research-script-run-kaggle` | dispatch | 15 | 0 (0) | 0.0 | 0 | - | 10 (SKILL.md) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `rotate-account-keys` | dispatch | 0 | 0 (0) | 0.0 | 0 | vm | 4 (SKILL.md) | **DELETE?** | 0 runs in 90 d, but it is the account-key rotation tool (credential break-glass): operator call |
| `training-rerun-5m` | push,dispatch | 21 | 0 (0) | 0.0 | 0 | commit | 2 (ci-training-trigger-main-onl) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `vm-driver` | push | 2 | 0 (0) | 0.0 | 0 | commit/vm | 2 (reland-1c-disposition-202609) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `vm-fix-devnull` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 0 | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `vm-ib-gateway-live-login-test` | issue-label,dispatch | 5,381 | 430 (430) | 0.0 | 0 | issue/vm | 3 (gpu-burst-train.yml) | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `yfinance-lane-proof` | dispatch | 19 | 0 (0) | 0.0 | 0 | - | 0 | **DELETE?** | dormant: executed <=5 times in 90 d, none in 7 d (one-shot or superseded); operator call |
| `alpaca-settlement-soak-watch` | cron,dispatch | 50 | 5 (0) | 0.2 | 0 | issue | 1 (check_cadence_liveness.py) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `arm-candidate-diag` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 0 | **MERGE** | overlapping VM diag/fix relays: fold the rarely-used ones into vm-diag-snapshot kinds (trading-path relay itself untouched) |
| `broker-truth-freshness` | cron,dispatch | 83 | 17 (0) | 0.4 | 0 | issue | 1 (check_cadence_liveness.py) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `dashboard-edge-watch` | issue-label,cron,dispatch | 1,491 | 243 (214) | 0.5 | 0 | issue/ping | 2 (check_cadence_liveness.py) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `delete-merged-branches` | issue-label | 2,698 | 216 (215) | 0.1 | 0 | commit/issue | 0 | **MERGE** | three branch pruners: one `branch-prune` with a mode |
| `desk-decisions-mirror` | push,cron,dispatch | 887 | 608 (0) | 82.0 | 1 | - | 12 (SKILL.md) | **MERGE** | mirror workflows WORK-STORE S6B/S7 retire (D4): retire with S7, not before; readers still read the mirrored files |
| `diag-relay-sweep` | cron,dispatch | 91 | 7 (0) | 0.0 | 0 | issue | 4 (vm-diag-snapshot.yml) | **MERGE** | overlapping VM diag/fix relays: fold the rarely-used ones into vm-diag-snapshot kinds (trading-path relay itself untouched) |
| `external-comment-alert` | issue_comment | 4,326 | 546 (546) | 0.0 | 0 | issue/ping | 1 (telegram_channels.py) | **MERGE** | two near-identical external-activity alerts: one |
| `external-issue-alert` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | issue/ping | 2 (external-comment-alert.yml) | **MERGE** | two near-identical external-activity alerts: one |
| `grading-freshness-alert` | cron,dispatch | 77 | 14 (0) | 0.1 | 0 | ping | 8 (SKILL.md) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `infra-runner-health` | cron,dispatch | 125 | 125 (0) | 0.3 | 3 | vm | 5 (infra-health-keeper.json) | **MERGE** | runner/console install-smoke-health trio: one `infra-runner` with a step input |
| `infra-runner-install` | issue-label,dispatch | 149 | 149 (147) | 0.1 | 0 | issue/vm | 1 (install_infra_runner.sh) | **MERGE** | runner/console install-smoke-health trio: one `infra-runner` with a step input |
| `infra-runner-smoke` | issue-label,dispatch | 149 | 149 (147) | 0.1 | 1 | issue/vm | 2 (infra-runner-install.yml) | **MERGE** | runner/console install-smoke-health trio: one `infra-runner` with a step input |
| `live-review-rows-mirror` | push,cron,dispatch | 923 | 644 (0) | 136.0 | 2 | - | 7 (REVIEWER-BRIEF.md) | **MERGE** | mirror workflows WORK-STORE S6B/S7 retire (D4): retire with S7, not before; readers still read the mirrored files |
| `macro-producer-liveness` | issue-label,cron,dispatch | 2,788 | 223 (215) | 0.2 | 0 | issue/ping | 4 (dashboard-edge-watch.yml) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `main-tree-watch` | cron,dispatch | 243 | 27 (0) | 0.4 | 0 | - | 5 (guards.yml) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `mirror-orphan-watch` | cron,dispatch | 30 | 7 (0) | 0.2 | 0 | - | 2 (live-review-wake.yml) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `oci-capacity-report` | issue-label,dispatch | 175 | 175 (174) | 0.0 | 0 | issue | 0 | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `oci-grow-boot-volume` | issue-label,dispatch | 166 | 166 (164) | 0.1 | 0 | issue/vm | 1 (oci_grow_boot_volume.py) | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `oci-inventory` | issue-label,cron,dispatch | 1,692 | 217 (216) | 0.0 | 0 | issue/ping | 9 (SKILL.md) | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `oci-retire-orphan-volume` | issue-label,dispatch | 1,025 | 216 (216) | 0.0 | 0 | issue | 0 | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `oi-feed-freshness` | cron,dispatch | 20 | 20 (0) | 0.3 | 0 | issue | 2 (check_cadence_liveness.py) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `provision-live-vm` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 0 | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `prune-landed-branches` | issue-label,dispatch | 1,562 | 215 (215) | 0.0 | 0 | commit/issue | 0 | **MERGE** | three branch pruners: one `branch-prune` with a mode |
| `prune-merged-claude-branch` | issue-label,dispatch | 1,547 | 216 (216) | 0.0 | 0 | commit/issue | 1 (bootstrap-labels.yml) | **MERGE** | three branch pruners: one `branch-prune` with a mode |
| `research-loss-detector` | cron,dispatch | 86 | 14 (0) | 7.3 | 9 | ping | 7 (lane-fix-research-loss-recei) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `research-script-run` | dispatch | 1,632 | 549 (0) | 90.6 | 107 | - | 86 (SKILL.md) | **MERGE** | five research-script-run variants differ only by runner target: one workflow with a `target` input (callers: research-queue-dispatch) |
| `research-script-run-kaggle-cpu` | dispatch | 171 | 85 (0) | 14.0 | 35 | - | 8 (collect_runner_results.py) | **MERGE** | five research-script-run variants differ only by runner target: one workflow with a `target` input (callers: research-queue-dispatch) |
| `research-script-run-trainer` | dispatch | 73 | 1 (0) | 0.0 | 0 | vm | 16 (SKILL.md) | **MERGE** | five research-script-run variants differ only by runner target: one workflow with a `target` input (callers: research-queue-dispatch) |
| `research-watchdog` | cron,dispatch | 127 | 30 (0) | 1.4 | 21 | ping | 4 (SKILL.md) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `reserve-live-ip` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 3 (SKILL.md) | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `reset-instance` | issue-label,dispatch | 5,379 | 429 (428) | - | 0 | issue/vm | 0 | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `stale-automation-sweep` | cron,dispatch | 238 | 24 (0) | 1.1 | 1 | - | 8 (lane4-stale-automation-landi) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `terminate-instance` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 1 (oci-inventory.yml) | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `trainer-boot-volume` | issue-label,dispatch | 1,038 | 216 (216) | 0.0 | 0 | issue/vm | 1 (oci_trainer_boot_volume.py) | **MERGE** | OCI/VM lifecycle relays (capacity, grow, retire, reserve, terminate, reset): one `oci-lifecycle` with an action input |
| `trainer-capture-watch` | issue-label,cron,dispatch | 1,568 | 236 (212) | 9.4 | 1 | ping/vm | 5 (lane-fix-research-loss-recei) | **MERGE** | freshness/liveness watchdogs that each read a feed and ping: one `freshness-watch` driven by a list (needs its own design lane) |
| `trainer-console-connector-install` | issue-label,dispatch | 34 | 34 (30) | 0.1 | 0 | issue/vm | 0 | **MERGE** | runner/console install-smoke-health trio: one `infra-runner` with a step input |
| `trainer-console-ingress` | issue-label,dispatch | 48 | 48 (45) | 0.1 | 0 | issue/vm | 0 | **MERGE** | runner/console install-smoke-health trio: one `infra-runner` with a step input |
| `vm-bybit-diag` | issue-label,dispatch | 5,381 | 430 (428) | - | 0 | issue/vm | 0 | **MERGE** | overlapping VM diag/fix relays: fold the rarely-used ones into vm-diag-snapshot kinds (trading-path relay itself untouched) |
| `vm-net-diag` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **MERGE** | overlapping VM diag/fix relays: fold the rarely-used ones into vm-diag-snapshot kinds (trading-path relay itself untouched) |
| `vm-net-fix` | issue-label,dispatch | 2,697 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **MERGE** | overlapping VM diag/fix relays: fold the rarely-used ones into vm-diag-snapshot kinds (trading-path relay itself untouched) |
| `armed-branch-push-watch` | push | 7,877 | 1,165 (0) | 16.1 | 1 | commit | 3 (mi280-armed-branch-push-watc) | **SIMPLIFY** | push-to-main trigger with no paths-ignore: add the bookkeeping ignore list branch-sync/work-digest already carry |
| `branch-mirror-heartbeat` | push,dispatch | 2,286 | 1,610 (0) | 2.4 | 0 | - | 2 (desk-decisions-mirror.yml) | **SIMPLIFY** | push-to-main trigger with no paths-ignore: add the bookkeeping ignore list branch-sync/work-digest already carry |
| `branch-protection-sync` | push,dispatch | 9,406 | 1,610 (0) | 4.0 | 724 | - | 9 (branch-protection-report.yml) | **SIMPLIFY** | push-to-main trigger; scope to its own file; also RED ~45% of runs (PUT protection step fails) |
| `pr-landing-hold-merge-alarm` | push | 7,269 | 1,610 (0) | 23.1 | 0 | issue/ping | 2 (jc-ca-04-hold-merge-alarm.js) | **SIMPLIFY** | push-to-main trigger with no paths-ignore: add the bookkeeping ignore list branch-sync/work-digest already carry |
| `repo-inventory` | cron,dispatch | 28,169 | 2,446 (0) | 36.3 | 0 | - | 1 (check_cadence_liveness.py) | **KEEP** | trigger already cut to daily cron + dispatch ~2026-11-03; the 7-day figure counted the earlier PR/push runs (finding 5) |
| `research-queue-chain` | dispatch,workflow_run | 113 | 72 (0) | 36.2 | 0 | - | 1 (pipeline-health-1021-a.json) | **SIMPLIFY** | holds a hosted slot while waiting (COMPUTE-ALLOCATION B8 submit-and-exit) |
| `research-slo` | cron,dispatch | 298 | 100 (0) | 37.4 | 10 | ping | 6 (SKILL.md) | **SIMPLIFY** | holds a hosted slot while waiting (COMPUTE-ALLOCATION B8 submit-and-exit) |
| `work-digest` | push,dispatch | 8,198 | 1,114 (0) | 140.7 | 3 | - | 13 (mgr-heartbeat-0100-20260909.) | **SIMPLIFY** | push-triggered 1,100+/wk though its own header says a daily roll-up (operator 2026-09-01): run on a cadence, not every main push |
| `account-broker-reconcile` | cron,dispatch | 126 | 19 (0) | 0.4 | 0 | issue | 4 (lane-recon-broker-reconcile.) | **KEEP** | never-touch: money path |
| `account-mode-verify` | push | 49 | 9 (0) | 0.3 | 0 | - | 6 (automation-set-account-mode-) | **KEEP** | never-touch: money path |
| `alpaca-options-probe` | issue-label | 2,698 | 216 (214) | - | 0 | issue | 0 | **KEEP** | active; no overlap found at this read depth |
| `bootstrap-labels` | push,dispatch | 21 | 7 (0) | 0.0 | 0 | issue | 15 (settings.json) | **KEEP** | never-touch: label source for relays |
| `branch-protection-report` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **KEEP** | active; no overlap found at this read depth |
| `branch-sync` | push,dispatch | 3,805 | 1,116 (0) | 73.5 | 3 | - | 1 (branch_sync.py) | **KEEP** | active; no overlap found at this read depth |
| `broad-paths-corpus` | issue-label,dispatch | 216 | 216 (214) | 5.8 | 1 | issue | 1 (broad_paths_corpus.py) | **KEEP** | active; no overlap found at this read depth |
| `broker-bracket-reconcile` | cron,dispatch | 268 | 17 (0) | 0.6 | 0 | issue | 5 (account-broker-reconcile.yml) | **KEEP** | never-touch: money path |
| `cancel-queued-runs` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 0 | **KEEP** | active; no overlap found at this read depth |
| `cf-bulk-backtest` | dispatch | 1 | 1 (0) | 1.8 | 0 | - | 1 (cf_bulk.py) | **KEEP** | active; no overlap found at this read depth |
| `claude-pr-automerge` | push | 5,251 | 671 (0) | 9.8 | 4 | commit | 45 (action.yml) | **KEEP** | never-touch: PR landing |
| `claude-run-failure-alert` | workflow_run | 57,025 | 6,555 (5,066) | 2.0 | 0 | ping | 20 (mi280-u118-econ-calendar-str) | **KEEP** | active; no overlap found at this read depth |
| `compute-util-telemetry` | issue-label,cron,dispatch | 596 | 223 (210) | 5.6 | 0 | ping/vm | 1 (check_cadence_liveness.py) | **KEEP** | active; no overlap found at this read depth |
| `counterfactual-grade-closed` | cron,dispatch | 28 | 27 (0) | 5.8 | 1 | - | 4 (check_cadence_liveness.py) | **KEEP** | never-touch: grading |
| `cutover-live` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 5 (SKILL.md) | **KEEP** | never-touch: deploy/cutover |
| `deploy-candidate` | issue-label,dispatch | 5,381 | 430 (429) | - | 0 | issue/vm | 2 (mi-266-secret-map-jwt-webapp) | **KEEP** | never-touch: deploy |
| `desk-scan-packet` | cron,dispatch | 263 | 177 (0) | 6.5 | 2 | commit | 9 (SKILL.md) | **KEEP** | never-touch: trade desk |
| `doc-audit-weekly` | issue-label,cron,dispatch | 2,711 | 217 (216) | 0.0 | 0 | issue | 2 (pytest-run.yml) | **KEEP** | active; no overlap found at this read depth |
| `e35-bracket-sweep` | dispatch | 94 | 16 (0) | 13.1 | 3 | commit | 18 (lane-e54-dispatcher-dry-run.) | **KEEP** | active; no overlap found at this read depth |
| `econ-calendar-produce` | issue-label,cron,dispatch | 2,787 | 223 (216) | 4.6 | 0 | issue | 5 (econ-event-study.yml) | **KEEP** | never-touch: data pull |
| `econ-event-study` | issue-label,cron,dispatch | 2,711 | 217 (216) | 0.3 | 0 | issue | 2 (check_cadence_liveness.py) | **KEEP** | active; no overlap found at this read depth |
| `etf-history-pipeline` | issue-label,cron,dispatch | 207 | 207 (169) | 20.4 | 24 | issue/vm | 7 (etf-history-pipeline-2.json) | **KEEP** | never-touch: data pull |
| `exit-cell-mandate` | cron,dispatch | 76 | 14 (0) | 0.1 | 0 | commit/issue/ping/pr | 5 (pathb-exit-cell-runner.json) | **KEEP** | never-touch: mandate |
| `flip-override-walkforward` | issue-label,dispatch | 2,597 | 216 (216) | 0.0 | 0 | issue | 0 | **KEEP** | active; no overlap found at this read depth |
| `forecast-grade` | cron,dispatch | 113 | 113 (0) | 33.2 | 3 | - | 6 (forecast-grade-freshness.jso) | **KEEP** | never-touch: operator 2026-11-01: run at least hourly |
| `get-diag-token` | issue-label,dispatch | 2,699 | 216 (216) | 0.0 | 0 | issue/vm | 1 (check_workflow_catalog.py) | **KEEP** | never-touch: diag token |
| `gitleaks-history-weekly` | cron,dispatch | 7 | 1 (0) | 0.1 | 1 | - | 1 (check_cadence_liveness.py) | **KEEP** | active; no overlap found at this read depth |
| `gld-compat-matrix` | issue-label,dispatch | 2,742 | 216 (216) | 0.0 | 0 | issue | 2 (gld_compat_extract.py) | **KEEP** | active; no overlap found at this read depth |
| `gpu-burst-train` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | commit/issue/vm | 15 (lane-e61-arm-gpu-bursts.txt) | **KEEP** | active; no overlap found at this read depth |
| `grade-closed-trades` | cron,dispatch | 79 | 14 (0) | 1.9 | 0 | vm | 8 (SKILL.md) | **KEEP** | never-touch: money path grading |
| `guards` | merge_q,PR,cron,dispatch | 29,619 | 3,431 (0) | 463.8 | 469 | ping | 32 (ci-streamline-alarm.json) | **KEEP** | never-touch: required check |
| `health-snapshot` | issue-label,cron,dispatch | 3,022 | 237 (216) | 0.4 | 0 | issue/ping/pr/vm | 8 (SKILL.md) | **KEEP** | never-touch: diag relay |
| `hf-lake-kaggle-pilot` | PR | 12 | 12 (0) | 0.7 | 3 | - | 2 (kaggle_pilot.py) | **KEEP** | active; no overlap found at this read depth |
| `hf-lake-storage` | issue-label,PR | 31 | 31 (17) | 1.6 | 0 | issue | 1 (hf_storage.py) | **KEEP** | active; no overlap found at this read depth |
| `init-actions-secrets` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue | 7 (SKILL.md) | **KEEP** | active; no overlap found at this read depth |
| `journal-offvm-backup` | issue-label,cron,dispatch | 595 | 223 (214) | 1.3 | 0 | issue/ping/vm | 2 (check_cadence_liveness.py) | **KEEP** | never-touch: money DB backup |
| `kaggle-backups` | issue-label,PR,cron | 25 | 25 (0) | 0.3 | 5 | ping/vm | 6 (hf-lake-squash-2.json) | **KEEP** | never-touch: backup |
| `kaggle-cold-lake-copy` | PR | 3 | 3 (0) | 0.4 | 0 | - | 0 | **KEEP** | active; no overlap found at this read depth |
| `live-replay-parity` | issue-label,cron,dispatch | 867 | 231 (216) | 3.6 | 0 | issue/ping/vm | 6 (health-review-2026-10-04.jso) | **KEEP** | never-touch: trading parity |
| `live-review-wake` | cron,dispatch | 46 | 30 (0) | 0.5 | 1 | - | 4 (desk-scan-packet.yml) | **KEEP** | never-touch: live review |
| `m20-exit-lever-sweep` | push,dispatch | 188 | 31 (0) | 6.7 | 31 | commit/issue/vm | 20 (SKILL.md) | **KEEP** | active; no overlap found at this read depth |
| `macro-valuation-backfill` | issue-label,dispatch | 2,702 | 218 (216) | 0.6 | 0 | issue | 5 (macro-backfill-cost-paths-20) | **KEEP** | active; no overlap found at this read depth |
| `macro-valuation-snapshot` | issue-label,cron,dispatch | 2,789 | 223 (211) | 5.0 | 0 | issue | 3 (macro-producer-liveness.yml) | **KEEP** | never-touch: data pull |
| `market-data-lake` | issue-label,PR,cron,dispatch | 235 | 235 (174) | 1.3 | 6 | issue/ping/vm | 10 (market-data-lake-fallbacks.j) | **KEEP** | never-touch: data pull the trader needs |
| `ml-data-export-kaggle` | cron,dispatch | 28 | 7 (0) | 0.6 | 2 | vm | 7 (hf-lake-kaggle-pilot.yml) | **KEEP** | never-touch: data pull |
| `ml-entry-retrain` | cron,dispatch | 3 | 3 (0) | 0.0 | 3 | - | 2 (ml-entry-retrain-monitor.jso) | **KEEP** | active; no overlap found at this read depth |
| `news-gdelt-panel` | cron,dispatch | 20 | 7 (0) | 2.9 | 1 | - | 3 (news-alpha-gdelt-panel-1016.) | **KEEP** | never-touch: data pull |
| `options-snapshot-capture` | issue-label,cron,dispatch | 188 | 188 (178) | 0.5 | 0 | issue/vm | 4 (etf-history-pipeline-2.json) | **KEEP** | never-touch: data pull |
| `phone-exec-js-sign` | push,dispatch | 6 | 1 (0) | 0.0 | 0 | - | 4 (phone-exec-js-sign.json) | **KEEP** | active; no overlap found at this read depth |
| `phone-executor-apk` | push,dispatch | 332 | 19 (0) | 0.9 | 0 | - | 5 (fix-apk-build-concurrency.js) | **KEEP** | active; no overlap found at this read depth |
| `pr-opener` | push | 435 | 0 (0) | 0.0 | 0 | commit/pr | 26 (README.md) | **KEEP** | never-touch: PR landing |
| `probes` | issue-label,dispatch | 1,422 | 215 (215) | 0.0 | 0 | issue | 39 (oi-review-packet-cron-observ) | **KEEP** | active; no overlap found at this read depth |
| `prop-report` | issue-label,dispatch | 2,698 | 216 (215) | - | 0 | issue/vm | 2 (flatten_alpaca_position_acti) | **KEEP** | active; no overlap found at this read depth |
| `prop-tp-r-gate` | issue-label,dispatch | 1,559 | 216 (0) | 0.4 | 0 | - | 0 | **KEEP** | active; no overlap found at this read depth |
| `purge-artifacts` | issue-label,cron,dispatch | 2,788 | 223 (216) | 0.1 | 3 | issue | 2 (lane4-sweep-cadence-20260910) | **KEEP** | active; no overlap found at this read depth |
| `pytest-collect` | merge_q,PR,dispatch | 29,570 | 3,407 (0) | 75.5 | 1 | - | 3 (ci-main-pytest-no-cancel.jso) | **KEEP** | never-touch: required check |
| `pytest-rerun` | workflow_run | 10,737 | 3,422 (2,364) | 16.1 | 1 | - | 1 (pytest_rerun.py) | **KEEP** | never-touch: required check helper |
| `pytest-run` | merge_q,PR,cron,dispatch | 30,371 | 3,632 (0) | 559.3 | 64 | - | 18 (ci-change-classes.json) | **KEEP** | never-touch: required check |
| `r4-demotion-gate` | cron,dispatch | 86 | 14 (0) | 0.1 | 0 | commit/issue/ping/pr | 9 (README.md) | **KEEP** | never-touch: promotion ladder |
| `replay-pregate-nightly` | issue-label,cron,dispatch | 2,839 | 230 (215) | 13.2 | 0 | commit/issue/vm | 9 (mi279-u1-pregate-skip-ci.txt) | **KEEP** | never-touch: trading replay |
| `research-backtest-augment` | issue-label,cron,dispatch | 2,711 | 217 (216) | 0.1 | 0 | issue/vm | 5 (research-exit-head-replay-tr) | **KEEP** | active; no overlap found at this read depth |
| `research-candles-kaggle` | PR,dispatch | 9 | 9 (0) | 1.3 | 2 | - | 1 (candle_dataset.py) | **KEEP** | active; no overlap found at this read depth |
| `research-exit-head-build` | issue-label,dispatch | 2,705 | 216 (216) | 0.0 | 0 | commit/issue | 12 (lane-e58-research-recovery.j) | **KEEP** | active; no overlap found at this read depth |
| `research-exit-head-replay-trainer` | issue-label,dispatch | 2,684 | 216 (216) | 0.0 | 0 | issue/vm | 4 (exit-head-replay-fail-closed) | **KEEP** | active; no overlap found at this read depth |
| `research-harness-dispatch` | dispatch | 304 | 26 (0) | 12.0 | 0 | - | 20 (w5d-e7-orphan-harnesses.json) | **KEEP** | never-touch: research loop |
| `research-queue-dispatch` | cron,dispatch,workflow_run | 872 | 219 (0) | 23.1 | 60 | commit/issue/ping | 26 (SKILL.md) | **KEEP** | never-touch: research loop (OPERATING-PLAN) |
| `research-queue-grade` | cron,dispatch | 290 | 44 (0) | 11.7 | 1 | - | 7 (SKILL.md) | **KEEP** | never-touch: research loop |
| `research-queue-replenish` | cron,dispatch | 251 | 105 (0) | 11.4 | 2 | - | 9 (SKILL.md) | **KEEP** | never-touch: research loop |
| `reset-daily-risk-state` | issue-label | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **KEEP** | never-touch: trading state |
| `reset-protocol-backup` | cron,dispatch | 2 | 2 (0) | 0.0 | 0 | issue/ping | 5 (SKILL.md) | **KEEP** | never-touch: backup |
| `schedule-keeper` | push,cron,dispatch | 7,947 | 1,758 (0) | 62.4 | 218 | ping | 14 (keeper-vm-floor.json) | **KEEP** | never-touch: operator process: pages when validators stop |
| `set-diag-token` | issue-label,dispatch | 2,699 | 216 (216) | 0.0 | 0 | issue/vm | 2 (dt-fix-set-diag-token-shadow) | **KEEP** | never-touch: diag token |
| `soak-book-grade-weekly` | issue-label,cron,dispatch | 1,270 | 221 (216) | 0.1 | 1 | - | 6 (check_cadence_liveness.py) | **KEEP** | active; no overlap found at this read depth |
| `sp500-membership-refresh` | issue-label,cron,dispatch | 183 | 183 (183) | 0.0 | 0 | - | 1 (check_cadence_liveness.py) | **KEEP** | never-touch: data pull |
| `strategy-review-packets` | issue-label,cron,dispatch | 1,482 | 230 (216) | 1.6 | 1 | commit/issue/vm | 9 (oi-review-packet-cron-observ) | **KEEP** | never-touch: trade desk |
| `sync-vm-secrets` | issue-label,dispatch | 2,699 | 216 (213) | 0.1 | 0 | issue/ping/vm | 11 (SKILL.md) | **KEEP** | never-touch: credentials |
| `system-actions` | issue-label,dispatch | 2,898 | 225 (137) | 1.8 | 3 | commit/issue/ping/pr/vm | 77 (settings.json) | **KEEP** | never-touch: allowlist |
| `system-actions-cancel-guard` | workflow_run | 430 | 115 (113) | 0.0 | 0 | ping | 3 (ops-audit-oa17-sa-concurrenc) | **KEEP** | never-touch: system-actions |
| `trainer-diag-relay` | push | 34 | 6 (0) | 0.7 | 0 | commit/vm | 4 (pi-20260921-0001-trainer-vm-) | **KEEP** | never-touch: diag relay |
| `trainer-offload-train` | issue-label,dispatch | 2,699 | 216 (216) | 0.0 | 0 | commit/issue | 5 (ict-offload-drain.service) | **KEEP** | active; no overlap found at this read depth |
| `trainer-vm-diag` | issue-label,dispatch | 2,705 | 216 (141) | 0.4 | 1 | issue/vm | 11 (ml-review.md) | **KEEP** | never-touch: diag relay |
| `vm-caddy-deploy` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **KEEP** | never-touch: deploy (Caddy) |
| `vm-diag-snapshot` | issue-label,dispatch | 2,699 | 216 (187) | 0.4 | 8 | issue/vm | 21 (SKILL.md) | **KEEP** | never-touch: diag relay on the trading path |
| `vm-git-credential-bootstrap` | issue-label,dispatch | 2,698 | 216 (215) | 0.1 | 0 | issue/vm | 7 (keeper-vm-floor.json) | **KEEP** | active; no overlap found at this read depth |
| `vm-ib-gateway-deploy` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **KEEP** | never-touch: gateway |
| `vm-ib-gateway-recover` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 3 (system-actions.yml) | **KEEP** | never-touch: gateway |
| `vm-ib-gateway-selftest` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 1 (system-actions.yml) | **KEEP** | never-touch: gateway |
| `vm-ib-gateway-stop` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 1 (vm-ib-gateway-watchdog-enabl) | **KEEP** | never-touch: gateway |
| `vm-ib-gateway-watchdog-enable` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **KEEP** | never-touch: gateway |
| `vm-resize-live` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 0 | **KEEP** | never-touch: live VM |
| `vm-web-api-recover` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 11 (settings.json) | **KEEP** | never-touch: serving path |
| `vwap-backtest` | issue-label,dispatch | 2,698 | 216 (216) | 0.0 | 0 | issue/vm | 2 (candle-refresh-code.json) | **KEEP** | active; no overlap found at this read depth |
| `work-store-outbox` | issue_comment,cron,dispatch | 116 | 116 (111) | 0.0 | 0 | issue | 3 (wsd-s3-cli-outbox.json) | **KEEP** | never-touch: WORK-STORE |

## 7. P3 merge feasibility, read after the approval (2026-11-06 ~01:40Z)

The operator approved P3 ("Merge as proposed") on my claim that each group does *the same job*. Reading the members at diff level before writing any merge, **that claim holds for almost none of the groups**. Nothing was merged. The evidence, so the call can be re-made on facts:

| group | members | what the diff shows | verdict |
|---|---|---|---|
| M1 research-script-run ×5 | `research-script-run{,-data,-kaggle,-kaggle-cpu,-trainer}` (1,069 lines) | five **different executors**: GitHub runner, Kaggle CPU, Kaggle GPU, trainer-VM over ssh, data runner. They differ in env and secrets, installs, sparse-checkout, concurrency group, and `run-name`/`dispatch_queue.fired` handling; two of them diffed share well under half their lines | not the same job. A `target` input means one ~1,000-line workflow of conditional steps on the research loop's hot path |
| M2 branch pruners ×3 | `delete-merged-branches` (bash sweep of every merged-PR branch), `prune-landed-branches` (github-script over a manifest), `prune-merged-claude-branch` (one branch, `force` + audited `reason`) | three different jobs with different inputs and different safety rules; each **executed <=2 times in 90 d** | not the same job; merging ref-deleting code buys one fewer file for a regression risk |
| M7 external alerts ×2 | `external-comment-alert`, `external-issue-alert` | two **security tripwires** on different events (`issue_comment` vs `issues`) with different logic (minimize the comment vs flag the issue); neither has fired in 90 d | different controls; merging touches an intrusion alarm for no saving |
| M6 terminate/reset | `terminate-instance` vs `reset-instance` | **~30 differing lines of ~150**: genuinely near-identical | mergeable, but both act on live VMs (terminate/reset) and run ~once per 90 d; the saving is one file |
| M5 runner/console ×5, M6 rest, M4 diag/fix | not diffed to the line | each is a label-dispatched relay with its own ssh/OCI body (`diff` of install vs console-install: 143 differing lines) | same pattern: shared *shape*, different *body* |
| M8 ~13 watchdogs | needs the design pass the manager asked for first | not started | design first (filed in the pipeline) |

**Recommendation (to re-decide):** do not merge M1, M2 or M7. Where the real duplication is shared *steps* (the sparse-checkout/install block in the five research runners, the "Require VM host secrets / Dedup / post result" scaffold in the label relays), extract a composite action and keep each entry point, which keeps label and `workflow_dispatch` contracts byte-identical. M6's terminate/reset pair is the only clean merge and is not worth a live-VM-action change on its own. M3 (the mirrors) stays with WORK-STORE S7 as decided.

### Disposition of P3 (Manager 2026-11-05b, 2026-11-06 01:32Z; pipeline PI-20261106-01AFOLUJ-0004, closed)

1. **Do not merge M1, M2 or M7, and do not merge terminate/reset** (it acts on live VMs about once per 90 d, so the risk outweighs one file).
2. **Do extract the shared scaffolding as composite actions** (the sparse-checkout/install block; "Require VM host secrets / Dedup / post result"). Every entry point, label contract and output stays byte-identical. Tier 1, self-land, **after #23594 and #23600 merge**, so it never stacks on unmerged deletions.
3. **Order:** the M8 watchdog design doc (PI-20261106-01AFOLUJ-0005) first, then the composite actions.
4. `board-post.yml` is left for the operator.

### Composite actions: measured before building (2026-11-06 ~04:10Z, after #23594, #23600 and #23603 merged)

The manager ordered three composite actions (PI-20261106-01AFOLUJ-0007). Before writing any, I read the callers. **None of the three is supported by what the code shows, and the M8 design doc (#23603) overstated one of them.** Nothing was built.

| proposed action | what the callers show | verdict |
|---|---|---|
| `diag-feed-watch` for the five VM-feed watchers | **The design doc's "common diag_fetch -> render -> exit-code-through-tee -> summary -> red scaffold" is not there.** `oi-feed-freshness` and `broker-truth-freshness` are two-step jobs (grade, then a `github-script` status-issue upsert); `mirror-orphan-watch` is two bash steps with no issue; the shell differs in each (extra `curl` reads, a `pip install`, different exit handling). The one real duplication is the **status-issue upsert** block (find the open issue by label, create or update it, comment only when the fingerprint changes): it appears, with different text, in `oi-feed-freshness`, `broker-truth-freshness`, `account-broker-reconcile` and `broker-bracket-reconcile` | the design doc is wrong on this point (it said it had diffed shapes, not outputs: this is that check). A `status-issue-upsert` action would have **4 callers, 2 of them (`account-broker-reconcile`, `broker-bracket-reconcile`) on the never-touch money-path list**. Only the other two are in scope: ~25 duplicated lines each |
| shared sparse-checkout/install block in the `research-script-run` family | only **2 of the 5** files carry a sparse checkout (`-kaggle`, `-kaggle-cpu`); the other three have none | 2 callers, ~12 lines each. Not worth an action |
| "Require VM host secrets (fail closed) / Dedup / post result" scaffold in the label relays | the step is in **49 workflows**, not ~10, and the bodies are **not identical**: the first 14 lines hash to **at least 10 distinct variants** (most common: 7 files), each naming different secrets. `Dedup` is in 14 files. 49 includes never-touch files (`system-actions`, `vm-diag-snapshot`, `trainer-vm-diag`, `trainer-diag-relay`, `vm-web-api-recover`, the IB-gateway relays) | one action means a 49-file edit across the never-touch list with a secrets-as-input interface. Blast radius far above the saving |

**Recommendation (for the manager):** close PI-...-0007 as "measured, not worth building"; do not touch the 49-file scaffold. If a saving is still wanted, the only defensible one is `status-issue-upsert` for `oi-feed-freshness` and `broker-truth-freshness` (two non-money-path callers), and the two money-path callers only with the operator's explicit OK. The merged design doc `docs/plans/WATCHDOG-CONSOLIDATION-DESIGN-2026-11-06.md` §4 should then be corrected to say this; I have not edited a merged doc without a decision. **Why this matters beyond the saving:** the prune's first estimates (same job, same scaffold) were read from names and shapes; every group that was then read at diff level turned out different.
