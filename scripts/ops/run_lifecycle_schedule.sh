#!/usr/bin/env bash
# scripts/ops/run_lifecycle_schedule.sh — body of ict-trainer-lifecycle.service (TIER-2 unit; prepared, not installed).
# Runs the per-model lifecycle scheduler (ml/lifecycle/scheduler.py) on the trainer VM with ZERO Anthropic usage.
# Serialises behind the shared heavy-job queue so it never races a training cycle. Never exits non-zero for job
# failures (no halting; the signal is a lifecycle_red_flag event in training_cycle.jsonl).
set -uo pipefail
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/ict-trading-bot}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
cd "$REPO_ROOT" || exit 2
export REPO_ROOT
# shellcheck source=/dev/null
. "$REPO_ROOT/scripts/ops/_trainer_heavy_lock.sh"
take_trainer_heavy_lock "lifecycle_schedule" || exit 0   # busy past the wait: next timer retries
# shellcheck source=/dev/null
[ -f "$VENV_DIR/bin/activate" ] && source "$VENV_DIR/bin/activate"
python -m ml.lifecycle.scheduler "$@"
exit 0
