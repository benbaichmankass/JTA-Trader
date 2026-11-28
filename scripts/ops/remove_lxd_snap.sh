#!/usr/bin/env bash
# Tier-2 operator action: remove the UNUSED lxd snap from the live VM (ict-bot-arm), and nothing else.
#
# WHY (2026-11-28): the lxd snap on ict-bot-arm was never initialised and runs no container (snap-units-report run
# 46133194205: lxd.daemon / activate / user-daemon inactive, only the two unix sockets listening; the `lxc list`
# first-run hint). Its snapd auto-refresh at 09:34-09:35Z rewrote six unit files and tripped six security alerts
# (benign, issues #29740 / #29749). The operator approved removal, popup ~10:25Z, verbatim
# "Remove the LXD snap now (Recommended)" (Tier 2). A removed snap also stops lxd's refreshes and its
# snap.lxd.* / snap-lxd-*.mount unit churn.
#
# What it does: (1) refuses (exit 1, changes nothing) if ANY lxd container or VM exists; (2) `snap remove --purge lxd`
# (every revision, data purged, no snapshot); (3) prints the post-state and exits non-zero if lxd is still present,
# a snap.lxd.* unit file or listening socket remains, or the trader / web-api is not active afterwards.
# Idempotent: lxd already absent = no-op success. It touches NO other snap, unit, file or service, and never
# restarts the trader or web-api.
#
# The security watcher WILL flag the removed unit files (ours: record it as this action's own change).

set -euo pipefail

SCRIPT_NAME="remove_lxd_snap"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif sudo -n true >/dev/null 2>&1; then
    SUDO=(sudo -n)
else
    log "ERROR: passwordless sudo is required to remove a snap."
    record_audit "remove-lxd-snap" "error" '{"reason": "sudo unavailable"}' >/dev/null || true
    exit 1
fi

if ! command -v snap >/dev/null 2>&1; then
    log "Nothing to remove: 'snap' is not installed on this host. (no-op success)"
    record_audit "remove-lxd-snap" "noop" '{"reason": "snap not installed"}' >/dev/null || true
    exit 0
fi

t() { timeout 30 "$@" 2>&1 || echo "(could_not_look: '$*' rc=$?)"; }

echo "----- pre-state -----"
t snap list --all lxd
if ! snap list lxd >/dev/null 2>&1; then
    log "Nothing to remove: the lxd snap is not installed. (no-op success)"
    record_audit "remove-lxd-snap" "noop" '{"reason": "lxd snap not installed"}' >/dev/null || true
    exit 0
fi

# 1. Refuse if lxd holds a container or VM. Directory listing only: NEVER `lxc list`, which socket-activates the daemon.
containers=0
for d in /var/snap/lxd/common/lxd/containers /var/snap/lxd/common/lxd/virtual-machines; do
    if [ -d "${d}" ]; then
        n="$("${SUDO[@]}" find "${d}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
        echo "entries in ${d}: ${n}"
        containers=$((containers + n))
    else
        echo "entries in ${d}: (directory absent)"
    fi
done
if [ "${containers}" -gt 0 ]; then
    log "REFUSED: lxd has ${containers} container/VM entr(y/ies); removing it would destroy them. Nothing changed."
    record_audit "remove-lxd-snap" "error" "{\"reason\": \"lxd has ${containers} container or VM entries\"}" >/dev/null || true
    exit 1
fi

# 2. Remove every revision and purge its data.
log "Running: snap remove --purge lxd"
"${SUDO[@]}" timeout 300 snap remove --purge lxd 2>&1 | sed 's/^/  /' || {
    log "snap remove returned nonzero; reading the post-state anyway."
}

# 3. Post-state: report, then verify.
echo "----- post-state -----"
fail=0
if snap list lxd >/dev/null 2>&1; then
    echo "snap list lxd: STILL INSTALLED"; fail=1
else
    echo "snap list lxd: not installed (expected)"
fi
echo -n "snap.lxd.* / snap-lxd-* unit files left in /etc/systemd/system: "
left="$(find /etc/systemd/system -maxdepth 1 \( -name 'snap.lxd.*' -o -name 'snap-lxd-*' \) 2>/dev/null | wc -l | tr -d ' ')"
echo "${left}"
[ "${left}" -eq 0 ] || fail=1
echo -n "lxd unix sockets still listening: "
socks="$( (ss -lxn 2>/dev/null || true) | grep -c 'snap/lxd' || true)"
echo "${socks}"
[ "${socks}" -eq 0 ] || fail=1
for u in ict-trader-live.service ict-web-api.service; do
    st="$(systemctl is-active "${u}" 2>/dev/null || true)"
    echo "${u}: ${st}"
    [ "${st}" = "active" ] || fail=1
done

if [ "${fail}" -ne 0 ]; then
    log "WARNING: post-state is not clean (see above). Manual inspection needed."
    record_audit "remove-lxd-snap" "error" "{\"unit_files_left\": ${left}, \"sockets\": ${socks}}" >/dev/null || true
    exit 1
fi
log "Done: the lxd snap is removed; trader and web-api are active."
record_audit "remove-lxd-snap" "ok" '{"removed": "lxd"}' >/dev/null || true
exit 0
