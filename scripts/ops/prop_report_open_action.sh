#!/usr/bin/env bash
# system-action wrapper: journal ONE prop ticket as an OPEN position (filled) through the
# sanctioned ingest path (src/prop/prop_report.ingest_report). Tier 2.
#
# Runs scripts/ops/prop_report_open.py on the live VM. DRY-RUN by default. Writes only with
# ACTION_APPLY=true AND ACTION_CONFIRM equal to the ticket id, after an SQLite backup.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID          - the prop account (e.g. breakout_2)        (required)
#   ACTION_TICKET_ID    - the ticket id (prop-manual-<hex>)         (required)
#   ACTION_REASON       - who confirmed the position is open, verbatim (required)
#   ACTION_ENTRY_PRICE  - optional positive fill price (else the ticket's planned entry, labelled)
#   ACTION_OPENED_AT    - optional ISO-8601 open time
#   ACTION_APPLY        - "true" to write; ACTION_CONFIRM must echo the ticket id
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/prop_report_open.py"
ACCOUNT_ID="${ACCOUNT_ID:-}"
ACTION_TICKET_ID="${ACTION_TICKET_ID:-}"
ACTION_REASON="${ACTION_REASON:-}"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_CONFIRM="${ACTION_CONFIRM:-}"
ACTION_ENTRY_PRICE="${ACTION_ENTRY_PRICE:-}"
ACTION_OPENED_AT="${ACTION_OPENED_AT:-}"

if [ -z "${ACCOUNT_ID}" ] || [ -z "${ACTION_TICKET_ID}" ]; then
    log "ERROR: prop-report-open needs ACCOUNT_ID and ACTION_TICKET_ID."
    exit 1
fi
if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "prop-report-open" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "prop-report-open" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--db "${DB_PATH}" --account "${ACCOUNT_ID}" --ticket-id "${ACTION_TICKET_ID}" --reason "${ACTION_REASON}")
[ -n "${ACTION_ENTRY_PRICE}" ] && ARGS+=(--entry-price "${ACTION_ENTRY_PRICE}")
[ -n "${ACTION_OPENED_AT}" ] && ARGS+=(--opened-at "${ACTION_OPENED_AT}")
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> prop-report-open: APPLY mode — will write (DB backup taken first) if confirm matches."
    ARGS+=(--apply --confirm "${ACTION_CONFIRM}")
    ;;
  *)
    echo ">>> prop-report-open: DRY-RUN (set apply: true and confirm: <ticket_id> to write)."
    ;;
esac

cd "${REPO_DIR}"
set +e
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
rc=$?
set -e
record_audit "prop-report-open" "$([ "${rc}" -eq 0 ] && echo ok || echo refused)" \
    "{\"account\": \"${ACCOUNT_ID}\", \"ticket_id\": \"${ACTION_TICKET_ID}\", \"apply\": \"${ACTION_APPLY}\", \"rc\": ${rc}}" >/dev/null || true
exit "${rc}"
