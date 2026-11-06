# Watchdog consolidation: design (M8 of the workflow prune)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · a **proposal**; nothing here is built. Lane WORKFLOW-PRUNE (Manager Session 2026-11-05b), pipeline `PI-20261106-01AFOLUJ-0005`. Measurements: [`docs/audits/2026-11-06-workflow-prune.md`](../audits/2026-11-06-workflow-prune.md).

**Gates this adds or changes: none.** The recommendation is to *not* build the single list-driven watcher the prune proposed, and to extract shared scaffolding instead (the manager's 2026-11-06 direction for P3).

## 1. The question

The prune proposed folding ~13 freshness/liveness watchdogs into one list-driven `freshness-watch`. The manager asked for the design before any merge. This doc reads the 13 and answers: *do they share a shape, and what would consolidation save?*

## 2. What the 13 are (MEASURED 2026-11-06; the 7-day figures are upper bounds, see audit finding 5)

| class | workflows | reads | on a finding | run cost |
|---|---|---|---|---|
| **A. read a VM feed over the diag relay, render, exit red** | `oi-feed-freshness`, `broker-truth-freshness`, `mirror-orphan-watch`, `alpaca-settlement-soak-watch`, `macro-producer-liveness` | `scripts/ops/diag_fetch.sh '<route>'` -> a stdlib script | step goes red; `claude-run-failure-alert` pages | 0.16-0.44 job-h/wk each |
| **B1. read the VM or repo another way** | `dashboard-edge-watch` (ssh), `main-tree-watch`, `grading-freshness-alert` | ssh / repo / grader receipts | red, or `send-ping` | 0.11-0.46 job-h/wk each |
| **B2. read, act, and land a receipt through `commit-to-main`** | `research-slo`, `research-loss-detector`, `trainer-capture-watch`, `stale-automation-sweep`, `research-watchdog` | Actions API / trainer ssh / queue | direct Telegram / `post_alert.sh` / dispatches workflows; **three of them wait for a landing PR** | **37.4, 7.4, 9.4, 1.1, 1.4 job-h/wk** |

**Total ~58.9 job-h/wk for all 13, and 54 of it is three B2 workflows** (`research-slo` 37.4, `trainer-capture-watch` 9.4, `research-loss-detector` 7.4). The ten others cost ~5 job-h/wk between them. `research-slo` spends 1,556 s of each ~1,659 s run in "Land the status file", the `commit-to-main` verify-merged wait.

## 3. Why one list-driven watcher is the wrong build

1. **It saves almost nothing.** Consolidating class A + B1 touches ~5 job-h/wk. The 54 job-h/wk is the landing wait, which this does not change.
2. **It removes failure isolation, which the rules require.** Prime Directive rule 7 ("failures are contained per item"). Today a dead `oi-feed-freshness` is one red workflow; `cron-failure-watch` and `CADENCE_REGISTRY` are keyed per workflow. A merged workflow reds as a whole, and the guards can no longer say *which* watcher died.
3. **Cadences differ** (`*/2 h`, `*/6 h`, daily, weekday, hourly): one cron would have to dispatch per-watcher, which rebuilds the separate workflows inside one file.
4. **Alert paths differ** (red step, direct Telegram, `send-ping`, `post_alert.sh`), each tied to a different token/secret set. A merged job needs all of them.

## 4. What is genuinely duplicated, and what to build instead

Class A's five workflows repeat the same ~15-line scaffold: *fetch the route with `diag_fetch.sh`, tolerate a failed fetch as `{}` read-state, run the render script, keep the exit code through `tee`, write the step summary, fail red on non-zero.* (`mirror-orphan-watch` even carries a comment about the `tee` exit-code trap it hit.) That is one composite action: **`.github/actions/diag-feed-watch`**, inputs `route`, `script`, `args`, `summary`; the workflow keeps its own name, cron, concurrency group and failure-alert entry. Same file count, ~60-75 fewer duplicated lines, one place for the `tee`-exit-code and "could not look is not clean" rules. This matches the manager's disposition for P3 (extract scaffolding, keep every entry point byte-identical).

## 5. The part that does pay: the B2 landing wait

The 54 job-h/wk is not a watchdog-design problem; it is `commit-to-main` holding a hosted runner while a receipt PR lands. WORK-STORE-DESIGN S6C moves SLO readings, stamps and receipts to ledgers (`slo_readings`, `research_runs`), which deletes the wait. Until then, the only safe lever inside these workflows is not to wait, which weakens "landed means landed" and is **not** proposed here.

## 6. Recommendation and what stays open

- **Do not build `freshness-watch`.**
- **Build `diag-feed-watch` (composite action)** for the five class-A workflows, in the same PR family as the other composite actions, **after #23594 and #23600 merge**. Acceptance: for each of the five, a run's outputs (step summary text, exit code, alert behaviour) are identical before and after on a recorded input; `check_cron_failure_watch`, `check_cadence_liveness` and `check_workflow_catalog` unchanged.
- **B2 cost waits for WORK-STORE S6C.** Re-measure the three after S6C lands.
- Not verified here: whether the five class-A scripts' exit-code contracts are identical (they read as the same, but I diffed shapes, not outputs); the acceptance test above is how to find out.
