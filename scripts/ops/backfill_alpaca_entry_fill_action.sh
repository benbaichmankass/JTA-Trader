#!/usr/bin/env bash
# Tier-2 operator action: correct trades.entry_price on Alpaca rows whose entry filled AFTER the
# placement's 3 s confirm poll and so kept the package signal price (ALPACA-ENTRY-FILL-PRICE-UNSYNCED,
# 2026-11-26; measured 15 of 65 Alpaca stock entries 11-09..11-25, net +1,471.86 USD journal-minus-venue).
#
# Wraps scripts/ops/backfill_alpaca_entry_fill.py. Reads each candidate's entry order by id from Alpaca
# (read-only GET /v2/orders/{id}) and, on --apply, sets entry_price to the order's filled_avg_price
# (package price kept in notes.package_entry), shifts a closed row's pnl by the same linear delta
# (notes.pnl_prior keeps the old figure) and clears pnl_basis/pnl_computed/pnl_gap_usd for the monitor's
# venue sweep to re-classify. NEVER places/amends/cancels an order, touches SL/TP/size/status, or
# restarts a service. Idempotent (corrected rows are labelled alpaca_order_status and skipped).
#
# Two invocations in one run for a self-documenting audit trail:
#   1. dry-run (always) -> prints every row it would change (old vs venue entry, pnl delta), no write.
#   2. --apply          -> commits the UPDATEs, ONLY when the issue body says `apply: true`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

# Alpaca credentials, loaded exactly as rearm_alpaca_protective_action.sh does (2026-11-26 fix): without this the
# per-id order reads ran with missing or default (paper) keys, so the 2026-11-26 16:08Z dry run (issue #29223) read
# 81 live/portfolio orders as 404 'not found' and 56 as could_not_look, and proposed 0 writes against the 12 the
# #29165 table measured through the web API (which runs with these creds). Never echoes a value.
cd "${REPO_DIR}"
load_runtime_secrets

# The working Alpaca creds are the ones the ict-web-api service authenticates
# with — it loads the root-owned /etc/ict-trader/web-api.env EnvironmentFile in
# addition to repo .env. The repo .env copy (synced from Actions secrets by
# sync-vm-secrets) can be empty/stale for the ALPACA_*_LIVE pair, which makes
# alpaca_client_for() return None → "could not read the live Alpaca position".
# So prefer web-api.env's known-good ALPACA_* values (sudo-read, mirroring the
# prop-report.yml pattern). Non-secret presence diagnostic only — never echoes
# a value. Override only when web-api.env carries a non-empty value.
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
  echo ">>> creds: web-api.env not sudo-readable — using repo .env creds only"
fi

DB_PATH="$(runtime_db_path)"
PY_SCRIPT="${REPO_DIR}/scripts/ops/backfill_alpaca_entry_fill.py"

if [ ! -f "${PY_SCRIPT}" ]; then
    log "ERROR: backfill helper not present at ${PY_SCRIPT}. Did the VM pull the latest main?"
    record_audit "backfill-alpaca-entry-fill" "error" \
        "{\"reason\": \"helper missing\", \"path\": \"${PY_SCRIPT}\"}" >/dev/null || true
    exit 1
fi

if [ ! -f "${DB_PATH}" ]; then
    log "ERROR: trade_journal.db not present at ${DB_PATH}."
    record_audit "backfill-alpaca-entry-fill" "error" \
        "{\"reason\": \"db missing\", \"path\": \"${DB_PATH}\"}" >/dev/null || true
    exit 1
fi

echo
echo "===== backfill_alpaca_entry_fill.py (DRY-RUN preview) ====="
set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}"
dry_code=$?
set -e
if [ "${dry_code}" -ne 0 ]; then
    log "ERROR: dry-run preview exited ${dry_code} — NOT applying."
    record_audit "backfill-alpaca-entry-fill" "failed" \
        "{\"phase\": \"dry-run\", \"exit_code\": ${dry_code}}" >/dev/null || true
    exit "${dry_code}"
fi

# apply is an explicit opt-in (issue body `apply: true`), the same gate as the sibling money-DB wrappers
# (rebuild-pnl-from-bybit, backfill-monitor-closed-pnl; FIX-CA-14). Without it this run is the dry-run
# above and nothing is written, so the row list can be checked before the write (manager 26a, 2026-11-26).
case "${ACTION_APPLY:-}" in
    true|True) ;;
    *)
        log "DRY-RUN only (no 'apply: true' in the issue body): nothing written."
        record_audit "backfill-alpaca-entry-fill" "ok" "{\"db\": \"${DB_PATH}\", \"phase\": \"dry-run\"}" >/dev/null || true
        exit 0
        ;;
esac

echo
echo "===== backfill_alpaca_entry_fill.py --apply (COMMIT) ====="
set +e
python3 "${PY_SCRIPT}" --db "${DB_PATH}" --apply
apply_code=$?
set -e
if [ "${apply_code}" -ne 0 ]; then
    log "ERROR: apply exited ${apply_code}."
    record_audit "backfill-alpaca-entry-fill" "failed" \
        "{\"phase\": \"apply\", \"exit_code\": ${apply_code}}" >/dev/null || true
    exit "${apply_code}"
fi

record_audit "backfill-alpaca-entry-fill" "ok" "{\"db\": \"${DB_PATH}\"}" >/dev/null || true
log "backfill-alpaca-entry-fill complete."
