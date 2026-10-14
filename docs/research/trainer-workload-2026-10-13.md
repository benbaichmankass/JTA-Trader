# Trainer VM workload, idle windows and capacity options — 2026-10-13

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-13` · lane `ML-DATA-OFF-TRAINER` · checklist row `ML-DATA-OFF-TRAINER` · machine-readable form: `comms/cloud/trainer_workload_profile.json` (read by `scripts/research/trainer_queue.py`) · for the weekly planning (operator, 2026-10-14). Nothing here resizes or reschedules anything.

**Population.** One 1-OCPU / 6 GB trainer, **7 days to 2026-10-13 16:00Z**, the 10 `ict-*.service` units that ran in it, from the systemd journal (`Starting`→`Deactivated` wall time, `Consumed … CPU time`), pulled through `trainer-vm-diag` issue #17887. **Not measured:** processes outside systemd, and research runs launched over SSH (`research-script-run-trainer`): they are not separate systemd units, so they are in neither column below. 10-13 is a partial day.

## 1. What consumes the trainer

| service | cadence | runs | CPU-h | share of service CPU | wall-h | CPU-h as % of the week's 168 OCPU-h |
|---|---|---|---|---|---|---|
| `ict-drift-retrain` | hourly | 167 | **30.45** | **63.7%** | 55.87 | 18.1% |
| `ict-trainer` (daily cycle) | 00:05Z | 7 | 8.82 | 18.5% | 12.71 | 5.2% |
| `ict-trainer-catchup` | 05:00Z | 7 | 6.29 | 13.2% | 11.11 | 3.7% |
| `ict-trainer-forecast` | 15 min | 672 | 1.44 | 3.0% | 3.82 | 0.9% |
| `ict-trainer-publish` | 2 min | 4,704 | 0.72 | 1.5% | 8.74 | 0.4% |
| `ict-promotion-readiness` | ~04:10Z | 7 | 0.06 | 0.1% | 0.87 | 0.0% |
| 4 others (git-sync, offload-drain, candle-refresh, pm-snapshot) | — | 1,187 | ~0.01 | 0.0% | 0.29 | 0.0% |
| **all measured services** | | | **47.79** | 100% | | **28.4%** |

* **Scheduled training (cycle + catch-up + drift) is 95.3% of the measured CPU.** The earlier review (`COMPUTE-ARCH-REVIEW-2026-10-13.md`) put the heavy occupancy at ≈2.5–3 h/day and the promotion sweep at ~99 min; the journal shows the promotion sweep at **0.05–0.33 h/day** and the summed heavy wall time at **≈11–14 h/day** (overlapping jobs counted separately) because of the *hourly* drift retrain, which that review did not list as a heavy job. That estimate is superseded.
* **`ict-drift-retrain` is the largest consumer and is growing:** wall-h/day 6.49 (10-08), 7.23, 7.32, 7.87, 8.93 (10-12), 10.02 by 16:00Z on 10-13. Average 20 min/run over the week; ~37 min/run on 10-13 (inference: runs accrued ÷ 10.0 h). If the trend held it would stop fitting between hourly slots in roughly 3–4 weeks (extrapolation from five points; unverified).
* The telemetry ledger's `cpu_p95 = 100%` on all nine measured days is consistent with this: the box is saturated in bursts, not on average (28.4% mean service CPU).

## 2. Real idle windows (busy fraction of each UTC hour, heavy services only)

Heavy = drift-retrain + daily cycle + catch-up + promotion sweep. Busy fraction = their wall-hours in that UTC hour ÷ 7 days (>1.0 means they overlap, which on one OCPU means each runs slower).

| UTC hour | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08–14 | 15 | 16–23 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| busy fraction | 0.81 | **1.74** | 0.80 | 0.37 | 0.36 | **1.96** | **1.29** | 0.36 | 0.23–0.26 | 0.30 | 0.20–0.23 |

* **Closed (busy > 0.45): 00–03Z and 05–07Z, i.e. 5 h/day** (01Z, 05Z and 06Z are over-subscribed: 1.74×, 1.96×, 1.29×).
* **Open: 03–05Z and 07–24Z = 19 h/day.** Configured in `research_compute.yaml::backends.trainer.queue.windows_utc` as `03:00-05:00, 07:00-24:00`; `tests/test_ml_data_published.py` fails if the config opens an hour this profile marks busy.
* **Corroboration, not proof:** the three 45-minute `research-script-run-trainer` failures of 10-13 started at 00:48Z, 02:16Z and 05:55Z, all inside closed hours (busy 0.81, 0.80, 1.96). The cause inside the command was never read.
* Even in an open hour a 1-OCPU box keeps ~0.2–0.3 busy from the hourly drift retrain and the light timers, so the queue keeps `max_concurrent: 1` and requires a unit to fit (`est_minutes × 1.5` before the window closes).

## 3. Is the trainer structurally over-committed?

* **In aggregate, no:** 28.4% of the week's OCPU-hours are used by measured services; the open windows hold ~19 h/day with ≥70% of an OCPU free. At 15 min/unit that is room for roughly 4 serial units per open hour, bounded by memory (a 3 GB unit next to a drift retrain on 6 GB; unmeasured).
* **In its busy hours, yes:** 5 h/day (00–03Z, 05–07Z) are over-subscribed by up to 1.96×, every day, from scheduled work alone, with no research on top. Anything added to those hours queues behind, or fails behind, the cycle.
* **Memory:** telemetry ledger `mem_p95` ≥ 84% on 5 of 9 days (84.1, 89.5, 88.5, 91.2, 91.8). Daily granularity only; the open-window headroom is therefore not measured.

## 4. Options for the weekly planning (numbers, not decisions; nothing was resized)

| # | option | frees (measured basis) | cost / risk | tier |
|---|---|---|---|---|
| A | **Done in this lane:** ML bake-off research units leave the trainer (published market dataset → GitHub runner / Kaggle). Trainer research queue falls to 2 units (`RQ-20261009-903`, `RQ-20261012-904`) | all ML-unit research load, ≈15 min × queued ML units; 3 of the 4 failed trainer-route runs started in closed hours | the export itself costs one 06:40Z SSH pull (nice 19, 20 MB/s) | 1 |
| B | Reschedule catch-up `05:00Z` → an open hour (e.g. 08:00Z) | removes the 05–07Z overlap: 11.1 wall-h/wk, 6.29 CPU-h/wk out of the worst hours | timer edit on the trainer; catch-up output reaches the registry ~3 h later | 2 |
| C | Drift retrain: every 3 h instead of hourly | ≈ 30.45 × (1 − 1/3) = **~20 CPU-h/wk, ~37 wall-h/wk** if per-run cost is constant (assumption) | slower drift reaction; the 2026-10-13 growth suggests the per-run cost is not constant | 3 (model lifecycle) |
| D | Move drift retrain off the VM (Kaggle CPU kernel or runner, fed by the published dataset) | up to **30.45 CPU-h/wk (63.7%)**, 55.9 wall-h/wk | registry/shadow artefacts must round-trip to the trainer; the retrain input is the dataset that is now published, but it is **truncated for BTC/SOL** (see `ML-SHARD-TRUNCATED`) | 2–3 |
| E | Move the daily cycle + catch-up off the VM (runner: 4 vCPU/16 GB vs 1 OCPU/6 GB; 6 h/job) | 15.1 CPU-h/wk, 23.8 wall-h/wk | registry write-back, `MemoryMax`/promotion invariants; biggest change | 2–3 |
| F | Resize the trainer | — | **Do not.** The Ampere pool is fully assigned (live 2/12 + trainer 1/6 + gateway 1/6 = 4 OCPU / 24 GB, `comms/cloud/oci_limits.json`, measured 13:48Z); the same file reports a tenancy limit of 250 cores / 1,666 GB, so more would be *billed*, not free, and no price was looked up here | 2 |

**Recommendation for the planning (a view, not a decision):** B is free and removes the measured worst hours; fix the BTC/SOL shard truncation (`ML-SHARD-TRUNCATED`) before D or E (they would train on the same stale rows); C/D are model-lifecycle decisions for the operator.

## 5. How the trainer is now managed as its own queue

* `research_compute.yaml::backends.trainer.queue` holds the windows and the fit rule; `compute_router.window_problem` applies them to every unit bound to the trainer (including units that still name `research-script-run-trainer.yml` explicitly). A unit outside a window is `deferred` with the reason and the next opening, and retried next cycle; it never halts and it never blocks units bound elsewhere.
* It is the same dispatcher, not a second cron: stamping, landing and the liveness receipt are single-writer. A second dispatcher could fire a unit twice.
* `python3 scripts/research/research_utilization.py --week` prints this breakdown and the queue depth (`trainer_queue`) beside the per-backend slot utilization, and `python3 scripts/research/trainer_queue.py --status` prints depth, idle minutes/day and days-to-drain.
