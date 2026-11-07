#!/usr/bin/env bash
# Tier-2 system-action: delete NAMED phone capture runs of ONE account (operator decision
# 2026-11-07, "Delete them": stored images that showed an unmasked amount, before exec.js .5).
#
# Deletes only <phone_captures root>/<account>/<run_id>/ directories -- never anything else,
# never a run you did not name, never the TTL logic. DRY-RUN by default (lists what would go).
#   action: purge-phone-captures
#   account: breakout_2                     (required)
#   ids: periodic-terminal-2026...Z,...     (required, comma-separated run ids)
#   apply: true                             (default dry-run)
# Verify: GET /api/diag/phone_captures?account_id=<acct> (the runs are gone).
# Exit codes: 0 = done (or dry-run listed), 1 = refused or failed.

set -euo pipefail

SCRIPT_NAME="purge_phone_captures_action"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
load_runtime_env

ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required (issue body: account: <phone_accounts key>)}"
RUN_IDS="${ACTION_IDS:?ids required (issue body: ids: <run_id>,<run_id>)}"
APPLY="${ACTION_APPLY:-false}"
FLAG=()
if [ "${APPLY}" = "true" ]; then FLAG=(--apply); fi

log "purge-phone-captures account=${ACCOUNT_ID} apply=${APPLY}"
if OUT="$(cd "${REPO_DIR}" && /usr/bin/python3 -c '
import json, sys
from src.prop import phone_captures as pc
apply = "--apply" in sys.argv[3:]
print(json.dumps(pc.purge_runs(sys.argv[1], sys.argv[2].split(","), apply=apply)))
' "${ACCOUNT_ID}" "${RUN_IDS}" ${FLAG[@]+"${FLAG[@]}"})"; then
    printf '%s\n' "${OUT}"
    record_audit "purge-phone-captures" "ok" "${OUT}" >/dev/null || true
    exit 0
else
    printf '%s\n' "${OUT:-}"
    record_audit "purge-phone-captures" "failed" '{"reason": "purge_runs raised"}' >/dev/null || true
    log "ERROR: purge failed (see output)."
    exit 1
fi
