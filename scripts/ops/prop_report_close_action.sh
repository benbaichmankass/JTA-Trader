#!/usr/bin/env bash
# system-action wrapper: journal the CLOSE of ONE open prop position through the
# sanctioned ingest path (src/prop/prop_report.ingest_report). Tier 2.
#
# Runs scripts/ops/prop_report_close.py on the live VM. DRY-RUN by default:
# prints the ticket + open-fill rows and the close row it would write, writes
# nothing. Only writes when ACTION_APPLY is true, after an SQLite backup of the
# journal. Exit price is optional: absent -> exit/pnl NULL, provenance UNVERIFIED.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID        - the prop account (e.g. breakout_2)            (required)
#   ACTION_TICKET_ID  - the ticket id (prop-manual-<hex>)             (required)
#   ACTION_EXIT_PRICE - optional positive number
#   ACTION_CLOSED_AT  - optional ISO-8601 timestamp
#   ACTION_REASON     - free text stored on the close row
#   ACTION_APPLY      - "true" to write (backup first); else dry-run
#   ACTION_FROM_PLACED - "true" to also close a `placed` row on a `placed` ticket
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/prop_report_close.py"
ACCOUNT_ID="${ACCOUNT_ID:-}"
ACTION_TICKET_ID="${ACTION_TICKET_ID:-}"
ACTION_EXIT_PRICE="${ACTION_EXIT_PRICE:-}"
ACTION_CLOSED_AT="${ACTION_CLOSED_AT:-}"
ACTION_REASON="${ACTION_REASON:-}"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_FROM_PLACED="${ACTION_FROM_PLACED:-}"

if [ -z "${ACCOUNT_ID}" ] || [ -z "${ACTION_TICKET_ID}" ]; then
    log "ERROR: prop-report-close needs ACCOUNT_ID and ACTION_TICKET_ID."
    exit 1
fi
if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "prop-report-close" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "prop-report-close" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--db "${DB_PATH}" --account "${ACCOUNT_ID}" --ticket-id "${ACTION_TICKET_ID}" --reason "${ACTION_REASON}")
[ -n "${ACTION_EXIT_PRICE}" ] && ARGS+=(--exit-price "${ACTION_EXIT_PRICE}")
[ -n "${ACTION_CLOSED_AT}" ] && ARGS+=(--closed-at "${ACTION_CLOSED_AT}")
case "${ACTION_FROM_PLACED}" in true|True) ARGS+=(--from-placed) ;; esac
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> prop-report-close: APPLY mode — will write (DB backup taken first)."
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> prop-report-close: DRY-RUN (set apply: true to write)."
    ;;
esac

cd "${REPO_DIR}"
set +e
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
rc=$?
set -e
record_audit "prop-report-close" "$([ "${rc}" -eq 0 ] && echo ok || echo refused)" \
    "{\"account\": \"${ACCOUNT_ID}\", \"ticket_id\": \"${ACTION_TICKET_ID}\", \"apply\": \"${ACTION_APPLY}\", \"rc\": ${rc}}" >/dev/null || true
exit "${rc}"
