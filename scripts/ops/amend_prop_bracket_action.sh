#!/usr/bin/env bash
# system-action wrapper: ask the system to set a VM-executed prop ticket's TP and/or SL
# (PROP-BRACKET-APPLY, operator 2026-11-11: "it has to be able to do it on its own").
#
# Runs scripts/ops/amend_prop_bracket.py on the live VM. DRY-RUN by default; it writes the request onto the ticket
# only when ACTION_APPLY is true. The account's executor then applies it through its own amend code. Refuses, with the
# reason, an account that cannot amend (browser dxtrade has no TP amend; phone accounts use the phone channel), a
# ticket that is not placed/filled, a TP on the wrong side of entry and a looser stop.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID       - e.g. velotrade_1                         [required]
#   ACTION_TICKET_ID - prop ticket id (prop-manual-...)         [required]
#   ACTION_NEW_TP    - the TP to rest at                         [this, ACTION_NEW_SL or ACTION_CLEAR_TP]
#   ACTION_NEW_SL    - a tighter stop                            [optional]
#   ACTION_CLEAR_TP  - "true" to remove a TP pin                 [optional]
#   ACTION_REASON    - why (written on the ticket)               [required]
#   ACTION_APPLY     - "true" to write; anything else = dry-run  [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

cd "${REPO_DIR}"
# The prop journal lives in the canonical trade_journal.db. A system-action wrapper runs from a fresh SSH shell and does
# NOT inherit the systemd services' DATA_DIR / TRADE_JOURNAL_DB, so resolve them exactly as every sibling wrapper does
# (src.utils.paths then opens the same file the executor and the web API use). Without this the first dry run read an
# empty default path: "ticket ... not readable in the prop journal" (issue #25083).
DB_PATH="$(runtime_db_path)"
export TRADE_JOURNAL_DB="${DB_PATH}"
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    exit 1
fi
ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required}"
ACTION_TICKET_ID="${ACTION_TICKET_ID:?ACTION_TICKET_ID required}"
ACTION_REASON="${ACTION_REASON:?ACTION_REASON required}"
PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--account "${ACCOUNT_ID}" --ticket-id "${ACTION_TICKET_ID}" --reason "${ACTION_REASON}")
[ -n "${ACTION_NEW_TP:-}" ] && ARGS+=(--tp "${ACTION_NEW_TP}")
[ -n "${ACTION_NEW_SL:-}" ] && ARGS+=(--sl "${ACTION_NEW_SL}")
case "${ACTION_CLEAR_TP:-}" in true|True) ARGS+=(--clear-tp) ;; esac
case "${ACTION_APPLY:-}" in true|True) ARGS+=(--apply) ;; esac

set +e
"${PY}" scripts/ops/amend_prop_bracket.py "${ARGS[@]}"
rc=$?
set -e
log "amend-prop-bracket: exit ${rc}"
exit "${rc}"
