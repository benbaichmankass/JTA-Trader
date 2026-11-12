---
name: model-training
description: Trigger, monitor, and analyze ML model training for the ICT bot. The actual training RUNS on the trainer VM (ict-trainer.service → scripts/ops/run_training_cycle.sh); Claude drives it autonomously through the trainer-vm-diag relay — kick a cycle, watch the journal, read the registry, analyze the result. Covers the `python -m ml ...` CLI (train, list-models, promote-stage, shadow-*, build-dataset), the manifests in ml/configs/, dataset families, and the registry stage labels (candidate→shadow→advisory, housekeeping). Use when the operator says "train the models", "run a training cycle", "check the trainer", "what's in the registry", or "promote model X". A model reaches real money on its backtest evidence, with no stage step in between (operator 2026-11-12).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-09-07` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

> **The research loop (binding, 2026-11-01):** [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md) § 2 "What does not pass goes back into research — THE research workflow" -- a model is BUILT parameterised: its levers (features, labels, recipe, universe, horizon, threshold, calibration) are declared in `research/levers/<model>.yaml` and the first evaluation is a structured design (one-factor ablations against the base recipe), never one configuration; a model whose evidence does not pass iterates from its map, never parked in shadow.

> **One ladder (operator, 2026-11-12, binding; row `ML-ONE-LADDER`).** A model reaches a book the way a strategy does -- [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../../../docs/plans/OPERATING-PLAN-2026-09-21.md) § 2 (the ladder, the soak, three strategy statuses); this skill points at it and restates none of it. The registry `stage` (`candidate`/`shadow`/`advisory`) is a trainer-housekeeping label, never a step to real money; shadow on paper is only for something demoted and in iteration. Operator, verbatim: *"We already said that things get promoted to real money based on backtesting, shadow on paper is only for something that is demoted and in iteration, not a step on the way to real money"*. Gates this adds or changes: none.

# /model-training — drive the ICT bot's ML training lifecycle

> **Practice principles (pointer):** the design and evaluation choices this skill makes follow [`docs/reference/trading-and-model-practice-principles.md`](../../../docs/reference/trading-and-model-practice-principles.md) (TRADING T1–T10 · MODEL M1–M10 · RESEARCH-OPS R1–R6), refreshed weekly by `frontier-research`; a principle never overrides a binding rule.


Training is **autonomous trainer-VM territory** (CLAUDE.md § VM authority
split). Claude provisions, kicks cycles, reads the registry, and analyzes
results without operator-in-the-loop. The registry `stage` is a housekeeping
label, never a step: a model reaches real money by the one flow, backtest →
real money → (if demoted) soak on the demo floor while it iterates. Operator,
2026-11-12, verbatim: *"There is nothing in between proving edge on back testing
and real money. Absolutely no steps."*

**The training run happens on the trainer VM, never in this session.** The
sandbox has no SSH and no GPU; it drives the trainer through the
`trainer-vm-diag` relay (arbitrary bash → issue comment). See the
`diag-data` and `vm-ops` skills for the relay mechanics.

## How training actually runs (the cycle)

`ict-trainer.service` runs `scripts/ops/run_training_cycle.sh`. One cycle:

1. `git fetch && git reset --hard origin/main` (HEAD short-sha logged).
2. Create/activate `.venv` (python3.11) if missing.
3. `scripts/ops/sync_trainer_data.sh` — pull `trade_journal.db` +
   `signal_audit.jsonl` from the live VM (best-effort).
4. `scripts/ops/build_trainer_datasets.sh` — rebuild all families.
5. For each manifest in `$TRAINING_MANIFESTS` (default: every `*.yaml`
   under `ml/configs/`, sorted): `python -m ml train <manifest> --datasets-root … --experiments-root … --registry-root …`.
   - exit `0` → registered; one `manifest_ok` row with `model_id`.
   - exit `78` (EX_CONFIG) → empty dataset, **clean skip** (not a
     failure); `manifest_skipped`. This is expected until the live
     trader has produced enough closed-trade history.
   - other non-zero → `manifest_failed`; cycle ends non-zero.
6. `scripts/ops/publish_trainer_mirror.sh` — mirror registry/results to
   the live VM so `/api/bot/ml/*` and the dashboard Models page update.

Every step appends a JSONL row to `runtime_logs/training_cycle.jsonl`
(`$TRAINING_LOG_PATH`). That log is the primary monitoring surface.

## Kick a cycle (trainer-vm-diag relay)

Open an issue labelled `trainer-vm-diag-request` with a `cmd:` block:

```
cmd: |
  cd /home/ubuntu/ict-trading-bot
  sudo systemctl start ict-trainer.service
  sleep 5
  systemctl is-active ict-trainer.service
  tail -n 5 runtime_logs/training_cycle.jsonl
```

Then poll the issue for the workflow's reply. To run a single manifest
out-of-cycle (faster feedback), set `TRAINING_MANIFESTS`:

```
cmd: |
  cd /home/ubuntu/ict-trading-bot && source .venv/bin/activate
  python -m ml train ml/configs/baseline-trade-outcome-winrate.yaml \
    --datasets-root datasets-out --experiments-root ml/experiments-runs \
    --registry-root ml/registry-store
```

## Monitor a running / finished cycle

```
cmd: |
  REPO=/home/ubuntu/ict-trading-bot
  systemctl is-active ict-trainer.service; systemctl is-active ict-trainer.timer
  journalctl -u ict-trainer.service -n 100 --no-pager
  tail -n 30 "$REPO/runtime_logs/training_cycle.jsonl"
  ls -la "$REPO/datasets-out/" 2>/dev/null
```

Look for: `cycle_start` → per-manifest `manifest_ok|skipped|failed` →
`cycle_end` with `overall_rc`. A healthy daily cycle lands every
trainable manifest with `overall_rc=0` (skips are fine).

## The `python -m ml` CLI

Routed through `ml/__main__.py` → `ml/cli.py`. Subcommands (verified):

| Subcommand | What it does |
|---|---|
| `train <manifest> [--datasets-root --experiments-root --registry-root --commit-sha --no-register]` | Run one experiment, register a candidate, print a JSON summary |
| `list-models [--status S] [--registry-root]` | Enumerate registry entries |
| `list-trainers` / `list-evaluators` / `list-families` | Discover available trainer / evaluator / dataset-family classes |
| `promote <model_id> <status> --by --reason [--gates-acknowledged]` | Legacy WS4 status transition |
| `promote-stage [model_id] --new-stage <stage> --by --reason [--all-pre-shadow]` | WS7 deployment-stage transition (the live ladder) |
| `compare <model_a> <model_b>` | Side-by-side metric diff |
| `shadow-inspect` / `shadow-stats` / `shadow-drift` | Read `runtime_logs/shadow_predictions.jsonl` (tail / aggregate / KS+PSI drift) |
| `backfill-shadow-predictions --db <path> [--registry-root --output --limit]` | Retroactive-decision replay scoring every historical trade |
| `model-attribution --db <path> [--shadow-log --backfill-log --model-id]` | Per-model live attribution: joins shadow scores to realized trade outcomes (AUC + brier vs base-rate). Go-live decision-support; read-only |
| `gate-check <model_id> [--target-stage --db --shadow-log]` | Computed shadow→advisory promotion gates (go/no-go evidence packet). Reports only; never promotes |
| `stage-guard [--db --shadow-log --registry-root]` | Proposes promote/demote/hold for every model from gates + drift + attribution. Read-only — operator runs `promote-stage` to act |
| `build-dataset …` / `validate-dataset <path>` | Passthrough to `ml.datasets` |

> **There is no `python -m ml.registry list`.** `ml/registry/` has no
> `__main__`. Use `python -m ml list-models`. (Older docs got this wrong.)

## Manifests, families, registry

- **Manifests** — `ml/configs/*.yaml` (e.g. `baseline-trade-outcome-winrate.yaml`,
  `baseline-regime-classifier.yaml`, `baseline-setup-quality.yaml`,
  `baseline-execution-quality.yaml`, `mes-*.yaml`). Each declares its
  dataset family, trainer, evaluator, and `target_deployment_stage`
  (every baseline declares `shadow`).
  - **`description:` is mandatory** — a 1–2 sentence human-readable
    summary of what the model does / how it is used. It flows through
    registration into the registry row and is surfaced on the dashboard
    Models page (`/api/bot/ml/registry` → each card's "about" line). When
    you **add a new manifest**, author its `description`; when you change
    what a model does (different trainer, target, dataset, stage intent),
    **update the `description` in the same edit** so the Models page never
    misdescribes a live model. Keep `description` (the "about") distinct
    from `notes` (operational caveats). Older registry rows whose stored
    manifest predates the field re-populate on the next training cycle.
- **Dataset families** — `ml/datasets/families/*.py`: `trade_outcomes`,
  `setup_labels`, `setup_labels_audit`, `execution_quality`,
  `account_context`, `review_journal`, `market_raw`, `market_features`,
  `backtest_results`. Built by `build_trainer_datasets.sh`.
- **Registry** — `ml/registry-store/` (append-only; never edit a past
  `StageEvent`). Read with `list-models`.

## Cost-net labels and the enforced cost gate (2026-10-28, Tier-2, operator-approved)

Operator popup 2026-10-28, verbatim: *"Yes, ship it today (Recommended)"* for labels net of
the full cost stack plus an enforced cost gate on model promotion; revert is one config value.

- **Labels.** `setup_candidates` / `exit_candidates` triple-barrier labels charge fee +
  slippage + perp funding, venue-correct per symbol, through `src/runtime/execution_costs.py`
  (`ml/datasets/labeling/cost_policy.py`; the hold label pays only the holding cost, funding).
  Each row carries `label_cost_basis` (`net` / `gross` / `realized` / `harness`) and
  `label_cost_r`. A dataset keeps the basis it was BUILT with — rebuild to change it.
- **Gate.** Every `ml train` writes `cost_gate.json` and `cost_*` metrics: the model's net R
  per opportunity vs the incumbent and the take-all / take-none / matched-random baselines on
  the same eval rows, plus PSR and a deflated Sharpe over `n_trials` (manifests on the same
  dataset). A run that does not beat them registers at `candidate`; a retrain of a
  shadow/advisory model that does not beat them keeps the incumbent's state. `promote-stage`
  refuses a forward move on a failed/missing evaluation. Families with no net-R value column
  (regime / direction / execution heads) are `not_applicable` — a gap, not a pass.
- **Revert:** `config/ml_training.yaml::cost_net_labels: false` (labels gross, gate report-only).
- **Soak:** the `shadow_soak` gate is mechanical — 1–2 clean scored shadow predictions, no
  calendar term (operator 2026-10-28, *"Same as trades: 1-2 clean"*).

**Naming:** a model promoted to shadow or above gets a display alias (breed = its job, `Breed-<gen><variant>`) in `docs/reference/model_names.yaml` in the same PR as the `promote-stage` record. Aliases are display only; ids never change.

## The registry stage labels (housekeeping, not a ladder to real money)

`candidate → shadow → advisory`

(Stage ladder collapsed 7→3 on 2026-06-16; legacy names alias via
`ml.manifest.canonical_stage`: `research_only`/`backtest_approved` →
`candidate`; `limited_live`/`live_approved` → `advisory`. Old registry rows
still resolve.)

- `candidate`: refused by the shadow factory (never wired onto a strategy).
- `shadow`: model logs predictions, **never** changes an order.
  A `shadow` model auto-wires onto every strategy whose YAML omits
  `shadow_model_ids` — shadow logging is enabled-by-default for newly
  trained models, so Claude does not hand-wire it.
- `advisory`: model output influences the order package through the registry
  consumers. A stage label does not by itself put a model on a book; that
  follows the strategy ladder (OPERATING-PLAN § 2). A change to
  `promote-stage` / `gate-check` / `stage-guard` code is a separate Tier-2
  proposal, not an edit to this skill.

## What to analyze / report

After a cycle: which manifests trained vs skipped (and why — usually
empty dataset, which is fine early), any `manifest_failed` with stderr
tail, new `model_id`s and their metrics, and whether the registry
progressed. For drift on a live shadow model use `shadow-drift`. Flag a
model that's been stuck at `candidate` across cycles (training runs
but nothing passes eval) — that's a `concern`, not silent.

---

## Testing a model idea vs training a model (ML-RQ-RUNNER)

Training a manifest is this skill. **Comparing learners/features against a baseline under a pre-registered rule** (a bake-off,
a conformal evaluation, a control) is a *research queue unit*, not a one-off script and not a training cycle: write the unit with an
`ml_bakeoff:` block, route it to `research-script-run-trainer.yml`, and let the queue run it and research-ops read it — see
`.claude/skills/frontier-research/SKILL.md` § "The research → test → improve loop". Nothing a bake-off does registers or promotes a model.

## Definition of done

A capability is not shipped until something RUNS it (runner, consumer, wiring check). The four-point rule is binding on this skill: [`docs/CLAUDE-RULES-CANONICAL.md`](../../../docs/CLAUDE-RULES-CANONICAL.md) § "Generation Discipline" → "Rule 4 — Definition of done". Verify with `python3 scripts/ci/check_unwired_artifacts.py`.
