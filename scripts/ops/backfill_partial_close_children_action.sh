#!/usr/bin/env bash
# system-action wrapper: backfill partial-close child rows + the exit they corrupted
# (PARTIAL-CLOSE-PNL-NOT-JOURNALED / DEMO-EXIT-FIRST-FILL-ATTRIBUTION).
#
# Runs scripts/ops/backfill_partial_close_children.py on the live VM against the committed,
# venue-verified plan docs/research/evidence/partial-close-backfill-plan-2026-11-12.json.
# DRY-RUN by default: every item is re-verified against the exchange-fills store and printed
# with its exact before/after; nothing is written. ACTION_APPLY=true writes, after an online
# SQLite backup. Idempotent (a booked close order / a corrected exit is skipped). No venue
# call, no service touched.
#
# Env (passed by system-actions.yml):
#   ACTION_APPLY - "true" to write (backup taken first); else = dry-run report
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/backfill_partial_close_children.py"
ACTION_APPLY="${ACTION_APPLY:-}"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: backfill not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "backfill-partial-close-children" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "backfill-partial-close-children" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"
FILLS_DB="$(fills_store_path)"
echo ">>> fills store: ${FILLS_DB}"
ARGS=(--db "${DB_PATH}" --fills-db "${FILLS_DB}")
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> backfill-partial-close-children: APPLY mode (online DB backup taken first)."
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> backfill-partial-close-children: DRY-RUN (set apply: true to write)."
    ;;
esac

cd "${REPO_DIR}"
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
