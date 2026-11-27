#!/usr/bin/env bash
# Tier-1 read-only diagnostic (VM-CONTROL-1127): is the live VM's slowness CPU starvation or venue/network latency?
#
#   1. thread census of the trader and web-api main processes, and per-THREAD CPU over a 20 s /proc window
#      (counts abandoned executor threads; names which threads burn the CPU)
#   2. curl timing breakdown (dns / connect / tls / first byte / total) to the Bybit mainnet + demo hosts
#   3. vm_latency_probe.py: scheduler latency, Bybit public HTTP from Python, Bybit PRIVATE get_positions timed per
#      account (prints elapsed, retCode and row count only -- no balances, sizes or keys)
#   4. py-spy dump of both processes (installed with `pip --target` into /tmp/metis-pyspy if absent; needs sudo -n
#      for ptrace; says so and skips if either is unavailable). Function names + lines only, no --locals.
#
# Writes nothing to the repo, the DB or any service; signals, restarts and places nothing.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
load_runtime_secrets  # exchange creds for the timed private call (never printed)
PY="${REPO_DIR}/.venv/bin/python3"

echo "probe starts: $(date -u +%Y-%m-%dT%H:%M:%SZ)   loadavg: $(cat /proc/loadavg 2>/dev/null)   nproc: $(nproc)"
echo "--- CPU pressure (PSI) ---"; cat /proc/pressure/cpu 2>/dev/null || echo "(no PSI: could_not_look)"

TRADER_PID="$(systemctl show -p MainPID --value ict-trader-live.service 2>/dev/null || echo 0)"
API_PID="$(systemctl show -p MainPID --value ict-web-api.service 2>/dev/null || echo 0)"

echo
echo "===== 1. thread census + per-thread CPU over 20 s ====="
python3 - "${TRADER_PID}" "${API_PID}" <<'PY'
import os, sys, time, collections
hz = os.sysconf("SC_CLK_TCK")
pids = {"trader": sys.argv[1], "web-api": sys.argv[2]}

def tasks(pid):
    out = {}
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            try:
                raw = open(f"/proc/{pid}/task/{tid}/stat").read()
                f = raw[raw.rindex(")") + 2:].split()
                comm = open(f"/proc/{pid}/task/{tid}/comm").read().strip()
                out[tid] = (int(f[11]) + int(f[12]), comm, f[0])  # utime+stime, name, state
            except Exception:
                continue
    except Exception:
        return None
    return out

a = {k: tasks(p) for k, p in pids.items()}
t0 = time.time(); time.sleep(20); dt = time.time() - t0
b = {k: tasks(p) for k, p in pids.items()}
for k, pid in pids.items():
    if not b[k]:
        print(f"{k} (pid {pid}): could_not_look"); continue
    states = collections.Counter(v[2] for v in b[k].values())
    names = collections.Counter(v[1] for v in b[k].values())
    print(f"{k} (pid {pid}): {len(b[k])} threads  states {dict(states)}  (R=running/runnable, S=sleeping, D=io-wait)")
    print(f"  thread names: {names.most_common(12)}")
    rows = []
    for tid, (tk, comm, st) in b[k].items():
        d = tk - (a[k] or {}).get(tid, (tk,))[0] if tid in (a[k] or {}) else tk
        rows.append((100.0 * d / hz / dt, tid, comm, st))
    rows.sort(reverse=True)
    busy = [r for r in rows if r[0] >= 1.0]
    print(f"  threads >= 1% of a CPU over {dt:.1f}s: {len(busy)} of {len(rows)}; total {sum(r[0] for r in rows):.1f}% of ONE cpu")
    for pct, tid, comm, st in rows[:10]:
        print(f"    {pct:6.1f}%  tid {tid:>8}  {comm:<18} {st}")
PY

echo
echo "===== 2. curl timing to Bybit (seconds) ====="
for host in https://api.bybit.com https://api-demo.bybit.com; do
    for i in 1 2 3; do
        curl -s -o /dev/null -m 20 -w "${host} try ${i}: dns %{time_namelookup}  connect %{time_connect}  tls %{time_appconnect}  first-byte %{time_starttransfer}  total %{time_total}  http %{http_code}\n" "${host}/v5/market/time" || echo "${host} try ${i}: curl failed rc=$?"
    done
done

echo
echo "===== 3. python probe ====="
if [ -x "${PY}" ]; then
    (cd "${REPO_DIR}" && timeout 240 "${PY}" "${REPO_DIR}/scripts/ops/vm_latency_probe.py") || echo "(python probe exited rc=$?)"
else
    echo "venv python missing at ${PY}: could_not_look"
fi

echo
echo "===== 4. py-spy dump ====="
PYSPY="$(command -v py-spy || true)"
if [ -z "${PYSPY}" ] && [ -x /tmp/metis-pyspy/bin/py-spy ]; then PYSPY=/tmp/metis-pyspy/bin/py-spy; fi
if [ -z "${PYSPY}" ]; then
    echo "py-spy absent; installing to /tmp/metis-pyspy (pip --target, outside the venv)"
    timeout 180 python3 -m pip install --quiet --disable-pip-version-check --target /tmp/metis-pyspy py-spy 2>&1 | tail -3
    [ -x /tmp/metis-pyspy/bin/py-spy ] && PYSPY=/tmp/metis-pyspy/bin/py-spy
fi
if [ -z "${PYSPY}" ]; then
    echo "py-spy unavailable after install attempt: could_not_look"
elif ! sudo -n true 2>/dev/null; then
    echo "sudo -n unavailable (ptrace needs it): could_not_look"
else
    for pair in "trader:${TRADER_PID}" "web-api:${API_PID}"; do
        name="${pair%%:*}"; pid="${pair#*:}"
        echo "--- ${name} (pid ${pid}) ---"
        timeout 40 sudo -n "${PYSPY}" dump --pid "${pid}" 2>&1 | head -220 || echo "(py-spy dump rc=$?)"
    done
fi
echo
echo "probe ends: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit 0
