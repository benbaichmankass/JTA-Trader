#!/usr/bin/env bash
# system-action wrapper (Tier 1, READ-ONLY): who is using the live VM's CPU, MEASURED over a window?
#
# LIVE-VM-CPU-SATURATION-1112: cpu p95 99.7-99.9% every day since 11-04 and no allowlisted read could say
# which process. `ps %CPU` (status-check) is lifetime-average, so it cannot name a burst. This samples
# /proc twice, WINDOW seconds apart (default 30, max 120), and prints per-process and per-systemd-unit CPU
# over exactly that window, plus loadavg, CPU pressure (PSI) and the trader restart count. It signals nothing,
# restarts nothing, writes nothing. Population is printed with every table.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

WINDOW="${CPU_SAMPLE_WINDOW_S:-30}"
case "${WINDOW}" in (''|*[!0-9]*) WINDOW=30 ;; esac
[ "${WINDOW}" -lt 5 ] && WINDOW=5
[ "${WINDOW}" -gt 120 ] && WINDOW=120

echo "===== loadavg / nproc ====="
echo "loadavg: $(cat /proc/loadavg 2>/dev/null || echo '(unreadable)')   nproc: $(nproc 2>/dev/null || echo '?')"
echo "--- CPU pressure (PSI; some/full avg10/avg60/avg300) ---"
cat /proc/pressure/cpu 2>/dev/null || echo "(no /proc/pressure/cpu: read_state=could_not_look)"

echo
echo "===== per-process and per-unit CPU over a ${WINDOW}s window ====="
python3 - "${WINDOW}" <<'PY'
import os, sys, time
win = int(sys.argv[1]); hz = os.sysconf("SC_CLK_TCK"); ncpu = os.cpu_count() or 1

def snap():
    out = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            raw = open(f"/proc/{pid}/stat").read()
            comm = raw[raw.index("(") + 1:raw.rindex(")")]
            f = raw[raw.rindex(")") + 2:].split()
            ticks = int(f[11]) + int(f[12])  # utime + stime
            try:
                cg = open(f"/proc/{pid}/cgroup").read().strip().splitlines()[-1].split("::")[-1]
            except Exception:
                cg = "?"
            try:
                args = open(f"/proc/{pid}/cmdline").read().replace("\0", " ").strip()[:110] or f"[{comm}]"
            except Exception:
                args = f"[{comm}]"
            out[pid] = (ticks, comm, cg, args, float(f[19]))  # starttime ticks
        except Exception:
            continue
    return out

def total():
    v = open("/proc/stat").readline().split()[1:]
    return sum(int(x) for x in v), int(v[3]) + (int(v[4]) if len(v) > 4 else 0)

t0, (tot0, idle0) = time.time(), total(); a = snap()
time.sleep(win)
t1, (tot1, idle1) = time.time(), total(); b = snap()
dt = t1 - t0
rows, units = [], {}
for pid, (tk, comm, cg, args, st) in b.items():
    if pid in a and a[pid][4] == st:
        d = tk - a[pid][0]
    else:
        d = tk  # born inside the window: all its ticks are in-window
    pct = 100.0 * d / hz / dt  # % of ONE cpu
    unit = cg.rsplit("/", 1)[-1] or cg
    rows.append((pct, pid, comm, unit, args))
    units[unit] = units.get(unit, 0.0) + pct
gone = sum(1 for p in a if p not in b)
busy = 100.0 * (1 - (idle1 - idle0) / max(1, tot1 - tot0))
print(f"population: {len(b)} processes seen at the end, {len(a)} at the start, {gone} exited in-window (their CPU is NOT counted: lower bound)")
print(f"window: {dt:.1f}s  whole-machine busy: {busy:.1f}% of {ncpu} cpus  sum of listed processes: {sum(r[0] for r in rows):.1f}% of ONE cpu (max {100*ncpu}%)")
print("--- top 20 processes (pct = % of ONE cpu over the window) ---")
print(f"{'pct':>6} {'pid':>7} {'comm':<16} {'unit':<34} args")
for pct, pid, comm, unit, args in sorted(rows, reverse=True)[:20]:
    print(f"{pct:6.1f} {pid:>7} {comm[:16]:<16} {unit[:34]:<34} {args}")
print("--- by systemd unit / cgroup leaf (sum of its processes) ---")
for u, p in sorted(units.items(), key=lambda kv: -kv[1])[:15]:
    print(f"{p:6.1f}  {u}")
PY

echo
echo "===== trader restarts, last 24h (journal; each one SIGTERMs the whole trader cgroup) ====="
if command -v journalctl >/dev/null 2>&1; then
    n="$(journalctl -u ict-trader-live --since '-24h' --no-pager 2>/dev/null | grep -c 'Stopping ICT Trader Live' || true)"
    echo "Stopping ICT Trader Live: ${n:-0} (read_state=$([ -n "${n}" ] && echo read || echo could_not_look))"
else
    echo "(journalctl unavailable)"
fi
