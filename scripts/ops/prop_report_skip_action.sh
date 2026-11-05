#!/usr/bin/env bash
# system-action wrapper: journal ONE prop ticket that never became a position as
# `skipped`, through prop_report.ingest_report (BREAKOUT-UNRECORDED-1101,
# 2026-11-05, operator decision "Approve, via a system action"). Tier 2.
#
# Runs scripts/ops/prop_report_skip.py on the live VM. DRY-RUN by default:
# prints the ticket and its fill rows, and the skipped report as it would be
# sent. Writes only when ACTION_APPLY is true AND ACTION_CONFIRM echoes the
# ticket id, after an SQLite backup of the journal.
#
# Refused (exit 3, nothing written): an empty reason, an unconfigured account,
# a missing ticket or one belonging to another account, a ticket not
# placed/emitted, or any open/filled/closed fill row on it (that is a position,
# which belongs to prop-report-close).
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID       - the prop account (e.g. breakout_2)           (required)
#   ACTION_TICKET_ID - the ticket id (prop-manual-<hex>)            (required)
#   ACTION_REASON    - why it never filled                          (required)
#   ACTION_APPLY     - "true" to write (backup first); else dry-run
#   ACTION_CONFIRM   - must equal ACTION_TICKET_ID for apply
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/prop_report_skip.py"
ACCOUNT_ID="${ACCOUNT_ID:-}"
ACTION_TICKET_ID="${ACTION_TICKET_ID:-}"
ACTION_REASON="${ACTION_REASON:-}"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_CONFIRM="${ACTION_CONFIRM:-}"

if [ -z "${ACCOUNT_ID}" ] || [ -z "${ACTION_TICKET_ID}" ]; then
    log "ERROR: prop-report-skip needs ACCOUNT_ID and ACTION_TICKET_ID."
    exit 1
fi
if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull latest main?"
    record_audit "prop-report-skip" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "prop-report-skip" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--db "${DB_PATH}" --account "${ACCOUNT_ID}" --ticket-id "${ACTION_TICKET_ID}" --reason "${ACTION_REASON}")
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> prop-report-skip: APPLY mode — will write (DB backup taken first) if confirm matches."
    ARGS+=(--apply --confirm "${ACTION_CONFIRM}")
    ;;
  *)
    echo ">>> prop-report-skip: DRY-RUN (set apply: true and confirm: <ticket_id> to write)."
    ;;
esac

cd "${REPO_DIR}"
set +e
"${PY}" "${PY_SCRIPT}" "${ARGS[@]}"
rc=$?
set -e
record_audit "prop-report-skip" "$([ "${rc}" -eq 0 ] && echo ok || echo refused)" \
    "{\"account\": \"${ACCOUNT_ID}\", \"ticket_id\": \"${ACTION_TICKET_ID}\", \"apply\": \"${ACTION_APPLY}\", \"rc\": ${rc}}" >/dev/null || true
exit "${rc}"
