#!/usr/bin/env bash
# wiring: called best-effort by scripts/deploy_pull_restart.sh on every deploy (ict-git-sync), and runnable by hand
# or through the ops channel's exec. Idempotent: a VM that already matches is a no-op that changes nothing.
#
# VM-CHANGE-LEDGER fold-back of ops job OPS-20261112T204454Z-exec-e9f0f4 (row HEALTH-20261112-LIVE-DISK-OTHER-GROWERS):
# /var/log/syslog grew to ~1 GB/week on the live VM. The cap: daily, maxsize 200M, rotate 7, compressed, in its own
# file /etc/logrotate.d/ict-syslog-cap, and the /var/log/syslog line removed from the distro's
# /etc/logrotate.d/rsyslog (logrotate refuses a file listed twice). A rebuilt VM converges on the next deploy.
#
# Revert: sudo rm /etc/logrotate.d/ict-syslog-cap; sudo cp -a <the newest /var/backups/logrotate.rsyslog.ict-*>
#         /etc/logrotate.d/rsyslog  (and delete deploy/logrotate/ict-syslog-cap so the next deploy does not re-add it)
#
# Exit 0 on success or no-op; 1 when the result does not validate (the previous files are restored).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC="${REPO_DIR}/deploy/logrotate/ict-syslog-cap"
DEST="${SYSLOG_CAP_DEST:-/etc/logrotate.d/ict-syslog-cap}"
DISTRO="${SYSLOG_CAP_DISTRO:-/etc/logrotate.d/rsyslog}"
BACKUP_DIR="${SYSLOG_CAP_BACKUP_DIR:-/var/backups}"
SUDO=()
[ "$(id -u)" -eq 0 ] || SUDO=(sudo -n)
[ -n "${SYSLOG_CAP_NO_SUDO:-}" ] && SUDO=()

[ -f "${SRC}" ] || { echo "install_syslog_cap: ${SRC} missing" >&2; exit 1; }
[ -f "${DISTRO}" ] || [ -f "${DEST}" ] || { echo "install_syslog_cap: no logrotate config here (not the VM?) — skipping"; exit 0; }

listed_in_distro=0
if [ -f "${DISTRO}" ] && grep -qx '/var/log/syslog' "${DISTRO}"; then listed_in_distro=1; fi
if [ -f "${DEST}" ] && cmp -s "${SRC}" "${DEST}" && [ "${listed_in_distro}" -eq 0 ]; then
    echo "install_syslog_cap: already in place (no-op)"
    exit 0
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [ "${listed_in_distro}" -eq 1 ]; then
    "${SUDO[@]}" cp -a "${DISTRO}" "${BACKUP_DIR}/logrotate.rsyslog.ict-${stamp}"
    "${SUDO[@]}" sed -i '\#^/var/log/syslog$#d' "${DISTRO}"
fi
prev_dest=""
if [ -f "${DEST}" ]; then
    prev_dest="${BACKUP_DIR}/logrotate.ict-syslog-cap.${stamp}"
    "${SUDO[@]}" cp -a "${DEST}" "${prev_dest}"
fi
"${SUDO[@]}" install -m 0644 "${SRC}" "${DEST}"

if command -v logrotate >/dev/null 2>&1 && [ -z "${SYSLOG_CAP_SKIP_VALIDATE:-}" ]; then
    if "${SUDO[@]}" logrotate -d /etc/logrotate.conf 2>&1 | grep -iE '^error|duplicate log entry' >/dev/null; then
        echo "install_syslog_cap: logrotate -d reports an error after install — restoring" >&2
        if [ "${listed_in_distro}" -eq 1 ]; then
            "${SUDO[@]}" cp -a "${BACKUP_DIR}/logrotate.rsyslog.ict-${stamp}" "${DISTRO}"
        fi
        if [ -n "${prev_dest}" ]; then "${SUDO[@]}" cp -a "${prev_dest}" "${DEST}"; else "${SUDO[@]}" rm -f "${DEST}"; fi
        exit 1
    fi
fi
echo "install_syslog_cap: installed ${DEST} (distro entry removed: ${listed_in_distro})"
