# Compute allocation: who gets which compute, and how it is enforced (2026-11-03)

> **Resumed 2026-11-04 ~20:05Z** after the reset and the deep audit (#22902), by Manager Session 2026-11-04a. **Phase 1 is
> measured (§ 8): it met V1 and V2 on its first 20 h. Phase 2 (paid resources) is not needed now** and stays parked until the 7-day
> re-measure (M1, due 2026-11-11).

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> **Gates this adds or changes.** **None are added; this design REMOVES checking friction.** The operator re-scoped at
> ~21:20Z on 2026-11-03 (relayed by the manager; binding):
> - "Cut duplicate and unneeded CI FIRST; measure the impact; only then consider resources."
> - "Free resources are fine anytime; nothing paid until the cuts are measured."
> - "Duplicate checks go entirely. Re-testing already-approved code (push-to-main re-runs) is the first target."
> - "Low-importance PRs (logging, data records, docs) must not be held by the full suite."
>
> So two checking reductions are **operator-decided**: (D3) required checks stop re-running in full on push to `main`, and (D4)
> low-importance PRs run a fast, diff-scoped form of the required checks. One existing limit may get TIGHTER: the research cap on
> GitHub-hosted runners (D5; a cap on research, not a gate on merging or trading). No `*_ENABLED` flag, approval step or readiness
> condition is added.
>
> **Phase 1** (CI cuts and free moves) is BUILT by lane CI-STREAMLINE (session_01AFoLuHkvWi7dqNdMx6Ey51), not by this lane.
> **Phase 2** (resources) is conditional on the phase-1 measurement.
>
> Row: `COMPUTE-ALLOCATION-DESIGN`. Lane: dispatched by Manager Session 2026-11-03b. Evidence:
> `comms/ci/compute-allocation-inventory-2026-11-03.json`. Rerun: `scripts/ops/actions_capacity_inventory.py`.

## 0. The answer in five lines

1. **The merge path is mostly starving itself, not being starved by research.** It is 66% of all GitHub-hosted job-hours (ESTIMATED, 3,362 job-h over 60,244 runs, 10-27T21Z..11-03T21Z). When a
   required check was queued at saturation (275 minutes, 11-03 06-21Z, n=2,102 runs), merge-path jobs held 60% of the slots, research 20% and automation 16%.
2. **63% of merge-path hours are avoidable.** Re-running the full required suite on every push to `main` costs 719 h/wk. Running it on
   bot-data automation PRs costs 685 h/wk. Of the 1,703 PR branches in 7 days, 70% are `automation/*`, and 569 of those are research
   *bookkeeping* PRs (stamps, receipts, result batches, SLO, grades).
3. **Research compute itself is small on GitHub.** `research-script-run` is 26 h/wk. Research's real GitHub cost is its landing loop:
   `research-queue-dispatch` holds a runner for 175 h/wk, mostly waiting in `commit-to-main verify-merged` for its own PRs.
4. **The required checks depend on a full clone of a 2.2 GB repository.** Today that clone went from ~2 min to 20–35 min while GitHub
   reported degraded Git operations. Checks then hit their own timeouts inside `Checkout`. A design that needs a full clone to merge a
   one-line PR is fragile, whatever the runner pool.
5. **The trainer was the wrong host for self-hosted runners.** It has 0.0 spare OCPU (7-day p95) and 1.1 GB of its 6 GB memory spare,
   and the account is already at the Always-Free A1 ceiling. They stay off the trainer (operator, 2026-11-03).
   Any extra capacity is phase 2, and is considered only after the phase-1 cuts are measured (§ 6).

## 1. Measured inventory (7 days)

**Population.** Every workflow run created **2026-10-27T21:00Z → 2026-11-03T21:00Z**: 60,244 runs read via `actions/runs` in 336
half-hour windows, with **0 failed reads**. Job-level data: every non-skipped run created 2026-11-03 06:00–21:00Z ("dense", 2,102 runs),
plus a stratified sample before that (250 runs per required check, 12 per other workflow; 1,746 runs), giving 3,903 jobs and 0 failed
reads. Step timings come from 900 required-check runs (500 before the dense window, 400 inside it).

Definitions:
- **Job-hours** are ESTIMATED: the mean job-minutes per run from the job sample × the non-skipped run count.
- **Queue wait** = job `started_at − created_at`. It includes a workflow's wait on its own concurrency group, so it is an upper bound on
  pool starvation.

| class | runs | non-skipped | job-h / 7 d (EST.) | share | biggest consumers (job-h) |
|---|---|---|---|---|---|
| merge path (4 required checks) | 15,866 | 15,866 | 2,211 | 66% | pytest-run 1,184 · Guards 798 · pytest-collect 159 · repo-inventory 70 |
| automation / data-commit | 29,074 | 11,105 | 635 | 19% | desk-decisions-mirror 133 · work-digest 103 · live-review-rows-mirror 97 · schedule-keeper 67 · branch-sync 56 · market-data-lake 54 |
| research + backtest | 2,952 | 1,174 | 394 | 12% | research-queue-dispatch 175 · research-slo 58 · research-script-run 26 · research-queue-grade 24 · replay-pregate 18 · m20 16 · e35 13 |
| landing | 5,421 | 5,065 | 86 | 3% | armed-branch-push-watch 34 · hold-merge alarm 32 · claude-pr-automerge 16 |
| training | 1,099 | 37 | 12 | <1% | trainer-capture-watch 9 |
| ops (money path: system-actions, diag, deploy, phone-apk) | 5,824 | 191 | 7 | <1% | system-actions 3 · trainer-vm-diag 2 |
| **total** | 60,244 | 33,446 | **3,362** | | = **20.0 mean concurrent jobs**, the pool's entire capacity on average |

**Merge-path hours by origin:** human PRs 726 · **push to `main` 719** · **`automation/*` PRs 685** · dispatch 73.

**Concurrency limit = 20 (MEASURED).** An exact start/stop sweep over the dense window's hosted jobs (those with a runner) reached exactly
20 and never 21. The pool sat at 20 for ≥ 186 of 900 minutes; this is a lower bound, because jobs of runs created before 06:00 are not
in the dense set. This matches the Free-plan figure on `docs.github.com/en/actions/reference/limits` (fetched 2026-11-03: Free 20,
Pro 40, Team 60, Enterprise 500; 6 h per job). The plan tier read via API is COULD_NOT_READ (`user.plan` is null for this token). The
self-hosted runner list is COULD_NOT_READ (the session proxy blocks `actions/runners`). The self-hosted peak was 4, before the 14:38Z
revert.

**Queue wait, minutes (p50 / p95 / max):**

| | Guards | pytest-run | pytest-collect | repo-inventory | ops | landing | research |
|---|---|---|---|---|---|---|---|
| 7-d sample (before 11-03 06Z) | 1.4 / 26.5 / 74 | 0.6 / 17.0 / 73 | 0.5 / 19.6 / 64 | 0.3 / 11.3 / 65 | 3.0 / 47.4 / 68 (n=68)¹ | 1.2 / 22.0 / 45 | 0.2 / 8.7 / 54 |
| 11-03 06–21Z (all) | 1.8 / 48.2 / 106 | 2.8 / 38.6 / 61 | 1.7 / 31.7 / 50 | 1.8 / 29.7 / 100 | 0.1 / 32.1 / 48 (n=40) | 1.4 / 77.2 / 123 | 0.5 / 32.4 / 86 |

¹ The worst ops waits are trainer-vm-diag and phone-executor-apk. Both serialise on their own concurrency groups, so part of each wait
is self-imposed.

**Who held the slots while a required check waited** (dense window; the 275 minutes in which a required-check job was queued and ≥ 18
hosted jobs ran): merge path **60%**, research **20%**, automation **16%**, landing 3%, training 1%, ops 0%.

**Checkout step of the required checks (minutes, p50 / p95 / max):**

| | 7-d sample (before 11-03 06Z) | 11-03 06–21Z |
|---|---|---|
| Guards | 1.4 / 2.2 / 4.1 | 2.2 / 18.2 / 30.0 |
| pytest-run | 1.4 / 2.1 / 2.2 | 2.2 / 19.0 / 35.2 |
| pytest-collect | 1.4 / 2.1 / 3.5 | 2.1 / 7.8 / 10.1 |
| repo-inventory | 0.9 / 1.2 / 2.5 | 0.8 / 4.6 / 6.2 |

16 jobs in the dense window were cancelled inside `Checkout`. The hourly median was 2.1 min from 06 to 15Z and 7–13 min from 16 to 20Z,
while hosted concurrency was *lower* (18Z peak 13). `githubstatus.com/history.rss` shows "Incident with Git Operations — degraded
performance", opened Nov 3 20:57Z, and an API/Git incident resolved at 13:56Z. So the trigger was partly GitHub-side. The amplifier is
ours: `fetch-depth: 0` (full history) in `pytest-run.yml` and `guards.yml` on a repository whose packed size is **2.2 GB** (repos API
`size` 2,232,828 KB; 72,365 tracked files, 25,776 of them under `.github/`).

**The manager's four items, verified against the Actions API:**
1. guards job 126162423829 waited 22 min in the queue, then spent 20:08:18Z → 20:39:10Z in `Checkout` and was cancelled at
   `timeout-minutes: 30`. Checkout was its only non-success step.
2. repo-inventory job 126162423119: `Checkout` ran 20:01:05Z → 20:06:05Z, which is exactly `timeout-minutes: 5`. This was a
   **timeout, not a concurrency cancel**.
3. pytest-run job 126162377943: `Checkout` took 24 min before tests started. The image-drift PermissionError fixed in #22729 is a
   separate merge-path risk; see § 3.6.
4. A one-line PR taking more than 1 h is consistent with 15–22 min of queue plus 24–31 min of checkout.

## 2. Resource map: today versus target

| resource | limits (source) | used for today | should be used for |
|---|---|---|---|
| **GitHub-hosted runners** | 20 concurrent, 6 h/job, free for a public repo (limits page, fetched 2026-11-03; cap MEASURED above) | everything: merge path 66%, automation 19%, research 12% (mostly its landing loop), ops <1% | **the control plane**: money-path ops, the merge path, landing, light automation. Research only as spill-over under a hard cap (§ 3.4). |
| **Self-hosted `jta-infra` on the trainer** | the host's capacity: 1 OCPU / 6 GB, disk 97 GB (100% full at 14:10Z today, per the GH-CAPACITY-INFRA-RUNNER row); spare 0.0 OCPU / 1.1 GB (`comms/cloud/compute_spare.json`, 7 days to 11-03) | OFF since 14:38Z (`INFRA_RUNS_ON` = hosted). Before that, 4 instances carried infra **and** research pollers: `research-script-run-kaggle*.yml` and `research-queue-dispatch.yml` also read `vars.INFRA_RUNS_ON` | **nothing**: retire it (D2). It competed with the trainer's own work, and it put research pollers on the ops pool. |
| **Trainer VM** | 1 OCPU / 6 GB; `research_compute.yaml` trainer max_concurrent 1, heavy-lock windows | training cycle, promotion sweep, forecasts, mirror; research units that need trainer-resident data (`needs_vm_data`) | the same, unchanged. No CI. |
| **Live VM** | 2 OCPU / 12 GB; spare 0.062 OCPU (7-day p95) | trading, web API, Caddy, prop executor | trading only. Never CI, never research. |
| **Kaggle CPU kernel** | CPU not metered by `kaggle quota` (KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13 § 1); 1 slot in `research_compute.yaml` | `cpu_long` first choice; published-data units | **the default for every research unit over ~10 min** that needs no trainer data. Its GitHub poller must stop holding a runner (§ 3.5). |
| **Kaggle GPU** | 30 GPU-h/week, TPU 20 h/week (`kaggle quota`, observed 2026-10-13, same doc); 2× T4 | `gpu` / `gpu_preferred` classes | unchanged; GPU-only work |
| **RunPod (M19)** | $10/month ledger cap, $0.22/h RTX 3090 (`research_compute.yaml`) | GPU fallback, rarely used | unchanged |
| **Hugging Face** | Hub storage + read: free. ZeroGPU 5 GPU-min/day; HF Jobs paid from $0.40/h T4 (COMPUTE-ARCH-REVIEW-2026-10-13 § C, fetched then) | dataset storage (`market-data-lake.yml`, `hf_upload_large_files.py`); `hf-cron.yml` is dispatch-only | **storage and sourcing, not compute**. No change. ZeroGPU is too small for batch work; HF Jobs is a paid alternative to RunPod, not needed now. |
| **OCI A1 (new VM)** | the account uses 4 OCPU / 24 GB = exactly the Always-Free 3,000 OCPU-h + 18,000 GB-h per month (`comms/cloud/oci_limits.json`, read 2026-11-03; tenancy limit 250 cores, so pay-as-you-go is possible) | — | only if phase-2 option P2-B is chosen. Any new instance is **paid**. |

## 3. Design

### 3.1 Priority order

**P0 money-path ops** (system-actions, deploy, diag relays, phone-executor-apk) > **P1 merge path** (the 4 required checks on a PR) >
**P2 landing** (automerge, merge-slot, branch-protection) > **P3 automation data** (mirrors, digests) > **P4 research and training on
GitHub**, as spill-over only.

GitHub-hosted runners have no priority queue (GH-QUEUE-DEDUPE, 2026-11-03), so priority cannot be *declared*. It is enforced by three
mechanisms:
- (a) **cut demand** so the pool is rarely saturated (§ 3.2, § 3.3);
- (b) **hard caps and yields on the low classes** (§ 3.4);
- (c) **compute that does not need GitHub goes elsewhere** (§ 3.5).

Target utilisation is ≤ 60% of the pool (≈ 12 mean concurrent). Today's measured 20.0 mean means the pool is full on average, and no
yield rule can fix that.

### 3.2 Merge path: run the checks where they decide something

| lever | saves (EST., job-h/wk) | how | decision |
|---|---|---|---|
| **No full required suite on push to `main`** | ≈ 719 | Drop the `push` trigger from `pytest-run` and `guards` (keep pytest-collect and repo-inventory, which are cheap). The 30-min `pytest_run_backstop` already grades `main`'s HEAD with the full suite when a merge commit is not covered (GH-CAPACITY-PR-CI-FANOUT). Add a Guards twin of that backstop. Post-merge detection moves from "per merge" to "≤ 30 min + run". | operator-decided (D3) |
| **Data-only automation PRs fast-pass** | most of ≈ 685 | When every changed path is in the bot-data list already pinned by `tests/test_push_paths_ignore_bot_data.py`: a shallow checkout; pytest-run runs only the data-tree tests (the mode exists today: "data-only diff - every test file that reads the data trees"); Guards runs only the guards whose `when` matches the diff, with `secret_scan` on the diff. The checks still report, and still go red on a bad file. | operator-decided (D4) |
| **Batch research bookkeeping** | fewer PRs: 569 → ~170/wk | One landing PR per dispatcher cycle carrying stamps + receipt + results (today these are 3 separate `commit-to-main` calls), and one per 2-h SLO/grade cycle. | Tier 1 |
| **Shallow checkout everywhere** | 1–30 min per job under Git degradation | `fetch-depth: 2`, plus `git fetch --depth=1 origin <base>`, or the PR files API, for the diff. Done for pytest-collect in #22714. Guards and pytest-run still use `fetch-depth: 0`. Add `filter: blob:none` + sparse checkout where the job reads a known subtree. | Tier 1 |
| **Shrink the clone** | all jobs | 25,776 files under `.github/` (merge-slot, landing and automerge records) plus ~2 GB of tracked data. Archive closed landing records off `main` periodically; move bulk data to the HF lake. This is a separate row. | Tier 1 (filed) |

### 3.3 Landing and automation

- `research-queue-dispatch`: stop holding a runner in `commit-to-main verify-merged`. Open the PR, arm auto-merge and exit; the next
  cycle verifies. This is GH-CAPACITY-LAND-VERIFY-OFF-RUNNER, already designed. It saves ≈ 175 job-h/wk.
- The per-event listeners (`claude-run-failure-alert` 1,763 running runs/wk, `armed-branch-push-watch`, hold-merge alarm, `pytest-rerun`)
  are cheap per run (~86 job-h/wk in total). Leave them. Revisit only if § 5 shows they matter after § 3.2.

### 3.4 Research and training on GitHub: spill-over, capped

- `research_compute.yaml`: `github_runner.max_concurrent` **10 → 4** and `github_runner_data` 2 → 1 (D5; the 6 → 10 raise was today,
  RESEARCH-FLOW). With `kaggle_first` widened (below), research throughput need not fall.
- The dispatcher's yield list covers **required checks as well as infra**. `dispatch_queue.runner_pressure` adds the 4 required-check
  names to `infra_names`, with `infra_yield_at` unchanged, so research does not fire while a required check is queued.
- `kaggle_first.min_est_minutes` 30 → 10: any unit estimated over 10 min goes to `kaggle_cpu` before `github_runner`. `cpu_long` is
  already kaggle_cpu-first.
- Sweeps that bypass the dispatcher (e35, m20, regime-adx, ict-scalp, vwap, harness-dispatch) get `max-parallel ≤ 3` (e35/m20
  already have it, per GH-CAPACITY-RESEARCH-OFFLOAD; the others were not read for this doc) and a `concurrency` group per workflow.

### 3.5 Remote backends stop holding a GitHub runner

`research-script-run-kaggle.yml`, `-kaggle-cpu.yml` and `-trainer.yml` poll (`sleep 15/30/60`) for up to 360 min on a GitHub runner.
Make them submit-and-exit, and let the existing collector (`scripts/research/collect_runner_results.py`, run by the dispatcher) fetch
the finished output next cycle. This revives the dropped GH-CAPACITY-RESEARCH-OFFLOAD. Also move the two Kaggle pollers and
`research-queue-dispatch` **off `vars.INFRA_RUNS_ON`**: research must never land on the ops pool.

### 3.6 Merge-path robustness

- **Image drift** (#22729: a PermissionError on `/home/ubuntu` on one runner image): pin `runs-on: ubuntu-24.04`, not `ubuntu-latest`,
  for the 4 required checks, and stop tests depending on `$HOME` layout. A test that fails only on one image is a test bug.
- **Timeouts are not the fix.** With a shallow checkout, a required check's timeout measures its own work. Keep the timeouts as they
  are; do not raise them to absorb queue or clone time.

### 3.7 Self-hosted runners

**What the runner lane established.** These are SELF-HOSTED-RUNNER lane measurements, relayed by the manager at 21:15Z. Only one was
re-checked here:
- Queued→started was 2–3 s on a self-hosted runner. VERIFIED for run 41637864532 (job created 12:41:40Z, started 12:41:43Z, on
  trainer-jta-infra-3). The same lane reported ~55 min on hosted runners that morning.
- Per-job checkout on the trainer: a full depth-1 checkout is 6.4 GB in 164 s; the sparse infra profile is 0.56 GB in 22 s; the
  sparse dispatch profile is 0.78 GB in 57 s (#22712). NOT re-measured.

So a dedicated runner pool does fix ops latency. The trainer was just the wrong host for it. The sparse-profile result is also the
strongest evidence for B2: an 8–11× smaller checkout.

Failure modes the lane found are each a reason not to share a host with production work:
- the job hook path needed a `.sh` suffix;
- the workspace wipe needed an absolute path;
- the disk filled at 14:10Z, killing a real-money flatten;
- `infra-runner-health`'s cron never fired (now a schedule-keeper target, #22701).

Current state, as reported by the lane: all 4 trainer runner units are disabled, `INFRA_RUNS_ON` is hosted, and the trainer has
19.5 GB free.

Retire the trainer runners (D2, operator-decided). Keep the `INFRA_RUNS_ON` plumbing dormant, defaulting to hosted, so a dedicated runner host can be
attached later (phase-2 option P2-B) without workflow edits. Never run a runner on the trainer or the live VM again. #22712 (sparse checkout for jta-infra
jobs) is then moot for the runners. Its sparse-checkout idea moves into § 3.2.

## 4. Existing rows: proposed disposition (the manager disposes; this lane archives nothing)

| row | state | proposal |
|---|---|---|
| GH-CAPACITY-INFRA-FIRST | landed_unproven | **supersede** → its observation (infra queued→started < 10 min) becomes metric V3 of this row |
| GH-CAPACITY-INFRA-RUNNER | in_flight (T2) | **close by D2**: uninstall the trainer runners (build step B9); PI-20261103-RAM7EH86-0002 (stuck-queue rescue) and -0004 (re-arm gate) → `killed`, reason "runners retired by COMPUTE-ALLOCATION D2" (if D2-A; under D2-C they move to the new host). -0003 (sparse checkout) → **folded into B2** for hosted required checks. -0005 (keeper observation of infra-runner-health) → killed with the runners under D2-A |
| GH-CAPACITY-LAND-VERIFY-OFF-RUNNER | landed_unproven | **merge** → build step B6 |
| GH-CAPACITY-PR-CI-FANOUT | done | keep. The backstop is a dependency of D3. |
| GH-CAPACITY-RESEARCH-OFFLOAD | dropped | **revive as** build step B8 |
| KAGGLE-TRAIN-RUNNER-FIRST | done | **amend the principle**: "runner first" becomes "Kaggle CPU first, GitHub runner as capped spill-over"; writeback only |
| ML-RQ-RUNNER | blocked | no change: blocked on frontier levers, not capacity |
| ML-NONGBDT-RUNNERS | landed_unproven | no change: learner availability per backend; unaffected |
| ML-DATA-RUNNER-FETCH | done | no change |
| RQ-INFRA | done | no change |
| SA-INFRA | landed_unproven | keep. The trainer disk alarm feeds metric V5. |
| LTR-10-CAPACITY-RESERVE · DESK-10-CAPACITY | done · queued | out of scope: these are Claude-plan spend capacity, not compute |
| DATA-INFRA-PROGRAMME | done | out of scope; the HF lake is where § 3.2 "shrink the clone" moves bulk data |

## 5. Verification (what closes the row)

Re-measure with `scripts/ops/actions_capacity_inventory.py --days 7 --dense-hours 15` 7 days after B2–B8 have merged. Compare against
`comms/ci/compute-allocation-inventory-2026-11-03.json`.

- **V1** Total hosted job-hours ≤ 2,000 per 7 d (from 3,362), mean concurrent ≤ 12.
- **V2** Required checks: queue p95 ≤ 5 min and checkout p95 ≤ 3 min, both over the dense window. A human 1-file PR goes from open to
  4 required checks green in ≤ 25 min (p95, n ≥ 20 human PRs).
- **V3** Ops (system-actions, deploy, diag relays) queue p95 ≤ 5 min, excluding a workflow's own concurrency-group wait.
- **V4** Burst test: during a research burst (≥ 10 units dispatched in one cycle), a 1-file human PR still meets V2. Any
  `research-script-run*` job that starts while a required check is queued is a failure of the yield rule.
- **V5** Research units over 10 min land from `kaggle_cpu`, `kaggle` or `trainer`, not `github_runner` (count by backend in
  `research/results/**`). No GitHub job polls a remote backend for longer than 5 min. Trainer disk stays under 90% with no runner on it.
- **V6** 0 required-check jobs cancelled inside `Checkout`.

## 6. Decisions

**Decided by the operator (2026-11-03 ~21:20Z re-scope):**
- D3: push-to-`main` full re-runs go. The 30-min backstop grades `main`.
- D4: low-importance PRs (logging, data records, docs) are not held by the full suite. The exact diff-scoped form, including whether
  `secret_scan` runs on the diff only for them, is CI-STREAMLINE's build detail.
- D2: self-hosted runners stay OFF the trainer.
- Nothing paid until phase 1 is measured.

**D5 (research cap on hosted runners) is withdrawn as a question (2026-11-04).** After phase 1, the data settles it:
- research held 15% of slots in the minutes when a required check waited (was 20%);
- research's own queue p95 is 0.8 min;
- required-check queue p95 is 3.3 min.
So the cap stays at 10 (RESEARCH-FLOW). The lever is re-opened only if M1 shows required-check queue p95 above 5 min with research
holding 25% or more of the slots. That is data, so it needs no pop-up.

**Phase 2: parked.** Phase 1 met V1–V2 on its first 20 h (§ 8). Phase 2 is revisited only if M1 (7 d) fails V1–V2:
- (P2-A) **GitHub Pro**: hosted cap 20 → 40, with nothing to operate. Price: the pricing page fetched 2026-11-03 lists Team at
  $4/user/month and does not show Pro; confirm in Settings → Billing.
- (P2-B) a paid OCI A1 VM (2 OCPU / 12 GB / 100 GB) as a dedicated ops runner host. Self-hosted queue→start was measured at 3 s; the
  cost is ESTIMATED at roughly $25–30/month from list prices not re-verified today.
- (P2-C) none.

## 7. Build plan (row `COMPUTE-ALLOCATION-DESIGN`)

**CI-STREAMLINE's fixed plan** (lane session_01AFoLuHkvWi7dqNdMx6Ey51, row CI-STREAMLINE, relayed 21:33Z). That lane owns this build; the B2/B3/B4 rows below are the same work and are not built here.
- PR1 removes the push trigger from all 4 required checks. 2-h scheduled backstops on `main` replace it: pytest-run runs the full suite when HEAD is ungraded, and Guards runs `--all`.
- PR2 switches pytest-run and Guards to a blobless checkout (`filter: blob:none`).
- PR3 adds `config/ci_change_classes.yaml`: data/record-only PRs skip the pytest install and run, while runtime and order-path changes keep the full suite.
- Its baseline (ESTIMATED, wall-min including queue, push-to-main over 31.6 h) is about 7,085: guards 3,355, pytest-run 2,448, collect 882, inventory 400.
- It re-measures at about 6 h and about 24 h after the last change lands. Those deltas are THE phase-1 measurement; this doc consumes them and does not re-derive them.

**Phase 1: cut duplicate and unneeded CI, plus free moves.** Built by CI-STREAMLINE. Savings are ESTIMATED from the § 1 baseline;
CI-STREAMLINE's measured before/after is written back here when it lands.

| step | what | saves (EST.) | owner |
|---|---|---|---|
| B1 | this doc + inventory tool + baseline record | — | this lane (this PR) |
| B3 | drop the push-to-main re-runs of pytest-run and Guards (D3); add a Guards backstop beside `pytest_run_backstop` | ≈ 719 job-h/wk | CI-STREAMLINE |
| B4 | low-importance-PR fast path (data records, logging, docs) in the 4 required checks (D4) | most of ≈ 685 job-h/wk | CI-STREAMLINE |
| B2 | ~~shallow/blobless checkout~~ **DROPPED**: blobless checkout (#22738) measured no faster and timed guards out; shallow conflicts with git-log readers (CI-STREAMLINE). Checkout p95 is back to 1–4 min with the 11-03 Git incident over (§ 8) | — | closed |
| B5 | batch research bookkeeping into one landing per dispatcher cycle and one per SLO/grade cycle | 569 → ~170 PRs/wk | CI-STREAMLINE or a research lane (manager's call) |
| B6 | the dispatcher stops holding a runner in verify-merged (GH-CAPACITY-LAND-VERIFY-OFF-RUNNER) | ≈ 175 job-h/wk | free move; manager assigns |
| B8 | Kaggle/trainer pollers submit-and-exit + collector pickup; research workflows off `INFRA_RUNS_ON` | holds no slot while Kaggle or the trainer computes | free move; manager assigns |
| B12 | stop re-dispatching a unit after a `producer_failed` landing until its command or script changes (PI-20261103-BCZDXJNR-0002, #22734). MEASURED on `research/results/**` on `main` (read 21:35Z): 137 `producer_failed` records in the 7-d window across 61 units; 43 units failed ≥ 2 times (76 repeat records). 136 matched Actions runs: research-script-run* ~98, research-script-run-kaggle-cpu ~38. Mean 6.6 job-min per run (n=35 sampled) | ≈ 15 job-h/wk on GitHub (≈ 8 h of repeats), about 0.5% of the pool. It also frees the single Kaggle CPU slot, which 38 of the failures held | free move; research dispatcher, not CI |
| B13 | one owner for "which workflows are ops" (§ 9, audit #14): `research_compute.yaml` `limits.infra_workflows`; move the 3 research workflows off `INFRA_RUNS_ON`; non-blocking single-owner report | stops research reaching the ops pool | free move; Tier 1 |
| B7 | D5 withdrawn (§ 6); only if M1 re-opens it: research caps, yield on queued required checks, `kaggle_first` > 10 min | caps research's peak share (20% at saturation) | free move, after D5 |
| B9 | uninstall the trainer runner units and confirm `INFRA_RUNS_ON` stays unset (D2) | — | Tier 2, manager assigns |
| M1 | **measure**: re-run `actions_capacity_inventory.py --days 7` 7 days after B3+B4 land; write the before/after into § 1 and the row | — | this row |

**Phase 2: resources, only if M1 shows V1–V2 still failing.**

| step | what | tier |
|---|---|---|
| B10 | P2-A or P2-B (§ 6) via a manager pop-up carrying the M1 numbers | operator / 2 |
| B11 | verification V1–V6 with the inventory tool; write back to the row | 1 |

## 8. Phase-1 result: measured 2026-11-04 (first 20.3 h after the cuts)

**Population.** Every run created 2026-11-03T23:42Z → 2026-11-04T20:00Z (20.3 h, from the merge of #22737): 5,049 runs, 0 failed reads.
Job-level data: every non-skipped run created 05:00–20:00Z (1,284 runs) plus a sample before that (347 runs), giving 1,734 jobs.
- Tool: `scripts/ops/actions_capacity_inventory.py`.
- Record: `comms/ci/compute-allocation-inventory-2026-11-04-after-cuts.json`.
- Job-hours are ESTIMATED, as in § 1. The "before" column is the 7-day baseline scaled to 20.3 h, or for queue and checkout times its
  11-03 06–21Z window.
- Caveats: one weekday, the overnight hours are included, and GitHub's 11-03 Git incident had ended. Read the checkout gain as partly
  GitHub's.

| measure | before | after | target |
|---|---|---|---|
| mean hosted concurrency | 20.0 | **8.0** | V1 ≤ 12 ✅ |
| merge-path job-h per 20.3 h | ≈ 267 | **73** (−73%) | — |
| automation / research / landing job-h per 20.3 h | ≈ 77 / 48 / 10 | 48 / 36 / 4 | — |
| required-check queue p95 (Guards / pytest-run / pytest-collect) | 48.2 / 38.6 / 31.7 min | **3.3 / 3.3 / 3.4 min** | V2 ≤ 5 ✅ |
| required-check checkout p95 (Guards / pytest-run / pytest-collect) | 18.2 / 19.0 / 7.8 min | 3.7 / 4.1 / 1.2 min | V2 ≤ 3 ⚠️ close |
| pytest-run exec p50 | 19.9 min | 9.9 min | — |
| ops queue p95 (n=30) | 32.1 min | 6.2 min (max 8.0) | V3 ≤ 5 ⚠️, includes own concurrency groups |
| landing queue p95 | 77.2 min | 4.3 min | — |
| minutes a required check waited with ≥ 18 hosted jobs | 275 of 900 | 48 of 900 | V6/V4 → M1 |
| peak hosted concurrency | 20 (the cap) | 20 (the cap) | bursts remain |

CI-STREAMLINE's own 6-h readout agrees in direction:
- PR pytest-run p50 21.9 → 13.4 min;
- PR guards p90 25.3 → 11.8 min;
- PR open → merge p50 28.6 → 13.0 min (n=41, merged only).

Its 24-h readout had not been posted to row CI-STREAMLINE when this was read (20:05Z). Blobless checkout (#22738) was disproved and
closed there, so B2 is DROPPED as a lever.

**Reading.**
- The pool is no longer full on average; 8 of 20 slots are used.
- The merge path is no longer queued in normal hours.
- What remains is bursts: the pool still reaches 20, and in 48 minutes a required check waited. The next demand lever is B5 (row
  CI-BATCH-BOOKKEEPING, about 360 research bookkeeping PRs/wk → about 120).
- Buying capacity is not justified by this data.

## 9. Audit decisions folded in (DEEP-AUDIT-20261104, #22902)

**#13: one follow-through register (operator chose "One register").** Every follow-up of this design lives as a checklist row with
`due_by`; none is filed to the pipeline. Proposed for the manager to dispose:
- PI-20261103-RAM7EH86-0002 (stuck-queue rescue), -0004 (re-arm gate) and -0005 (keeper observation of infra-runner-health) →
  `killed`, reason "trainer runners retired by D2; follow-through on row COMPUTE-ALLOCATION-DESIGN (B9)".
- PI-20261103-RAM7EH86-0003 (sparse checkout) → `killed`, reason "B2 disproved: blobless checkout #22738 closed by CI-STREAMLINE".
- The build steps B5 (CI-BATCH-BOOKKEEPING), B6, B8, B9 and B13 each need a row with `due_by`, or a line on this row. None may be a
  pipeline item.

**#14: one owner per fact (tick sizes had 4+ owners).** The same defect exists in compute routing. **"Which workflows are money-path
ops" has three owners that disagree** (MEASURED on `main`, 2026-11-04):
- (a) `research_compute.yaml` `limits.infra_workflows`: 28 names;
- (b) the 11 workflows that read `vars.INFRA_RUNS_ON`;
- (c) the class regex in `actions_capacity_inventory.py`.

3 of (b) are research workflows (`research-queue-dispatch`, `research-script-run-kaggle`, `research-script-run-kaggle-cpu`); that is
how research reached the ops pool on 11-03. 25 of (a) do not read (b). **B13**: (a) becomes the one owner; (b) must be a subset of (a)
plus the runner-admin workflows; the tool already reads (a). The check is a NON-BLOCKING report modelled on
`check_cost_model_single_owner.py`; a blocking guard needs the operator's OK (No new gates). The bot-data paths list is the second
multi-owner fact: it lives in `.github/ci-change-classes.json` plus the `paths-ignore` blocks of `work-digest.yml` and
`branch-sync.yml`. Fold it into the change-class map (CI-STREAMLINE's owner).

**Usage.** The Claude weekly plan is the scarcest compute this system runs on (`docs/claude/work/USAGE-READINGS.jsonl`, the 3 readings 2026-11-03T06:28Z..11-04T18:00Z: 89% and 91% on
11-03 before the 2026-11-04 18:00Z reset; 0% at the reset). How much of last week's plan went to sessions waiting on CI is UNMEASURED.
The 11-03 merge path (1-line PRs over 1 h) is the mechanism that converts CI queue into plan spend. M1 should read the week's
`USAGE-READINGS` beside the CI numbers.

