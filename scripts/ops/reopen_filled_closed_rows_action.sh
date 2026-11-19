#!/usr/bin/env bash
# Tier-2 operator action: reopen-filled-closed-rows (spec-driven).
# Wraps scripts/ops/reopen_filled_closed_rows.py: re-opens journal rows that were closed before their bracket
# entries filled at the venue, per the COMMITTED spec comms/ops/reopen_specs/<account>__<SYMBOL>.json, chosen
# by the issue body's `account:` + `symbol:` (ACCOUNT_ID / ACTION_SYMBOL). PI-20261118-JFWRQYOV-0004.
# Dry-run unless apply: true. Each spec's apply needs its own manager OK on the dry-run diff.
# ⚠️ IT PLACES, MODIFIES AND CANCELS NOTHING at any venue: journal/state repair only.
# The venue evidence (positions + order history) is captured HERE, inside the run, so it is fresh by construction.
set -euo pipefail

SCRIPT_NAME="reopen_filled_closed_rows"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"

ACTION_SLUG="reopen-filled-closed-rows"
BASE="http://127.0.0.1:8001/api/diag"
SYSTEM_ENV="/etc/ict-trader/web-api.env"
DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/reopen_filled_closed_rows.py"
ACCT="${ACCOUNT_ID:-}"
SYM="${ACTION_SYMBOL:-}"
if ! printf '%s' "${ACCT}" | grep -Eq '^[a-z0-9_]+$' || ! printf '%s' "${SYM}" | grep -Eq '^[A-Za-z0-9]+$'; then
    log "ERROR: account '${ACCT}' / symbol '${SYM}' missing or invalid (issue body: 'account: <id>' + 'symbol: <SYM>')."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"bad account/symbol\"}" >/dev/null || true
    exit 2
fi

for f in "${PY_SCRIPT}" "${DB_PATH}"; do
    if [ ! -f "${f}" ]; then
        log "ERROR: ${f} not present."
        record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"missing\", \"path\": \"${f}\"}" >/dev/null || true
        exit 1
    fi
done

DIAG_TOKEN=""
for candidate in "${SYSTEM_ENV}" "${REPO_DIR}/.env"; do
    if [ -z "${DIAG_TOKEN}" ] && [ -f "${candidate}" ]; then
        DIAG_TOKEN="$(grep -m1 '^DIAG_READ_TOKEN=' "${candidate}" 2>/dev/null | cut -d= -f2- || true)"
    fi
done
if [ -z "${DIAG_TOKEN}" ]; then
    log "ERROR: DIAG_READ_TOKEN not found; the venue evidence cannot be captured, so this action REFUSES."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"diag token unresolved\"}" >/dev/null || true
    exit 1
fi

POS_JSON="$(mktemp -t reopen_pos.XXXXXX.json)"
HIST_JSON="$(mktemp -t reopen_hist.XXXXXX.json)"
cleanup() { rm -f "${POS_JSON}" "${HIST_JSON}"; }
trap cleanup EXIT

capture() {   # $1 = url, $2 = out file; header via stdin, never in argv / ps
    local code rc
    set +e
    code="$(curl -sS --max-time 60 -o "$2" -w '%{http_code}' -H @- "$1" <<<"Authorization: Bearer ${DIAG_TOKEN}")"
    rc=$?
    set -e
    if [ "${rc}" -ne 0 ] || [ "${code}" != "200" ]; then
        log "ERROR: capture of $1 FAILED (curl_rc=${rc} http=${code:-none}); nothing was written."
        record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"venue capture failed\"}" >/dev/null || true
        exit 1
    fi
}
# The spec decides which orders are evidence: look each one up by id (exact; a list page can miss them).
set +e
IDS="$(python3 "${PY_SCRIPT}" --db "${DB_PATH}" --account "${ACCT}" --symbol "${SYM}" --print-lookup)"
rc=$?
set -e
if [ "${rc}" -ne 0 ] || ! printf '%s' "${IDS}" | grep -Eq '^[A-Za-z0-9,-]+$'; then
    echo "${IDS}"
    log "ERROR: no valid spec for ${ACCT} ${SYM} (rc=${rc}); nothing was written."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"spec\"}" >/dev/null || true
    exit 3
fi
capture "${BASE}/exchange_positions?account_id=${ACCT}" "${POS_JSON}"
capture "${BASE}/alpaca_order_history?account_id=${ACCT}&order_ids=${IDS}" "${HIST_JSON}"

APPLY_FLAG=""
case "${ACTION_APPLY:-}" in
    true|True) APPLY_FLAG="--apply" ;;
    *)         APPLY_FLAG="" ;;
esac
echo "===== reopen_filled_closed_rows.py ${ACCT} ${SYM} ${APPLY_FLAG:-(dry run)} ====="
set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}" --account "${ACCT}" --symbol "${SYM}" --order-history "${HIST_JSON}" --positions "${POS_JSON}" ${APPLY_FLAG}
exit_code=$?
set -e
if [ "${exit_code}" -ne 0 ]; then
    record_audit "${ACTION_SLUG}" "failed" "{\"apply\": \"${ACTION_APPLY:-}\", \"exit_code\": ${exit_code}}" >/dev/null || true
    exit "${exit_code}"
fi
record_audit "${ACTION_SLUG}" "ok" "{\"apply\": \"${ACTION_APPLY:-}\", \"account\": \"${ACCT}\", \"symbol\": \"${SYM}\"}" >/dev/null || true
