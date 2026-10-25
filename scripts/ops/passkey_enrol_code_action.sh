#!/usr/bin/env bash
# Tier-1 system-action: mint a one-time passkey enrolment code and ping it to the
# private SYSTEM Telegram chat (UI-UPGRADE-1-AUTH-CONFIG, design §2a).
#
# Dispatched by the system-actions workflow (issue body: `action: passkey-enrol-code`).
# No parameters. The code is single-use and valid 15 min, so dispatch it only when
# the operator is ready to sign in.
#
# ⚠️ THE CODE IS DELIVERED ONLY BY THE PING. This wrapper's output goes to a
# public issue comment, so nothing here (or in passkey_enrol_code.py) prints it.
#
# The mint must use the SAME database and pepper as ict-web-api.service, so the
# environment is assembled the way the unit's is: runtime paths via
# load_runtime_env, then WEB_SESSION_PEPPER (and DATA_DIR / TRADE_JOURNAL_DB if
# set there) from the root-owned web-api.env. Values are exported, never echoed.
#
# Exit codes: 0 sent, 1 failure, 2 pepper not configured.

set -euo pipefail

SCRIPT_NAME="passkey_enrol_code_action"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

load_runtime_env

WEB_ENV_FILE="${WEB_API_ENV_FILE:-/etc/ict-trader/web-api.env}"
PRIV=()
[ "$(id -u)" -ne 0 ] && PRIV=(sudo)

for _k in WEB_SESSION_PEPPER DATA_DIR TRADE_JOURNAL_DB; do
    _v="$("${PRIV[@]}" grep -E "^${_k}=" "${WEB_ENV_FILE}" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    _v="${_v%\"}"; _v="${_v#\"}"; _v="${_v%\'}"; _v="${_v#\'}"
    [ -n "${_v}" ] && export "${_k}=${_v}"
    unset _v
done

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="/usr/bin/python3"

set +e
OUT="$("${PY}" "${SCRIPT_DIR}/passkey_enrol_code.py" 2>&1)"
RC=$?
set -e
echo "${OUT}"

if [ "${RC}" -eq 0 ]; then
    record_audit "passkey-enrol-code" "ok" '{"delivery": "system-ping"}' >/dev/null || true
else
    record_audit "passkey-enrol-code" "failed" "{\"exit\": ${RC}}" >/dev/null || true
fi
exit "${RC}"
