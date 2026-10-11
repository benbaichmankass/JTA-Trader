#!/usr/bin/env bash
# system-action wrapper: settle historical intent_reduce legs' realised PnL from
# the exchange-fills store (PERF-FU-REDUCE-PNL).
#
# Runs scripts/ops/backfill_intent_reduce_pnl.py on the live VM.
# DRY-RUN by default — prints every reduce leg's plan (settled / absorbed /
# unverified + reason) and the per-account P&L it would book, real money first,
# WITHOUT writing. Only writes when ACTION_APPLY is true, after a timestamped DB
# backup.
#
# Provenance: a row is booked only from two venue fills (reduce order + parent
# entry order) -> exit_price_source=exchange_fill (MEASURED). Otherwise pnl
# stays NULL and the row is stamped reduce_settlement=unverified with a reason.
#
# Env (passed by system-actions.yml):
#   ACTION_APPLY - "true" to write (backup taken first); else = dry-run report
#   ACTION_IDS   - optional comma-separated trade-id allowlist
#
# Idempotent: a row already carrying notes.reduce_settlement is skipped. Touches
# only exit_reason='intent_reduce_executed' audit rows; no parent row, no venue
# call, no service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/backfill_intent_reduce_pnl.py"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_IDS="${ACTION_IDS:-}"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: backfill not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "backfill-intent-reduce-pnl" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "backfill-intent-reduce-pnl" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

# The fills store lives under DATA_DIR/runtime_state; this SSH shell does not
# carry DATA_DIR, so python's resolver would fall back to <repo>/runtime_state
# and find nothing (BL-20260717-FILLS-STORE-PATH-SPLIT; first dry-run, #17598).
FILLS_DB="$(fills_store_path)"
echo ">>> fills store: ${FILLS_DB}"
ARGS=(--db "${DB_PATH}" --fills-db "${FILLS_DB}")
if [ -n "${ACTION_IDS// }" ]; then
    ARGS+=(--ids "${ACTION_IDS}")
fi
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> backfill-intent-reduce-pnl: APPLY mode — will write (DB backup taken first)."
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> backfill-intent-reduce-pnl: DRY-RUN (set apply: true to write)."
    ;;
esac

cd "${REPO_DIR}"
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
