#!/usr/bin/env bash
# Tier-2 operator action: relabel 13 closed order packages whose close_reason still
# carries a bookkeeping label while every linked trade reads sl/tp.
# Wraps scripts/ops/relabel_package_close_reasons.py (CLOSE-REASON-XRP-1220).
# DRY-RUN by default; `apply: true` (issue body) writes. Fixed id list, conditional UPDATE,
# idempotent. Touches no trade row, money field or venue; no service restart.
set -euo pipefail

SCRIPT_NAME="relabel_package_close_reasons"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

ACTION_SLUG="relabel-package-close-reasons"
DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/${SCRIPT_NAME}.py"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull the latest main?"
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"helper missing\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"db missing\"}" >/dev/null || true
    exit 1
fi

APPLY_FLAG=""
case "${ACTION_APPLY:-}" in
    true|True) APPLY_FLAG="--apply" ;;
esac

if [ -n "${APPLY_FLAG}" ]; then
    log "Running ${SCRIPT_NAME}.py --apply (Tier-2 DB write) on ${DB_PATH} ..."
else
    log "Running ${SCRIPT_NAME}.py DRY RUN (pass apply: true to write) on ${DB_PATH} ..."
fi

set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}" ${APPLY_FLAG}
exit_code=$?
set -e

if [ "${exit_code}" -ne 0 ]; then
    record_audit "${ACTION_SLUG}" "failed" \
        "{\"apply\": \"${ACTION_APPLY:-}\", \"exit_code\": ${exit_code}}" >/dev/null || true
    log "ERROR: helper exited ${exit_code}."
    exit "${exit_code}"
fi
record_audit "${ACTION_SLUG}" "ok" "{\"apply\": \"${ACTION_APPLY:-}\"}" >/dev/null || true
log "${ACTION_SLUG} complete (apply=${ACTION_APPLY:-false}). Verify the post-state independently via /api/diag/journal?table=order_packages."
exit 0
