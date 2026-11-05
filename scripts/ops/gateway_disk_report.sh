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
echo; echo "===== /home/ubuntu depth 3 (the 33G; GWDISK-0001) ====="
timeout 150 ${SUDO} du -xh --max-depth=3 /home/ubuntu 2>/dev/null | sort -rh | first 30 || echo "could_not_look: du /home/ubuntu"
echo; echo "===== /home/ubuntu top-level entries (ls -la, sizes in bytes) ====="
${SUDO} ls -la --time-style=+%Y-%m-%dT%H:%M /home/ubuntu 2>&1 | first 40 || echo "could_not_look: ls /home/ubuntu"
echo; echo "===== files >=500M under /home/ubuntu ====="
timeout 150 ${SUDO} find /home/ubuntu -xdev -type f -size +500M -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | first 20 | awk -F'\t' '{printf "%.0fM\t%s\t%s\n",$1/1048576,$2,$3}' || echo "could_not_look: find big"
echo; echo "===== growth: bytes modified under /home/ubuntu in last 60 min / 24 h (is anything still writing) ====="
for m in 60 1440; do
  printf 'last %s min: ' "${m}"
  timeout 100 ${SUDO} find /home/ubuntu -xdev -type f -mmin -"${m}" -printf '%s\n' 2>/dev/null | awk '{s+=$1;n++} END{printf "%d files, %.0fM\n",n,s/1048576}' || echo "could_not_look"
done
echo "newest 10 files >=1M:"
timeout 100 ${SUDO} find /home/ubuntu -xdev -type f -size +1M -printf '%TY-%Tm-%TdT%TH:%TM\t%s\t%p\n' 2>/dev/null | sort -r | first 10 | awk -F'\t' '{printf "%s\t%.0fM\t%s\n",$1,$2/1048576,$3}' || echo "could_not_look"
echo; echo "===== ict-trading-bot checkout on the gateway ====="
RB=/home/ubuntu/ict-trading-bot
if [ -d "${RB}" ]; then
  timeout 60 ${SUDO} du -sh "${RB}/.git" 2>/dev/null || echo "could_not_look: du .git"
  timeout 60 ${SUDO} du -sh --exclude=.git "${RB}" 2>/dev/null || echo "could_not_look: du worktree"
  ${SUDO} git -c safe.directory="${RB}" -C "${RB}" count-objects -vH 2>&1 | first 12
  ${SUDO} git -c safe.directory="${RB}" -C "${RB}" log -1 --format='HEAD %h committed %cd' --date=iso-strict 2>&1 | first 2
  ${SUDO} git -c safe.directory="${RB}" -C "${RB}" rev-parse --is-shallow-repository 2>&1 | first 2
  ${SUDO} ls -la --time-style=+%Y-%m-%dT%H:%M "${RB}" 2>&1 | first 40
else
  echo "absent: ${RB}"
fi
echo; echo "===== who references the checkout path (units, timers, cron, compose, mounts) ====="
${SUDO} grep -rIl 'ict-trading-bot' /etc/systemd/system /etc/cron.d /etc/cron.daily /etc/cron.hourly /var/spool/cron /home/ubuntu/.config/systemd 2>/dev/null | first 30 || true
echo "-- ubuntu crontab:"; ${SUDO} crontab -u ubuntu -l 2>&1 | grep -v '^#' | first 20 || true
echo "-- active timers:"; systemctl list-timers --all --no-pager 2>&1 | first 20
echo "-- ib-gateway mounts:"; ${SUDO} docker inspect ib-gateway --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' 2>&1 | first 10
echo "-- processes with cwd or files under the checkout:"; timeout 60 ${SUDO} lsof +D "${RB}" 2>/dev/null | awk 'NR>1{print $1}' | sort | uniq -c | first 10 || echo "none_or_lsof_missing"
echo; echo "===== checkout .git forensics (GWDISK-0001 round 2; stderr warnings suppressed) ====="
RB=/home/ubuntu/ict-trading-bot
if [ -d "${RB}" ]; then
  G="git -c safe.directory=${RB} -C ${RB}"
  echo "-- count-objects -vH:"; ${SUDO} ${G} count-objects -vH 2>/dev/null | first 12
  echo "-- pack files (pack-*.pack): count, total, size buckets:"
  ${SUDO} find "${RB}/.git/objects/pack" -maxdepth 1 -type f -name 'pack-*.pack' -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1; if($1<10485760)a++; else if($1<52428800)b++; else c++} END{printf "%d packs, %.1fG total; <10M:%d 10-50M:%d >=50M:%d\n",n,s/1073741824,a,b,c}'
  echo "-- garbage tmp_pack_* / .tmp-* files: count and total size:"
  ${SUDO} find "${RB}/.git/objects/pack" -maxdepth 1 -type f \( -name 'tmp_pack_*' -o -name '.tmp-*' \) -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1} END{printf "%d files, %.2fG\n",n,s/1073741824}'
  echo "-- loose objects (outside pack/ and info/): count and total size:"
  ${SUDO} find "${RB}/.git/objects" -mindepth 2 -type f ! -path '*/pack/*' ! -path '*/info/*' -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1} END{printf "%d loose, %.2fG\n",n,s/1073741824}'
  echo "-- .git top-level du:"; timeout 100 ${SUDO} du -sh "${RB}/.git"/* 2>/dev/null | sort -rh | first 12
  echo "-- gc.log present?:"; { ${SUDO} ls -la --time-style=+%Y-%m-%dT%H:%M "${RB}/.git/gc.log" 2>&1 | first 2; } || true; ${SUDO} head -c 400 "${RB}/.git/gc.log" 2>/dev/null || true
  echo "-- gc / fetch / sparse config (names+values):"
  ${SUDO} ${G} config --get-regexp '^(gc|fetch|core\.(sparse|bare|preload)|pack|maintenance|extensions)' 2>/dev/null | first 20 || true
  echo "-- sparse-checkout list (first 25):"; ${SUDO} ${G} sparse-checkout list 2>&1 | first 25
  echo "-- excluded-shape files present under comms/research:"
  timeout 100 ${SUDO} find "${RB}/comms/research" -xdev -type f \( -name '*.pkl' -o -name '*.npz' -o -name '*.parquet' -o -name '*.csv' -o -name '*.gz' -o -name '*.zip' -o -name '*.joblib' \) -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1} END{printf "%d files, %.2fG\n",n,s/1073741824}'
  timeout 100 ${SUDO} du -xh --max-depth=2 "${RB}/comms/research" 2>/dev/null | sort -rh | first 12
  echo "-- ict-git-sync now / last journal lines:"; systemctl is-active ict-git-sync.service 2>&1 || true; ${SUDO} journalctl -u ict-git-sync.service -n 12 --no-pager 2>/dev/null | cut -c1-200
  echo "-- round 3: worktree vs tracked (is comms/research bigger than main tracks?):"
  { ${SUDO} ${G} ls-files -z -- comms/research 2>/dev/null | (cd "${RB}" && ${SUDO} xargs -0 -r stat -c %s 2>/dev/null) | awk '{n++;s+=$1} END{printf "tracked comms/research present on disk: %d files, %.2fG\n",n,s/1073741824}'; } || true
  { timeout 100 ${SUDO} ${G} status --porcelain --ignored 2>/dev/null | awk '{c[substr($0,1,2)]++} END{for(k in c)printf "status %s: %d\n",k,c[k]}' | first 10; } || true
  echo "-- comms/research depth 3 (top 15):"; { timeout 100 ${SUDO} du -xh --max-depth=3 "${RB}/comms/research" 2>/dev/null | sort -rh | first 15; } || true
  echo "-- loose objects by age (files, size): <=14d / >14d:"
  { ${SUDO} find "${RB}/.git/objects" -mindepth 2 -type f ! -path '*/pack/*' ! -path '*/info/*' -mtime -14 -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1} END{printf "<=14d: %d files, %.2fG\n",n,s/1073741824}'; } || true
  { ${SUDO} find "${RB}/.git/objects" -mindepth 2 -type f ! -path '*/pack/*' ! -path '*/info/*' -mtime +14 -printf '%s\n' 2>/dev/null | awk '{n++;s+=$1} END{printf ">14d: %d files, %.2fG\n",n,s/1073741824}'; } || true
  echo "-- loose objects already in a pack (prune-packed dry run): count and size:"
  { timeout 120 ${SUDO} ${G} prune-packed -n 2>/dev/null | awk '{print $NF}' | (cd "${RB}" && ${SUDO} xargs -r stat -c %s 2>/dev/null) | awk '{n++;s+=$1} END{printf "%d objects, %.2fG\n",n,s/1073741824}'; } || echo "could_not_look"
  echo "-- unreachable loose objects older than 14d (prune dry run): count:"
  { timeout 240 ${SUDO} ${G} prune -n --expire=2.weeks.ago 2>/dev/null | wc -l; } || echo "could_not_look"
  echo "-- snap disabled revisions / apt (small levers):"; { snap list --all 2>/dev/null | awk '/disabled/' | first 10; } || true
fi
} 2>&1 | mask
