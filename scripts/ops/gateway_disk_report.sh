#!/usr/bin/env bash
# Read-only: where is the IB Gateway VM's disk going? Runs ON the gateway VM
# (the workflow ProxyJumps through the trader, same as gateway-logs).
#
# COST-INFRA-REVIEW (PI-20261104-COSTINFRA): the gateway root disk went
# 75% (11-01) -> 100% (11-02) -> 94% (11-04) and no allowlisted read could say
# why. Prints df, a bounded du breakdown, the docker json-file log size of the
# ib-gateway container (the prime suspect: deploy/ib-gateway.compose.yml sets
# no logging cap), docker system df, journald size, apt cache, core dumps,
# /tmp and the largest files. Deletes nothing, restarts nothing, never opens
# IB Gateway settings or credentials. A section that cannot be read says so
# ("could_not_look"); it is never printed as 0.
#
# Public repo + output is posted to an issue: IPv4 and IBKR account ids masked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
# `head` would SIGPIPE its writer and, under pipefail, print a false
# "could_not_look"; first() reads to EOF instead.
first() { awk -v n="$1" 'NR<=n'; }

mask() { sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<ip>/g; s/\b(DU|DF)[A-Z0-9]{5,}\b/<acct>/g'; }
SUDO=""
if sudo -n true 2>/dev/null; then SUDO="sudo -n"; else echo "(no passwordless sudo: du is the unprivileged view, partial)"; fi

{
echo "===== now (UTC) ====="; date -u +%Y-%m-%dT%H:%M:%SZ
echo; echo "===== df ====="; df -h / 2>&1 || echo "could_not_look: df"
echo; echo "===== top-level (du -x / depth 1) ====="
timeout 120 ${SUDO} du -xh --max-depth=1 / 2>/dev/null | sort -rh | first 15 || echo "could_not_look: du /"
echo; echo "===== /var depth 2 ====="
timeout 120 ${SUDO} du -xh --max-depth=2 /var 2>/dev/null | sort -rh | first 15 || echo "could_not_look: du /var"
echo; echo "===== ib-gateway container log (docker json-file) ====="
LP="$(${SUDO} docker inspect ib-gateway --format '{{.LogPath}}' 2>/dev/null || true)"
if [ -n "${LP}" ]; then
  ${SUDO} ls -l --time-style=+%Y-%m-%dT%H:%M "${LP}" 2>&1 | mask || echo "could_not_look: ls LogPath"
  ${SUDO} docker inspect ib-gateway --format 'LogDriver={{.HostConfig.LogConfig.Type}} LogOpts={{json .HostConfig.LogConfig.Config}}' 2>&1 | mask
else
  echo "could_not_look: docker inspect LogPath"
fi
echo; echo "===== docker system df ====="
${SUDO} docker system df 2>&1 | first 12 || echo "could_not_look: docker system df"
echo; echo "===== /var/lib/docker depth 2 ====="
timeout 120 ${SUDO} du -xh --max-depth=2 /var/lib/docker 2>/dev/null | sort -rh | first 10 || echo "could_not_look: du docker"
echo; echo "===== journald ====="
journalctl --disk-usage 2>&1 || ${SUDO} journalctl --disk-usage 2>&1 || echo "could_not_look: journal"
echo; echo "===== apt cache / core dumps / tmp ====="
for d in /var/cache/apt /var/lib/systemd/coredump /var/crash /tmp /var/tmp /home/ubuntu; do
  [ -e "${d}" ] && timeout 60 ${SUDO} du -sh "${d}" 2>/dev/null || echo "absent_or_unreadable: ${d}"
done
echo; echo "===== 15 largest files on / (>=50M, no content shown) ====="
timeout 150 ${SUDO} find / -xdev -type f -size +50M -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | first 15 | awk -F'\t' '{printf "%.0fM\t%s\t%s\n",$1/1048576,$2,$3}' | mask
} 2>&1 | mask
