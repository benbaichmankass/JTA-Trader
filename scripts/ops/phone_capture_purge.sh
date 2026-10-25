#!/usr/bin/env bash
# Daily purge of phone step captures older than 7 days (PHONE-EXEC-OBSERVABLE-1018;
# operator decision 2026-10-18: captures live on the server only, auto-deleted after 7 days).
#
# Fired by deploy/ict-phone-capture-purge.timer. Resolves DATA_DIR / TRADE_JOURNAL_DB the way
# the trader does (scripts/ops/_lib.sh load_runtime_env: systemctl unit > .env > drop-in), so
# the purge walks <trade_journal.db dir>/phone_captures on the data volume and never a
# repo-relative fallback. Read-only on everything but the capture run directories.
# The same purge also runs on every capture the phone posts (at most hourly); this is the
# second path, for a phone that went quiet.

set -euo pipefail

SCRIPT_NAME="phone_capture_purge"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

load_runtime_env

PURGE="${REPO_DIR}/scripts/prop/phone_capture_purge.py"
if [ ! -f "${PURGE}" ]; then
    log "ERROR: ${PURGE} not found."
    exit 1
fi
log "phone capture purge: removing runs older than 7 days"
cd "${REPO_DIR}" && /usr/bin/python3 "${PURGE}"
