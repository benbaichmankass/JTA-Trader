# Per-model lifecycle schedule (trainer module)

> **Doc status:** `live` · category `instruction` · last verified `2026-11-07`
> Gates this adds or changes: **none** — gates nothing on the trade path; the schedule PROPOSES, never promotes (promotion past shadow stays operator Tier-3).

Operator, 2026-11-07: every model needs its own plan for when it is retrained, retested and updated, running in the trainer module so it keeps going if Claude usage runs out.

- **Plans:** `ml/lifecycle/plans/<manifest-stem>.yaml`, one per top-level `ml/configs/*.yaml` manifest (the nightly-cycle roster; registry stage lives on the trainer VM and can exceed the manifest's declared stage, so the manifest roster is the superset). Schema + validation: `ml/lifecycle/plan.py`. Seeded by `scripts/ops/seed_lifecycle_plans.py`; hand-edit afterwards. Each cadence carries `MEASURED`/`ESTIMATED`.
- **Scheduler:** `python -m ml.lifecycle.scheduler [--dry-run]` (wrapper `scripts/ops/run_lifecycle_schedule.sh`, behind the shared heavy lock). Jobs: `retrain`, retests (`drift_check` score drift, `labelled_decay`, `serve_parity`, `champion_challenger` where a sibling exists), `update` (`gate-check`, report-only). Retrain also counts nightly-cycle `manifest_ok` rows, so it is a backstop, not a duplicate; a significant `drift_check` verdict is an early retrain trigger.
- **No halting:** each job runs in its own subprocess with a timeout; failures retry with backoff; 3 consecutive failures write ONE `lifecycle_red_flag` event to `runtime_logs/training_cycle.jsonl` per episode while retries continue. Skips (no registry entry / empty dataset) are recorded once per reason.
- **Results:** one `MEASURED` record per job in `runtime_logs/trainer/lifecycle_results.jsonl`; state in `lifecycle_state.json`; read with `python scripts/ops/lifecycle_report.py` (prints `read_state`).
- **Guard:** `lifecycle-plan-guard` (`scripts/ci/check_lifecycle_plans.py`): every manifest has a plan, no orphan plans, every command statically resolves.
- **Not covered (stated):** champion/challenger here is a registry metric `compare`; a one-replay full-cost-stack challenger run is a research unit. The cost-net gate is enforced at registration on every retrain (`config/ml_training.yaml`).
- **Tier-2, waiting on operator OK:** install `deploy/trainer/ict-trainer-lifecycle.{service,timer}`; add `lifecycle_results.jsonl` to `publish_trainer_mirror.sh` and a read route so the console shows it.
