#!/usr/bin/env bash
# Tier-2 action: relabel NAMED closed trades whose entry order never filled as
# exit_reason='entry_unfilled' with the explicit notes.pnl_source='unmeasured'
# marker (the one db-integrity INV-2 accepts).
#
# WHY THIS EXISTS. PR #27537 makes the snapshot reconciler label these rows at
# close time. Rows closed before it deployed still read exchange_flat_reconciled
# (or stuck_strategy_watchdog) with pnl NULL, so INV-2 and the mechanics grader
# flag them as close faults. Measured case: alpaca_options_paper trade 8034.
#
# Wraps scripts/ops/mark_entry_unfilled.py. Self-test as a PRECONDITION, then a
# BEFORE table, a dry-run plan, --apply (online SQLite backup first, one
# transaction), and an AFTER table. Every id is venue-verified (terminal entry
# order, filled_qty 0); ANY refusal writes nothing. Touches no monetary field and
# no service (no restart required).
set -euo pipefail
_DBR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/db_read.py"

SCRIPT_NAME="mark_entry_unfilled"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

# Secrets FIRST, then the DB path: the same order as every working DB wrapper
# (grade_closed_trades, backfill_closed_null_pnl, ...). The first live run
# (issue #27636) resolved the path the other way round, behind an early cd,
# and both reads then opened a file that is not the journal.
load_runtime_secrets
DB_PATH="$(runtime_db_path)"
cd "${REPO_DIR}"
PY_SCRIPT="${REPO_DIR}/scripts/ops/mark_entry_unfilled.py"
PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

TRADE_IDS="${ACTION_TRADE_ID:-}"
REASON_TEXT="${ACTION_REASON:-}"

fail() {
    log "ERROR: $1"
    record_audit "mark-entry-unfilled" "error" "{\"reason\": \"$2\"}" >/dev/null || true
    exit 1
}
[ -n "${TRADE_IDS// }" ] || fail "ACTION_TRADE_ID is empty; this action never derives its targets." "no trade_id"
printf '%s' "${TRADE_IDS}" | grep -Eq '^[0-9]+(,[0-9]+)*$' \
    || fail "trade_id '${TRADE_IDS}' invalid (want digits, comma-separated)." "bad trade_id format"
[ -n "${REASON_TEXT// }" ] || fail "ACTION_REASON is empty." "no reason text"
[ -f "${PY_SCRIPT}" ] || fail "helper not present at ${PY_SCRIPT}. Did the VM pull the latest main?" "helper missing"
[ -f "${DB_PATH}" ] || fail "trade_journal.db not present at ${DB_PATH}." "db missing"

# The venue check reads the entry order from Alpaca, so authenticate exactly like
# the live services (same pattern as rearm_alpaca_protective_action.sh). Presence
# diagnostics only; never echoes a value. (load_runtime_secrets ran above.)
WEBAPI_ENV="/etc/ict-trader/web-api.env"
if sudo test -r "${WEBAPI_ENV}" 2>/dev/null; then
  for _v in ALPACA_API_KEY_ID_LIVE ALPACA_API_SECRET_KEY_LIVE \
            ALPACA_API_KEY_ID ALPACA_API_SECRET_KEY \
            ALPACA_API_KEY_ID_OPTIONS ALPACA_API_SECRET_KEY_OPTIONS; do
    _val="$(sudo grep -E "^${_v}=" "${WEBAPI_ENV}" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    if [ -n "${_val}" ]; then
      export "${_v}=${_val}"
      echo ">>> creds: ${_v} sourced from web-api.env"
    elif [ -n "${!_v:-}" ]; then
      echo ">>> creds: ${_v} absent in web-api.env; using repo .env value"
    else
      echo ">>> creds: ${_v} absent in web-api.env AND empty/unset in repo .env"
    fi
    unset _val
  done
else
  echo ">>> creds: web-api.env not sudo-readable; using repo .env creds only"
fi

echo
echo "===== DB: ${DB_PATH} ====="
ls -la "${DB_PATH}" || true
# Fail fast, before anything else reads it: the resolved file must be the journal.
if ! python3 "${_DBR}" "${DB_PATH}" "SELECT COUNT(*) FROM trades;" >/dev/null 2>&1; then
    fail "${DB_PATH} has no readable trades table; refusing (not the trade journal)." "db not the journal"
fi

echo
echo "===== PRECONDITION: mark_entry_unfilled.py --self-test ====="
"${PY}" "${PY_SCRIPT}" --self-test

SHOW="SELECT t.id, t.account_id, t.symbol, t.status, t.exit_reason, t.pnl, p.close_reason AS pkg_close_reason, \
      CASE WHEN json_valid(t.notes) THEN json_extract(t.notes,'\$.pnl_source') END AS pnl_source FROM trades t \
      LEFT JOIN order_packages p ON p.order_package_id = t.order_package_id WHERE t.id IN (${TRADE_IDS});"

echo
echo "===== BEFORE ====="
python3 "${_DBR}" --table "${DB_PATH}" "${SHOW}" || true

echo
echo "===== DRY-RUN plan ====="
set +e
TRADE_JOURNAL_DB="${DB_PATH}" "${PY}" "${PY_SCRIPT}" --db "${DB_PATH}" --trade-ids "${TRADE_IDS}" --reason "${REASON_TEXT}"
dry_code=$?
set -e
if [ "${dry_code}" -ne 0 ]; then
    record_audit "mark-entry-unfilled" "refused" \
        "{\"trade_ids\": \"${TRADE_IDS}\", \"exit_code\": ${dry_code}}" >/dev/null || true
    log "ERROR: dry-run refused (exit ${dry_code}); nothing written."
    exit "${dry_code}"
fi

echo
echo "===== APPLY ====="
set +e
TRADE_JOURNAL_DB="${DB_PATH}" "${PY}" "${PY_SCRIPT}" --db "${DB_PATH}" --trade-ids "${TRADE_IDS}" --reason "${REASON_TEXT}" --apply
exit_code=$?
set -e

echo
echo "===== AFTER ====="
python3 "${_DBR}" --table "${DB_PATH}" "${SHOW}" || true

if [ "${exit_code}" -ne 0 ]; then
    record_audit "mark-entry-unfilled" "failed" \
        "{\"trade_ids\": \"${TRADE_IDS}\", \"exit_code\": ${exit_code}}" >/dev/null || true
    log "ERROR: helper exited ${exit_code}."
    exit "${exit_code}"
fi
record_audit "mark-entry-unfilled" "ok" "{\"trade_ids\": \"${TRADE_IDS}\"}" >/dev/null || true
log "entry_unfilled relabel complete for trade ids ${TRADE_IDS}."
exit 0
