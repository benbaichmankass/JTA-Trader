#!/usr/bin/env bash
# Tier-2 operator action: set ONE open journal row's position_size to the venue's quantity.
#
# Wraps scripts/ops/set_journal_trade_qty.py (self-test as a PRECONDITION, then a dry-run plan, then --apply only
# when ACTION_APPLY=true). Targets are NAMED (trade_id + account + symbol + the quantity the caller READ), never
# derived. The prior value goes in notes.qty_writeback AND in the audit record below. No full-journal backup:
# the write is one guarded row UPDATE whose prior value is recorded, and the journal is 2 GB (disk pressure).
set -euo pipefail

SCRIPT_NAME="set_journal_trade_qty"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/set_journal_trade_qty.py"

TRADE_ID="${ACTION_TRADE_ID:-}"
ACCT="${ACCOUNT_ID:-}"
SYM="${ACTION_SYMBOL:-}"
NEW_QTY="${ACTION_NEW_QTY:-}"
EXPECT_QTY="${ACTION_EXPECT_QTY:-}"
REASON_TEXT="${ACTION_REASON:-}"
APPLY="${ACTION_APPLY:-}"

fail() {
    log "ERROR: $1"
    record_audit "set-journal-trade-qty" "error" "{\"reason\": \"$1\"}" >/dev/null || true
    exit 1
}
printf '%s' "${TRADE_ID}" | grep -Eq '^[0-9]+$' || fail "trade_id must be digits"
printf '%s' "${ACCT}" | grep -Eq '^[A-Za-z0-9_-]+$' || fail "account missing or invalid"
printf '%s' "${SYM}" | grep -Eq '^[A-Za-z0-9_]+$' || fail "symbol missing or invalid"
printf '%s' "${NEW_QTY}" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || fail "new_qty must be a positive decimal"
printf '%s' "${EXPECT_QTY}" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || fail "expect_qty must be a positive decimal"
[ -n "${REASON_TEXT// }" ] || fail "reason is empty"
[ -f "${PY_SCRIPT}" ] || fail "helper missing at ${PY_SCRIPT}; did the VM pull main?"
[ -f "${DB_PATH}" ] || fail "trade_journal.db not present at ${DB_PATH}"

echo "===== PRECONDITION: set_journal_trade_qty.py --self-test ====="
python3 "${PY_SCRIPT}" --self-test

echo "===== BEFORE ====="
sqlite3 -header -column "${DB_PATH}" \
    "SELECT id, account_id, symbol, status, direction, position_size FROM trades WHERE id = ${TRADE_ID};" || true

ARGS=(--trade-id "${TRADE_ID}" --account "${ACCT}" --symbol "${SYM}" --expect-qty "${EXPECT_QTY}" \
      --new-qty "${NEW_QTY}" --reason "${REASON_TEXT}")
case "${APPLY}" in
    true|True) ARGS+=(--apply); echo "===== APPLY =====" ;;
    *) echo "===== DRY-RUN (set apply: true to write) =====" ;;
esac
set +e
TRADE_JOURNAL_DB="${DB_PATH}" python3 "${PY_SCRIPT}" "${ARGS[@]}"
exit_code=$?
set -e

echo "===== AFTER ====="
sqlite3 -header -column "${DB_PATH}" \
    "SELECT id, account_id, symbol, status, direction, position_size FROM trades WHERE id = ${TRADE_ID};" || true

if [ "${exit_code}" -ne 0 ]; then
    record_audit "set-journal-trade-qty" "failed" \
        "{\"trade_id\": ${TRADE_ID}, \"exit_code\": ${exit_code}}" >/dev/null || true
    exit "${exit_code}"
fi
record_audit "set-journal-trade-qty" "ok" \
    "{\"trade_id\": ${TRADE_ID}, \"account\": \"${ACCT}\", \"symbol\": \"${SYM}\", \"expect_qty\": ${EXPECT_QTY}, \"new_qty\": ${NEW_QTY}, \"apply\": \"${APPLY:-false}\"}" >/dev/null || true
exit 0
