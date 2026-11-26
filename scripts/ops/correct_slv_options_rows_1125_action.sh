#!/usr/bin/env bash
# Tier-2 operator action: correct alpaca_options_paper rows 8569 / 8612 / 8613 (2026-11-25) from their venue fills.
#
# Wraps scripts/ops/correct_slv_options_rows_1125.py. Operator decision, 2026-11-26 popup, verbatim: "Backfill the P&L
# (Recommended)", carried out by the venue-fill method (manager 26a): 8612/8613 get exit_price + pnl from the Alpaca
# market exit fills (-2.00 / -8.00 USD, 100-share contracts); 8569, whose entry filled only after it closed, is labelled
# entry_unfilled with pnl declared unmeasured (P&L carried on 8612/8613). Refuses on any mismatch; idempotent.
#
# Always prints the dry-run plan. Writes ONLY when the issue body carries `apply: true` (the FIX-CA-14 opt-in).
# Never touches an order, SL/TP, size or a service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/correct_slv_options_rows_1125.py"
PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull the latest main?"
    record_audit "correct-slv-options-rows-1125" "error" "{\"reason\": \"helper missing\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "correct-slv-options-rows-1125" "error" "{\"reason\": \"db missing\"}" >/dev/null || true
    exit 1
fi

cd "${REPO_DIR}"
echo
echo "===== correct_slv_options_rows_1125.py (DRY-RUN plan) ====="
set +e
"${PY}" "${PY_SCRIPT}" --db "${DB_PATH}"
dry_code=$?
set -e
if [ "${dry_code}" -ne 0 ]; then
    log "ERROR: dry-run refused or failed (exit ${dry_code}) -- NOT applying."
    record_audit "correct-slv-options-rows-1125" "failed" "{\"phase\": \"dry-run\", \"exit_code\": ${dry_code}}" >/dev/null || true
    exit "${dry_code}"
fi

case "${ACTION_APPLY:-}" in
    true|True) ;;
    *)
        log "DRY-RUN only (no 'apply: true' in the issue body): nothing written."
        record_audit "correct-slv-options-rows-1125" "ok" "{\"phase\": \"dry-run\"}" >/dev/null || true
        exit 0
        ;;
esac

echo
echo "===== correct_slv_options_rows_1125.py --apply (COMMIT) ====="
set +e
"${PY}" "${PY_SCRIPT}" --db "${DB_PATH}" --apply
apply_code=$?
set -e
if [ "${apply_code}" -ne 0 ]; then
    log "ERROR: apply exited ${apply_code}."
    record_audit "correct-slv-options-rows-1125" "failed" "{\"phase\": \"apply\", \"exit_code\": ${apply_code}}" >/dev/null || true
    exit "${apply_code}"
fi
record_audit "correct-slv-options-rows-1125" "ok" "{\"phase\": \"apply\"}" >/dev/null || true
log "correct-slv-options-rows-1125 complete."
