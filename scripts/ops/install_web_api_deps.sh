#!/usr/bin/env bash
# Tier-2 system-action: install the web-auth Python deps into the interpreter
# ict-web-api.service ACTUALLY runs (UI-UPGRADE-1-AUTH).
#
# Why this exists (2026-10-12): POST /api/auth/passkey/register/begin 500'd
# with `ModuleNotFoundError: No module named 'webauthn'` — the traceback's
# site-packages is the repo .venv, while scripts/deploy_pull_restart.sh runs
# `/usr/bin/python3 -m pip install -r requirements.txt`, so a requirement added
# to requirements.txt never reached the web-api's environment.
#
# Dispatched by the system-actions workflow (issue body:
#   action: install-web-api-deps
#   reason: <why>
# ). No parameters: the package list is FIXED here and each spec is read from
# requirements.txt, so the issue body (untrusted) cannot choose what installs.
#
# The interpreter is resolved from the running unit's MainPID (/proc/<pid>/exe),
# falling back to ${REPO_DIR}/.venv/bin/python. Only the named packages are
# installed (no blanket `-r requirements.txt`, which could upgrade packages the
# trader shares). Then the import is verified and ict-web-api is restarted.
#
# Exit codes: 0 success, 1 failure.

set -euo pipefail

SCRIPT_NAME="install_web_api_deps"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

require_systemctl

SERVICE="ict-web-api.service"
# package-name (as in requirements.txt) : import-name
PACKAGES=("webauthn:webauthn")

if [ "$(id -u)" -eq 0 ]; then
    SYSTEMCTL=(systemctl)
elif sudo -n systemctl --version >/dev/null 2>&1; then
    SYSTEMCTL=(sudo systemctl)
else
    log "ERROR: passwordless sudo for systemctl is required."
    record_audit "install-web-api-deps" "failed" '{"reason": "sudo unavailable for systemctl"}' >/dev/null || true
    exit 1
fi

# Which environment does the running process import from? A venv's python is
# usually a symlink to the system binary, so /proc/<pid>/exe alone loses the
# venv; the process's mapped files (site-packages .so) say which one it is.
VENV_PY="${REPO_DIR}/.venv/bin/python"
pid="$("${SYSTEMCTL[@]}" show -p MainPID --value "${SERVICE}" 2>/dev/null || echo 0)"
PY=""
if [ -n "${pid}" ] && [ "${pid}" != "0" ]; then
    if sudo -n grep -q "${REPO_DIR}/.venv/lib" "/proc/${pid}/maps" 2>/dev/null; then
        PY="${VENV_PY}"
    else
        PY="$(sudo -n readlink -f "/proc/${pid}/exe" 2>/dev/null || true)"
    fi
fi
if [ -z "${PY}" ] || [ ! -x "${PY}" ]; then
    PY="${VENV_PY}"
fi
log "web-api interpreter: ${PY}"

specs=()
for entry in "${PACKAGES[@]}"; do
    name="${entry%%:*}"
    spec="$(grep -E "^[[:space:]]*${name}([<>=!~ ;\[]|$)" "${REPO_DIR}/requirements.txt" | head -1 | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || true)"
    if [ -z "${spec}" ]; then
        log "ERROR: ${name} not found in requirements.txt; refusing to install an undeclared package."
        record_audit "install-web-api-deps" "failed" "{\"reason\": \"${name} not in requirements.txt\"}" >/dev/null || true
        exit 1
    fi
    specs+=("${spec}")
done

log "Installing into ${PY}: ${specs[*]}"
"${PY}" -m pip install --quiet "${specs[@]}"

for entry in "${PACKAGES[@]}"; do
    mod="${entry##*:}"
    if ! "${PY}" -c "import ${mod}; print('${mod}', getattr(${mod}, '__version__', '?'))"; then
        log "ERROR: ${mod} still not importable from ${PY}."
        record_audit "install-web-api-deps" "failed" "{\"reason\": \"${mod} import failed\"}" >/dev/null || true
        exit 1
    fi
done

log "Restarting ${SERVICE}..."
"${SYSTEMCTL[@]}" restart "${SERVICE}"
post_state="unknown"
deadline=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "${deadline}" ]; do
    post_state="$("${SYSTEMCTL[@]}" is-active "${SERVICE}" 2>/dev/null || echo "unknown")"
    [ "${post_state}" = "active" ] && break
    sleep 2
done
log "Post-restart ${SERVICE} state: ${post_state}"
if [ "${post_state}" = "active" ]; then
    record_audit "install-web-api-deps" "ok" "{\"interpreter\": \"${PY}\", \"unit\": \"active\"}" >/dev/null || true
    exit 0
fi
record_audit "install-web-api-deps" "failed" "{\"unit\": \"${post_state}\"}" >/dev/null || true
log "ERROR: ${SERVICE} did not return to 'active' within 30 s."
exit 1
