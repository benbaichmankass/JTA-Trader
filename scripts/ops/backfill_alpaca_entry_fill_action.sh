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
#   1. dry-run (default) -> prints every row it would change (old vs venue entry, pnl delta), no write.
#   2. --apply           -> commits the UPDATEs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

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
