#!/usr/bin/env bash
# system-action wrapper (Tier 2): cap VM log growth. target: journald | runtime_logs. DRY-RUN unless apply: true.
#
# PI-20261017-VMDGITZI-0002 follow-up (OPERATOR-DECISIONS-20261028 item 6): runtime_logs was 11 GB and journald
# 4.1 GB on a 45 G root disk.
#   runtime_logs - scripts/ops/cap_runtime_logs.py: stale ROTATED log files only (see its docstring); prints the
#                  per-directory breakdown first. No sudo.
#   journald     - needs a ONE-TIME sudoers entry (the existing NOPASSWD covers systemctl only, not journalctl or a
#                  write under /etc). Without it this exits 4 and prints the exact line. With it: writes
#                  /etc/systemd/journald.conf.d/90-ict-cap.conf (SystemMaxUse=1G, MaxRetentionSec=14day), vacuums to
#                  1G, restarts systemd-journald.
# Env: ACTION_TARGET, ACTION_APPLY, ACTION_DAYS (runtime_logs retention, default 30).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

TARGET="${ACTION_TARGET:-}"
APPLY="${ACTION_APPLY:-}"
DAYS="${ACTION_DAYS:-30}"
case "${DAYS}" in ''|*[!0-9]*) echo "ERROR: days must be a whole number (got '${DAYS}')"; exit 2 ;; esac
CONF_DIR=/etc/systemd/journald.conf.d
CONF=${CONF_DIR}/90-ict-cap.conf
CONF_BODY=$'[Journal]\nSystemMaxUse=1G\nMaxRetentionSec=14day\n'

echo ">>> before"; df -h / || true
case "${TARGET}" in
    runtime_logs)
        ARGS=(--days "${DAYS}"); [ "${APPLY}" = "true" ] && ARGS+=(--apply)
        python3 "${REPO_DIR}/scripts/ops/cap_runtime_logs.py" "${ARGS[@]}"
        ;;
    journald)
        journalctl --disk-usage 2>/dev/null || echo "(journalctl --disk-usage unavailable)"
        echo "planned: write ${CONF} =>"; printf '%s' "${CONF_BODY}"
        echo "planned: journalctl --vacuum-size=1G ; systemctl restart systemd-journald"
        if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing changed. Re-dispatch with apply: true."; exit 0; fi
        if ! sudo -n -l /usr/bin/journalctl >/dev/null 2>&1 || ! sudo -n -l /usr/bin/tee "${CONF}" >/dev/null 2>&1; then
            echo "ERROR: passwordless sudo for journalctl/tee is not granted (only systemctl is). One-time operator step,"
            echo "       /etc/sudoers.d/ict-system-actions (0440 root:root), validate with 'visudo -c':"
            echo "         ubuntu ALL=(ALL) NOPASSWD: /usr/bin/journalctl --vacuum-size=*, /usr/bin/tee ${CONF}, /usr/bin/mkdir -p ${CONF_DIR}"
            record_audit "cap-vm-logs" "error" '{"reason": "journald sudoers entry missing"}' >/dev/null || true
            exit 4
        fi
        sudo -n /usr/bin/mkdir -p "${CONF_DIR}"
        printf '%s' "${CONF_BODY}" | sudo -n /usr/bin/tee "${CONF}" >/dev/null
        sudo -n /usr/bin/journalctl --vacuum-size=1G
        sudo -n systemctl restart systemd-journald
        ;;
    *) echo "ERROR: target must be journald or runtime_logs (got '${TARGET}')"; exit 2 ;;
esac
echo ">>> after"; df -h / || true
record_audit "cap-vm-logs" "ok" "{\"target\": \"${TARGET}\", \"apply\": \"${APPLY:-false}\"}" >/dev/null || true
