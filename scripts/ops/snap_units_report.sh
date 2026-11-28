#!/usr/bin/env bash
# Tier-1 read-only diagnostic: is a new /etc/systemd/system/snap-<name>-<rev>.mount unit a snapd refresh?
#
# WHY (2026-11-28, ops-flags / security watch): security_watch.py alerts on any file in /etc/systemd/system that is not a
# deploy/ copy or an installer-receipt hash ("systemd file ADDED: /etc/systemd/system/snap-snapd-28331.mount", and
# snap-core22-3130.mount on 11-27). The theory is that snapd wrote them on its daily auto-refresh. That is an inference
# until this report shows it: the live VM has no arbitrary-bash relay by design, and no existing read-only action runs
# `snap`. This is the sanctioned way to read it.
#
# Prints, for the snapd and core22 snaps and every snap-*.mount unit file:
#   1. snap version, `snap changes` (spawn/ready times of the refreshes), and `snap list --all snapd core22`
#   2. per snap-*.mount: ls -l (full-iso mtime), sha256, the unit file text (a snapd-generated mount unit: Description,
#      Where=, What=, Type=squashfs; no secrets), and systemctl's ActiveEnterTimestamp / FragmentPath
#   3. the .snap file each unit's What= names: exists? size, mtime (so unit mtime can be compared with the refresh)
#   4. unattended-upgrades / snapd.refresh timers: the schedule that would have caused a refresh
# plus a COMPARISON block that only states what is measured (unit mtime vs the matching refresh's ready time) and says
# `could_not_look` for anything unreadable. It never says "benign": the reader decides from the evidence.
#
# READS ONLY. Mutates nothing, restarts nothing, installs nothing. Every command is timeout-bounded and
# failure-tolerant (strict mode, every probe wrapped in t() or `|| true`); always exits 0 (an observation, not a gate).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

log "Collecting snap refresh evidence for snap-*.mount units (read-only)…"
t() { timeout 20 "$@" 2>&1 || echo "(could_not_look: '$*' rc=$?)"; }

echo "report starts: $(date -u +%Y-%m-%dT%H:%M:%SZ)   host: $(hostname)"

echo
echo "===== 1. snapd: version, recent changes, revisions ====="
if command -v snap >/dev/null 2>&1; then
  t snap version
  echo "--- snap changes (all listed; Spawn/Ready are UTC-ish as snapd prints them) ---"
  t snap changes
  echo "--- snap list --all snapd core22 ---"
  t snap list --all snapd core22
  echo "--- snap refresh --time (when snapd refreshes) ---"
  t snap refresh --time
else
  echo "(could_not_look: 'snap' is not installed on this host)"
fi

echo
echo "===== 2. snap-*.mount unit files in /etc/systemd/system ====="
shopt -s nullglob
UNITS=(/etc/systemd/system/snap-*.mount)
echo "unit files found: ${#UNITS[@]}"
for u in "${UNITS[@]}"; do
  n="$(basename "$u")"
  echo
  echo "--- ${n} ---"
  t ls -l --time-style=full-iso "$u"
  echo -n "sha256: "; t sha256sum "$u"
  echo "file text:"; t cat "$u" | sed 's/^/    /'
  echo -n "systemctl: "; t systemctl show -p FragmentPath -p ActiveState -p ActiveEnterTimestamp --no-pager "$n" | tr '\n' ' '; echo
  what="$(sed -n 's/^What=//p' "$u" 2>/dev/null | head -1 || true)"
  if [ -n "${what}" ]; then
    echo -n "What= target: "; t ls -l --time-style=full-iso "${what}"
  else
    echo "What= target: (could_not_look: no What= line)"
  fi
done

echo
echo "===== 3. the two units named in the alerts (explicit) ====="
for n in snap-snapd-28331.mount snap-core22-3130.mount; do
  if [ -e "/etc/systemd/system/${n}" ]; then
    echo "${n}: present, mtime $(stat -c %y "/etc/systemd/system/${n}" 2>/dev/null || echo could_not_look)"
  else
    echo "${n}: ABSENT (could have been removed by a later refresh; see section 1 for the revisions now installed)"
  fi
done

echo
echo "===== 4. refresh schedule ====="
t systemctl list-timers --all --no-pager 'snapd*' 'apt-daily*' 'unattended*'

echo
echo "===== COMPARISON (measured only; no verdict) ====="
echo "A unit is consistent with a snapd refresh only if ALL hold: (a) its What= .snap exists under /var/lib/snapd/snaps,"
echo "(b) its revision appears in 'snap list --all' for that snap, (c) its mtime is at or after a 'snap changes' row for that"
echo "snap (Done, 'Refresh snap ...') and before the alert time. Check those three against the sections above;"
echo "anything missing is a finding, not a pass."
echo "report ends: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit 0
