# GitHub Actions capacity — measurement, 2026-10-30 (lane GH-CAPACITY-INFRA-RUNNER)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Gates this adds or changes: **none** (one guard step is skipped on a PR diff it cannot be affected by; push / dispatch / merge_group still run it).

**Population.** Every workflow run created 2026-10-29T17:00Z → 2026-10-30T17:00Z via `actions/runs` (6,210 unique runs, all completed at read time; run-level wall = `updated_at − run_started_at`, which **includes queue wait**, so it overstates runner time). Queue wait below is job-level (`started_at − created_at`) over a **sample of ≤30 non-cancelled runs per workflow** (n shown), not a census.

## Queue wait (job level, minutes)
| workflow | n | median | p90 | max | exec median |
|---|---|---|---|---|---|
| Guards | 30 | 1.4 | 9.2 | 17.6 | 15.1 |
| pytest-run | 30 | 0.1 | 3.2 | 14.5 | 11.6 |
| pytest-collect | 30 | 0.5 | 5.5 | 12.7 | 1.4 |
| repo-inventory | 30 | 0.5 | 4.8 | 8.3 | 0.9 |
| research-script-run | 30 | 0.1 | 2.2 | 4.9 | 1.8 |
| system-actions | 24 | 0.0 | 1.2 | 4.2 | — |
| vm-diag-snapshot | 12 | 0.0 | 0.1 | 4.2 | — |
| research-queue-dispatch | 66 | 0.1 | 2.4 | 8.8 | 4.2 |

In this window the infra workflows were **not** starved (max 4.2 min). The 20+ min waits in the brief are bursts, not this day's median.

## Who consumes the wall-clock (run level, hours, ≤3 h runs)
Guards 163.7 · pytest-run 124.2 · pytest-collect 35.7 · desk-decisions-mirror 35.5 · work-digest 33.7 · repo-inventory 26.8 · claude-run-failure-alert 25.2 · research-queue-dispatch 18.0. Total 617 h/24 h ≈ 25.7 mean concurrent runs, peak 154 (queue-inflated).

## PR runs
1,128 pull_request-event runs on 247 branches; **764 (68%) from `automation/*` branches** (data-commit 304, work-digest 88, queue-stamp 88, queue-receipt 84, results-batch 84, research-slo 56 …). Superseded-head runs: 140, of which 49 cancelled and 91 ran to completion (pytest-collect 28, repo-inventory 27, Guards 20, pytest-run 16).
Item (a) is **already in place**: guards, pytest-run, pytest-collect, repo-inventory all carry `cancel-in-progress` keyed on the PR number (never on main); the 91 are runs already executing past the cancel race or pre-fix. No change made.

## Finding: Guards costs ~13 min on a data-only automation PR
Step timing of `Guards` run 41016776583 (`automation/work-digest-…`): Checkout 81 s, **Run guards 802 s**. Replaying merged data-only PR #21659's diff locally, the slowest step was `scripts/secret_scan.py` (461 s here, a whole-tree scan), then `candle-fixture-variance-guard` (310 s here): a `when: None` whole-tree scan of every tracked csv/jsonl/parquet (≈2 GB tracked). It grades only those suffixes.

Full local timing (one machine, shallow clone, so CI will differ): secret_scan 461 s · candle scan 310 s · daily-brief --check 49 s · guard-selftest-coverage 46 s · queue_replenish self-test 32 s · everything else < 25 s. (Two guards exited 2 only because my replay base ref was synthetic; their self-test timings are valid.)

## Change (this PR)
`run_guards.py` step key `pr_skip_unless`: the candle scan step is skipped **only** on a `pull_request` event whose diff matches none of `**/*.csv|jsonl|parquet` or the guard's own scripts. Self-test step unchanged; push, dispatch, `--all` and `merge_group` still run the full scan (pinned by `tests/test_run_guards_step_scoping.py`). Nothing is disabled; a PR touching a data file still runs it.

## Not done / needs the operator or a decision
- **`secret_scan.py` (largest single step, 461 s locally)** is NOT scoped by this PR: it is a security check, so narrowing it to the PR diff is a decision for the operator/manager, not a capacity tweak I took. Candidate follow-up: scan the diff on PRs and the whole tree on push/schedule.
- **Runner hold during `commit-to-main verify-merged`** (up to 80 min per automation job, ~40 callers) is the largest remaining occupancy and is test-pinned (`tests/test_commit_to_main_callers.py`); moving the wait off-runner is a design change, filed rather than done.
- Concurrency ceiling is a plan setting: hosted-runner concurrent-job limit (GitHub Settings → Actions → Runners; larger/paid runners or a higher plan raise it). Only the operator can change it. GitHub has no job priority, so "reserve capacity for infra" is not expressible with free runners; the mechanism available is fewer/shorter jobs.
- ~2 GB of tracked csv/jsonl (e.g. `comms/research/*/data/*.csv`) also costs an 81 s checkout per job.
- Stale `queued` runs from May–Sep 2026 still show in the queued list (cancel-queued-runs clears them).

## Observation (closes the row)
Re-measure ~24 h after merge: Guards "Run guards" step on automation PRs (was 802 s) and job queue waits. Method: same queries as above.
