#!/usr/bin/env bash
# Tier-2 operator action (GLD-ORPHAN-5209, 2026-11-01): re-link orphan-adopted trade 5209 to its true
# package pkg-8106d5eef6fc425c, reopen that package and close the mis-attributed pkg-6a8e3fb325464be3.
# Wraps scripts/ops/relink_orphan_trade_5209.py. DRY-RUN by default; `apply: true` writes.
# Journal only: places, modifies and cancels NOTHING at the venue. The venue evidence is captured FRESH in
# this run from the VM's own /api/diag/alpaca_open_orders; a failed capture ABORTS (could not look is never
# "nothing to do"). No service restart.
set -euo pipefail

SCRIPT_NAME="relink_orphan_trade_5209"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

ACTION_SLUG="relink-orphan-trade-5209"
DIAG_URL="http://127.0.0.1:8001/api/diag/alpaca_open_orders"
SYSTEM_ENV="/etc/ict-trader/web-api.env"
DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/relink_orphan_trade_5209.py"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: helper not present at ${PY_SCRIPT}. Did the VM pull the latest main?"
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"helper missing\"}" >/dev/null || true
    exit 1
fi
if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"db missing\"}" >/dev/null || true
    exit 1
fi

DIAG_TOKEN=""
for candidate in "${SYSTEM_ENV}" "${REPO_DIR}/.env"; do
    if [ -z "${DIAG_TOKEN}" ] && [ -f "${candidate}" ]; then
        DIAG_TOKEN="$(grep -m1 '^DIAG_READ_TOKEN=' "${candidate}" 2>/dev/null | cut -d= -f2- || true)"
    fi
done
if [ -z "${DIAG_TOKEN}" ]; then
    log "ERROR: DIAG_READ_TOKEN not found; the venue evidence cannot be captured. Nothing written."
    record_audit "${ACTION_SLUG}" "error" "{\"reason\": \"diag token unresolved\"}" >/dev/null || true
    exit 1
fi

VENUE_JSON="$(mktemp -t relink5209_venue.XXXXXX.json)"
trap 'rm -f "${VENUE_JSON}"' EXIT
set +e
http_code="$(curl -sS --max-time 60 -o "${VENUE_JSON}" -w '%{http_code}' \
    -H "Authorization: Bearer ${DIAG_TOKEN}" "${DIAG_URL}")"
curl_rc=$?
set -e
if [ "${curl_rc}" -ne 0 ] || [ "${http_code}" != "200" ]; then
    log "ERROR: venue capture FAILED (curl_rc=${curl_rc} http=${http_code:-none}). Nothing written: could not look."
    record_audit "${ACTION_SLUG}" "error" \
        "{\"reason\": \"venue capture failed\", \"curl_rc\": ${curl_rc}, \"http\": \"${http_code:-none}\"}" >/dev/null || true
    exit 1
fi

APPLY_FLAG=""
case "${ACTION_APPLY:-}" in
    true|True) APPLY_FLAG="--apply" ;;
esac
if [ -n "${APPLY_FLAG}" ]; then
    log "Running ${SCRIPT_NAME}.py --apply (Tier-2 journal write) on ${DB_PATH} ..."
else
    log "Running ${SCRIPT_NAME}.py DRY RUN (pass apply: true to write) on ${DB_PATH} ..."
fi

set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}" --venue "${VENUE_JSON}" --reason "${ACTION_REASON:-}" ${APPLY_FLAG}
exit_code=$?
set -e
if [ "${exit_code}" -ne 0 ]; then
    record_audit "${ACTION_SLUG}" "failed" \
        "{\"apply\": \"${ACTION_APPLY:-}\", \"exit_code\": ${exit_code}}" >/dev/null || true
    log "ERROR: helper exited ${exit_code} (2 = refused, 1 = lost race / rolled back)."
    exit "${exit_code}"
fi
record_audit "${ACTION_SLUG}" "ok" "{\"apply\": \"${ACTION_APPLY:-}\"}" >/dev/null || true
log "${ACTION_SLUG} complete (apply=${ACTION_APPLY:-false}). Verify independently via /api/diag/journal?table=order_packages and ?table=trades."
exit 0
