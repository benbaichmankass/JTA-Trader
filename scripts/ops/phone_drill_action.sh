#!/usr/bin/env bash
# Tier-1 system-action: request ONE phone REHEARSAL DRILL for a phone-driven prop
# account (PHONE-EXEC-OBSERVABLE-1018; operator decision 2026-10-18).
#
# The drill makes the phone executor run the full stop-amend flow on its real
# open position up to the final Confirm -- Positions tab, row target + native
# touch, the sheet, [Position details], [n TP / n SL], the Stop row, its pencil,
# the "Edit Stop loss" modal, ONLY the Trigger typed and read back -- then
# CANCEL the modal, re-read the stop unchanged and close the sheet, reporting
# pass/fail per step with a capture of each step. NO ORDER CHANGES: the app
# never confirms in a drill, the denylist refuses every close / cancel control,
# nothing is journaled as an amend. Three consecutive passes arm the live sheet
# edit (the operator's "done when"); a fail resets the streak.
#
# This writes ONE request file beside the journal (src.prop.phone_drill); the
# phone claims it on its next poll (it brings itself to the front: the sheet
# needs the screen). A request already outstanding is returned, not doubled.
# The account must be a phone_accounts entry in config/prop_platforms.yaml --
# anything else is REFUSED (exit 1, nothing written). No exchange socket.
#
# Dispatched by the system-actions workflow (issue body:
#   action: phone-drill
#   account: breakout_2          (required)
# ). The workflow threads ACCOUNT_ID and the dispatching issue number as
# ACTION_ISSUE (recorded as the request's `by`).
# Verify: GET /api/diag/phone_drill?account_id=<acct> (pending, then a result),
# GET /api/diag/phone_captures?account_id=<acct> (the drill's capture run).
#
# Exit codes: 0 = request written (or already outstanding), 1 = refused or failed.

set -euo pipefail

SCRIPT_NAME="phone_drill_action"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

# The request must land beside the canonical trade_journal.db the web API serves
# GET /phone/pending from -- resolve DATA_DIR / TRADE_JOURNAL_DB the way the trader does.
load_runtime_env

ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required (issue body: account: <phone_accounts key>)}"
SOURCE="phone-drill${ACTION_ISSUE:+#${ACTION_ISSUE}}"
WRITER="${REPO_DIR}/scripts/prop/phone_drill.py"

if [ ! -f "${WRITER}" ]; then
    log "ERROR: ${WRITER} not found."
    record_audit "phone-drill" "error" '{"reason": "phone_drill.py missing"}' >/dev/null || true
    exit 1
fi

# symbol: (optional) = a drill WITH A TEST TRADE under MD-EXEC-DEV-TEST-TRADES: the
# server writes ONE minimum-size exec-test ticket at claim (bounds checked), the
# app places it, amends its stop INCLUDING Confirm, reads back and CLOSES it.
TEST_TRADE="${ACTION_SYMBOL:-}"
EXTRA=()
if [ -n "${TEST_TRADE// }" ]; then EXTRA=(--test-trade "${TEST_TRADE}"); fi

log "Requesting ONE phone rehearsal drill (account=${ACCOUNT_ID} source=${SOURCE}${TEST_TRADE:+ test_trade=${TEST_TRADE}})."
if OUT="$(cd "${REPO_DIR}" && /usr/bin/python3 "${WRITER}" --request --account "${ACCOUNT_ID}" --source "${SOURCE}" "${EXTRA[@]}")"; then
    printf '%s\n' "${OUT}"
    record_audit "phone-drill" "ok" "{\"account\": \"${ACCOUNT_ID}\", \"result\": ${OUT:-null}}" >/dev/null || true
    log "phone-drill: request written; the phone claims it on its next poll and reports per step (GET /api/diag/phone_drill)."
    exit 0
else
    printf '%s\n' "${OUT:-}"
    record_audit "phone-drill" "failed" "{\"account\": \"${ACCOUNT_ID}\", \"result\": ${OUT:-null}}" >/dev/null || true
    log "ERROR: phone_drill.py refused or failed (nothing written)."
    exit 1
fi
