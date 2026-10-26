#!/usr/bin/env bash
# system-action wrapper: dispatch ONE committed live-review tighten_sl row to
# the per-account apply path (LTR-APPLY-DISPATCH, operator 2026-10-26 ~07:12Z).
#
# Runs scripts/ops/live_review_dispatch.py on the live VM. It re-reads the row
# from the COMMITTED comms/live_review/reviews.jsonl at HEAD (main, via
# ict-git-sync), re-checks MD-LIVE-TIGHTEN-SL's package-level clauses, and hands
# the row to scripts/ops/live_review_apply.py. That script decides each account
# through its own RiskManager.approve_amend and executor, reads the venue back,
# and pings. DRY-RUN by default; it executes only when ACTION_APPLY is true.
# Idempotent per review_id.
#
# Env (passed by system-actions.yml):
#   ACTION_REVIEW_ID - the review row's review_id (LR-…)            [required]
#   ACTION_APPLY     - "true" to execute; anything else = dry-run    [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"  # sets REPO_DIR (canonical /home/ubuntu/ict-trading-bot)

cd "${REPO_DIR}"

# Inherit the live trader's runtime env (.env) so venue clients, candles and
# account config resolve exactly as ict-trader-live.service sees them.
load_runtime_secrets

ACTION_REVIEW_ID="${ACTION_REVIEW_ID:?ACTION_REVIEW_ID required}"
ACTION_APPLY="${ACTION_APPLY:-}"

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--review-id "${ACTION_REVIEW_ID}")
# Optional pinned commit (LTR rows branch): the dispatcher fetches it itself, so
# the apply never waits for ict-git-sync.
if [ -n "${ACTION_REVIEW_REF:-}" ]; then
  ARGS+=(--ref "${ACTION_REVIEW_REF}")
fi
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> live-review-apply: APPLY — ${ACTION_REVIEW_ID} through each account's own risk manager"
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> live-review-apply: DRY-RUN (set apply: true to execute) for ${ACTION_REVIEW_ID}"
    ;;
esac

exec "${PY}" scripts/ops/live_review_dispatch.py "${ARGS[@]}"
