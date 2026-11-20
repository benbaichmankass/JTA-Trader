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
# Read-only forensics for the first live run (issue #27636): what the OLD order (cd first, path
# before secrets) resolves to in a clean shell, and whether a stray journal sits there or at the
# known CWD-fallback locations. Prints and lists only; never writes or removes anything.
OLD_ORDER_PATH="$(env -i HOME="${HOME}" PATH="${PATH}" bash -c \
    "source '${SCRIPT_DIR}/_lib.sh' >/dev/null 2>&1; cd '${REPO_DIR}'; runtime_db_path" 2>/dev/null || true)"
echo ">>> old-order path (issue #27636 ordering, clean shell): ${OLD_ORDER_PATH:-<unresolved>}"
# WAL hypothesis (manager, 04:47Z): a mode=ro open of a WAL journal needs write access to the
# -wal/-shm sidecars or the directory. Show who we are and the modes involved.
echo ">>> id: $(id)"
ls -ld "$(dirname "${DB_PATH}")" 2>/dev/null || true
ls -l "${DB_PATH}" "${DB_PATH}-wal" "${DB_PATH}-shm" 2>&1 || true
for _p in "${OLD_ORDER_PATH}" "${REPO_DIR}/trade_journal.db" "${REPO_DIR}/src/bot/trade_journal.db"; do
    [ -n "${_p}" ] && { ls -la "${_p}" 2>/dev/null || echo ">>> absent: ${_p}"; }
done
# Fail fast, before anything else reads it: the resolved file must be the journal.
# A read-write open (never creating), the way grade_closed_trades' python opens it; NOT db_read's
# mode=ro, which on a WAL journal also needs the sidecars and may be the #27636 failure itself.
if ! python3 -c 'import sqlite3,sys; sqlite3.connect("file:"+sys.argv[1]+"?mode=rw", uri=True, timeout=30).execute("SELECT COUNT(*) FROM trades").fetchone()' "${DB_PATH}"; then
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

# REPAIR PASS (trade 8034, issue #27646): a row relabelled by an earlier run whose notes lost the INV-2
# marker to the 500-char cap gets its notes rebuilt from that run's pre-write backup. The helper
# skips rows that already carry the marker and refuses any backup whose row is not the pre-write
# flat-detector state, so the newest backup that passes a dry-run is the one used.
if [ "${exit_code}" -eq 0 ]; then
    echo
    echo "===== REPAIR PASS (notes missing the marker) ====="
    restored="none"
    _cands=0
    while IFS= read -r _bak; do
        [ -n "${_bak}" ] || continue
        _cands=$((_cands + 1))
        set +e
        _out="$("${PY}" "${PY_SCRIPT}" --db "${DB_PATH}" --trade-ids "${TRADE_IDS}" --reason "${REASON_TEXT}" \
                --restore-notes-from "${_bak}" 2>&1)"
        _rc=$?
        set -e
        echo ">>> candidate ${_bak}: exit ${_rc}"
        echo "${_out}"
        if [ "${_rc}" -eq 0 ]; then
            if printf '%s' "${_out}" | grep -q '^restore '; then
                set +e
                "${PY}" "${PY_SCRIPT}" --db "${DB_PATH}" --trade-ids "${TRADE_IDS}" --reason "${REASON_TEXT}" \
                    --restore-notes-from "${_bak}" --apply
                exit_code=$?
                set -e
                restored="${_bak}"
            else
                restored="not needed"
            fi
            break
        fi
    done < <(ls -1t "${DB_PATH}".bak-mark-entry-unfilled-* 2>/dev/null || true)
    echo ">>> repair pass: ${restored} (${_cands} candidate backup(s))"
    if [ "${restored}" = "none" ] && [ "${_cands}" -gt 0 ]; then
        log "ERROR: every candidate backup refused the repair; see the REFUSE lines above."
        exit_code=3
    fi
fi

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
