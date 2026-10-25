#!/usr/bin/env bash
# system-action wrapper: price closed trades' exits from the venue fill that
# closed them (SOAK-MECH-B / PI-20261010-RNCT2YDP-0001).
#
# Runs scripts/ops/backfill_own_fill_exits.py on the live VM.
# DRY-RUN by default — prints every row's plan (old -> new exit price and pnl,
# the matched venue order) WITHOUT writing. Only writes when ACTION_APPLY is
# true AND an ids allowlist is given, after an online DB backup.
#
# Provenance: exit_price comes from exchange-fills store rows (venue fills) ->
# exit_price_source=exchange_fill (MEASURED); pnl is local compute net of the
# close-side fees. A row whose exit is already MEASURED is never touched, and
# exit_reason is never changed (backfill-exit-labels owns labels).
#
# Env (passed by system-actions.yml):
#   ACTION_APPLY - "true" to write (backup taken first); else = dry-run report
#   ACTION_IDS   - comma-separated trade-id allowlist (required to apply)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/backfill_own_fill_exits.py"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_IDS="${ACTION_IDS:-}"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: backfill not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "backfill-own-fill-exits" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "backfill-own-fill-exits" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

# This SSH shell does not carry DATA_DIR, so resolve the fills store here
# (BL-20260717-FILLS-STORE-PATH-SPLIT).
FILLS_DB="$(fills_store_path)"
echo ">>> fills store: ${FILLS_DB}"
ARGS=(--db "${DB_PATH}" --fills-db "${FILLS_DB}")
if [ -n "${ACTION_IDS// }" ]; then
    ARGS+=(--ids "${ACTION_IDS}")
fi
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> backfill-own-fill-exits: APPLY mode — will write (DB backup taken first)."
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> backfill-own-fill-exits: DRY-RUN (set apply: true and ids: to write)."
    ;;
esac

cd "${REPO_DIR}"
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
