#!/usr/bin/env bash
# Tier-2 operator action: backfill meta.risk_per_unit / meta.entry_time on OPEN ml_entry + claude_desk packages
# (ML-ENTRY-RISK-META). Wraps scripts/ops/backfill_package_risk_meta.py. DRY-RUN unless `apply: true`.
# Writes only order_packages.meta (missing keys only); no trade row, order, money field or venue; no restart.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

ACTION_SLUG="backfill-package-risk-meta"
DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/backfill_package_risk_meta.py"

if [ ! -f "${PY_SCRIPT}" ] || [ ! -f "${DB_PATH}" ]; then
    log "ERROR: helper (${PY_SCRIPT}) or db (${DB_PATH}) missing."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"helper or db missing\"}" >/dev/null || true
    exit 1
fi

APPLY_FLAG=""
case "${ACTION_APPLY:-}" in
    true|True) APPLY_FLAG="--apply" ;;
esac

set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}" ${APPLY_FLAG}
exit_code=$?
set -e

if [ "${exit_code}" -ne 0 ]; then
    record_audit "${ACTION_SLUG}" "failed" "{\"apply\": \"${ACTION_APPLY:-}\", \"exit_code\": ${exit_code}}" >/dev/null || true
    exit "${exit_code}"
fi
record_audit "${ACTION_SLUG}" "ok" "{\"apply\": \"${ACTION_APPLY:-}\"}" >/dev/null || true
log "${ACTION_SLUG} complete (apply=${ACTION_APPLY:-false}). Verify via /api/diag/journal?table=order_packages."
exit 0
