#!/usr/bin/env bash
# system-action wrapper (Tier 1, READ-ONLY): where is the live VM's disk going?
#
# PI-20261017-VSMHZYHF-0001: the root disk read 96% (45 G, 2.4 G free) on
# 2026-10-17 and no allowlisted read could say WHY -- status-check prints df
# only, and the diag relay is fixed-curl. This prints a bounded du breakdown,
# the journal size, every trade_journal backup with its age, and the journald /
# apt / pip footprints. It deletes nothing and touches no service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
DB_DIR="$(dirname "${DB_PATH}")"
# du over / needs root to see every directory; fall back to the unprivileged
# view (partial, and said so) when passwordless sudo is not available.
SUDO=""
if sudo -n true 2>/dev/null; then SUDO="sudo -n"; else echo "(no passwordless sudo: du is the unprivileged view)"; fi

echo "===== df ====="
df -h / "${DB_DIR}" 2>/dev/null || true

echo
echo "===== top-level (du -x / --max-depth=1) ====="
timeout 120 ${SUDO} du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -20 || true

echo
echo "===== ${DB_DIR} (depth 1) ====="
timeout 120 ${SUDO} du -xh --max-depth=1 "${DB_DIR}" 2>/dev/null | sort -rh | head -25 || true

echo
echo "===== journal DB + its backups (path, bytes, mtime) ====="
ls -l --time-style=+%Y-%m-%dT%H:%M "${DB_PATH}" "${DB_PATH}"-wal "${DB_PATH}"-shm 2>/dev/null || true
shopt -s nullglob
baks=( "${DB_PATH}".bak-* "${DB_PATH}".*-bak-* "${DB_DIR}"/*.db.bak-* )
if [ "${#baks[@]}" -gt 0 ]; then
    ls -l --time-style=+%Y-%m-%dT%H:%M "${baks[@]}" 2>/dev/null | sort -u -k7
    printf 'backup files: %d, total: ' "$(printf '%s\n' "${baks[@]}" | sort -u | wc -l)"
    printf '%s\n' "${baks[@]}" | sort -u | xargs -r du -ch 2>/dev/null | tail -1
else
    echo "(no journal backups found)"
fi

echo
echo "===== home / logs / caches ====="
for d in /home/ubuntu /home/ubuntu/ict-trading-bot /opt/ict-trading-bot /var/log /var/cache/apt /home/ubuntu/.cache /root/.cache /tmp; do
    [ -e "${d}" ] && timeout 60 ${SUDO} du -sh "${d}" 2>/dev/null || true
done
echo "--- journald ---"
timeout 20 ${SUDO} journalctl --disk-usage 2>/dev/null || echo "(journalctl --disk-usage unavailable)"

echo
echo "===== largest files on / (> 200 MB) ====="
timeout 120 ${SUDO} find / -xdev -type f -size +200M -printf '%s\t%TY-%Tm-%TdT%TH:%TM\t%p\n' 2>/dev/null \
    | sort -rn | head -30 | awk -F'\t' '{printf "%8.1f MB  %s  %s\n", $1/1048576, $2, $3}' || true
exit 0
