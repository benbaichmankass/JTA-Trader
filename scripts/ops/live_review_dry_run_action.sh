#!/usr/bin/env bash
# system-action wrapper: READ-ONLY per-account dry-run of the live-trade-review
# apply path (LTR-6R-APPLY-PATH, 2026-10-25).
#
# Runs scripts/ops/live_review_apply.py --dry-run on the live VM: for every
# OPEN order package, what EACH account carrying it would do with a stop
# tighten, decided by that account's own RiskManager.approve_amend. With no
# level it probes at the noise floor. Sends no order and writes no stop.
#
# Env (passed by system-actions.yml): none required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"  # sets REPO_DIR (canonical /home/ubuntu/ict-trading-bot)

cd "${REPO_DIR}"

# Inherit the live trader's runtime env (.env) so candles and account config
# resolve exactly as ict-trader-live.service sees them.
load_runtime_secrets

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

echo ">>> live-review-dry-run: READ-ONLY per-account verdicts for every open package"
exec "${PY}" scripts/ops/live_review_apply.py --dry-run
