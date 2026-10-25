#!/usr/bin/env bash
# Tier-2 system-action: provision WEB_SESSION_PEPPER on the live VM (UI-UPGRADE-1-AUTH-CONFIG).
#
# The site sign-in (src/web/api/web_sessions.py) hashes every device-session id
# with HMAC-SHA256(WEB_SESSION_PEPPER, token). Until the pepper exists the API
# answers `auth_unavailable` and no session can be issued.
#
# Dispatched by the system-actions workflow (issue body:
#   action: init-web-session-pepper
#   reason: <why>
# ). No other parameters: the key, file and service are FIXED here, so the
# issue body (untrusted input) cannot retarget the write.
#
# ⚠️ NEVER OVERWRITE. Replacing an existing pepper changes every session hash
# and signs every device out. The write happens only when the key is absent or
# empty; otherwise the action reports "already present" and restarts nothing.
#
# ⚠️ THE VALUE NEVER LEAVES THIS HOST. It is generated here (python secrets,
# 32 random bytes = 64 hex chars), written through the root-owned file's inode
# with `sudo tee` (the set_env.sh pattern: preserves owner/mode), and is never
# in argv, the issue body, the runner env, stdout, the log or the audit JSON.
# The one line reported is PEPPER=set or PEPPER=already_present.
#
# ALLOWED_EMAIL PRESENCE (item 3 of the lane): also reports whether
# ALLOWED_EMAIL is defined and non-empty in web-api.env or the repo .env (the
# two files ict-web-api.service loads). Presence only -- the address is the
# operator's and this repo is public.
#
# Exit codes: 0 success, 1 validation / write / restart failure.

set -euo pipefail

SCRIPT_NAME="init_web_session_pepper"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

require_systemctl

WEB_ENV_FILE="${WEB_API_ENV_FILE:-/etc/ict-trader/web-api.env}"
REPO_ENV_FILE="${REPO_DIR}/.env"
SERVICE="ict-web-api.service"
KEY="WEB_SESSION_PEPPER"

PRIV=()
if [ "$(id -u)" -ne 0 ]; then
    if sudo -n true 2>/dev/null; then
        PRIV=(sudo)
    else
        log "ERROR: ${WEB_ENV_FILE} is root-owned and passwordless sudo is unavailable."
        record_audit "init-web-session-pepper" "failed" '{"reason": "sudo unavailable"}' >/dev/null || true
        exit 1
    fi
fi

# Same refusal as set_env.sh: never create a root-owned credentials file.
if ! "${PRIV[@]}" test -f "${WEB_ENV_FILE}"; then
    log "ERROR: ${WEB_ENV_FILE} does not exist; refusing to create it."
    record_audit "init-web-session-pepper" "failed" '{"reason": "env_file absent"}' >/dev/null || true
    exit 1
fi

TMP_CUR="$(mktemp)"; TMP_NEW="$(mktemp)"; TMP_REPO="$(mktemp)"
chmod 600 "${TMP_CUR}" "${TMP_NEW}" "${TMP_REPO}"
trap 'rm -f "${TMP_CUR}" "${TMP_NEW}" "${TMP_REPO}"' EXIT

"${PRIV[@]}" cat "${WEB_ENV_FILE}" > "${TMP_CUR}"
cat "${REPO_ENV_FILE}" > "${TMP_REPO}" 2>/dev/null || : > "${TMP_REPO}"

# The decision + generation happen in Python so the value exists only in this
# process and the 600-mode temp file. stdout carries ONLY the two status words.
result="$(
KEY="${KEY}" CUR_FILE="${TMP_CUR}" NEW_FILE="${TMP_NEW}" REPO_FILE="${TMP_REPO}" /usr/bin/python3 - <<'PY'
import os, pathlib, secrets


def value_of(text: str, key: str) -> str:
    """Last non-comment KEY=VALUE for key (systemd: last assignment wins)."""
    val = ""
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export "):].lstrip()
        k, sep, v = s.partition("=")
        if sep and k.strip() == key:
            val = v.strip().strip("'\"").strip()
    return val


key = os.environ["KEY"]
cur = pathlib.Path(os.environ["CUR_FILE"]).read_text()
repo = pathlib.Path(os.environ["REPO_FILE"]).read_text()
email = "present" if (value_of(cur, "ALLOWED_EMAIL") or value_of(repo, "ALLOWED_EMAIL")) else "absent"

if value_of(cur, key):
    state = "already_present"
else:
    lines = [ln for ln in cur.splitlines()
             if ln.strip().removeprefix("export ").lstrip().split("=", 1)[0].strip() != key
             or ln.lstrip().startswith("#")]
    lines.append(f"{key}={secrets.token_hex(32)}")
    pathlib.Path(os.environ["NEW_FILE"]).write_text("\n".join(lines) + "\n")
    state = "set"
print(f"{state} {email}")
PY
)"
state="${result% *}"
email="${result#* }"

if [ "${state}" = "set" ]; then
    # tee writes THROUGH the existing inode: owner/mode of the root-owned file kept.
    "${PRIV[@]}" tee "${WEB_ENV_FILE}" < "${TMP_NEW}" >/dev/null
    if ! "${PRIV[@]}" grep -qE "^${KEY}=.+" "${WEB_ENV_FILE}"; then
        log "ERROR: post-write read-back for ${KEY} failed."
        record_audit "init-web-session-pepper" "failed" '{"reason": "readback failed"}' >/dev/null || true
        exit 1
    fi
fi

echo "PEPPER=${state}"
echo "ALLOWED_EMAIL=${email}"

if [ "${state}" = "already_present" ]; then
    log "${KEY} already present; nothing written, ${SERVICE} not restarted."
    record_audit "init-web-session-pepper" "ok" \
        "{\"pepper\": \"already_present\", \"allowed_email\": \"${email}\"}" >/dev/null || true
    exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
    SYSTEMCTL=(systemctl)
elif sudo -n systemctl --version >/dev/null 2>&1; then
    SYSTEMCTL=(sudo systemctl)
else
    log "ERROR: passwordless sudo for systemctl is required."
    record_audit "init-web-session-pepper" "failed" '{"reason": "sudo unavailable for systemctl"}' >/dev/null || true
    exit 1
fi

log "Restarting ${SERVICE} to pick up ${KEY}..."
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
    record_audit "init-web-session-pepper" "ok" \
        "{\"pepper\": \"set\", \"allowed_email\": \"${email}\", \"unit\": \"active\"}" >/dev/null || true
    exit 0
fi
record_audit "init-web-session-pepper" "failed" \
    "{\"pepper\": \"set\", \"unit\": \"${post_state}\"}" >/dev/null || true
log "ERROR: ${SERVICE} did not return to 'active' within 30 s."
exit 1
