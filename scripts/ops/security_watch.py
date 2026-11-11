"""Security watch: ONE red-flag alert per suspicious event on this VM (SEC-DETECTORS).

Gates this adds or changes: **none**. It reads, compares and alerts. It never
blocks a login, stops a service, changes a mode or halts anything. Always exits 0.

Detector ``ssh`` (row SEC-DETECTORS, D1), reading ``journalctl -u ssh``:

* ``new_identity``: an ACCEPTED login whose (user, auth method, key fingerprint)
  is not in the recorded baseline. One alert per identity per 24 h. An identity
  is never trusted automatically: ``--trust-current`` re-records the baseline.
* ``failure_burst``: failed attempts in the last hour above ``FAIL_BURST_PER_HOUR``.
  One alert per 6 h; a burst twice as large again breaks the cooldown.
* ``blind``: the journal could not be read on ``BLIND_AFTER`` runs in a row. A
  detector that cannot look must say so: 0 findings is not "no logins".

MEASURED BASELINE (live VM ssh.service journal, 2026-11-11, ~23 h retained):
10,222 accepted logins, 1 identity (ubuntu / publickey / one fingerprint);
1,976 failed attempts from 31 sources, per hour median 50, max 588 (n=25 hours).
The burst threshold is ~3.4x that max. n=25 is thin: re-measure after a week.

NOT a detector here, and why: *login from a new source address*. The trainer VM
and every GitHub Actions runner log in with the SAME key, the runners from
rotating public addresses (31 distinct in 5 h), so every run would alert. It
becomes possible once the keys are split (row SEC-SSH-SINGLE-KEY).

State: ``runtime_logs/security_watch_state.json`` (on the VM, never committed).
Run by ``ict-security-watch.timer`` every 5 min on the live VM.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STATE_NAME = "security_watch_state.json"
COOLDOWN_KIND = "security_watch"
FAIL_BURST_PER_HOUR = 2000          # measured max 588/h over 25 h (2026-11-11)
IDENTITY_COOLDOWN_S = 24 * 3600
BURST_COOLDOWN_S = 6 * 3600
BLIND_AFTER = 3                     # consecutive unreadable runs before one alert
BLIND_COOLDOWN_S = 6 * 3600
FIRST_RUN_LOOKBACK_S = 24 * 3600
MAX_LOOKBACK_S = 6 * 3600           # after a long gap, never rescan more than this

_ACCEPTED = re.compile(r"Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<src>\S+) port \d+")
_FP = re.compile(r"SHA256:[A-Za-z0-9+/=]+")
_FAILED = re.compile(r"Failed password|Invalid user|authentication failure", re.IGNORECASE)


def identity(user: str, method: str, fp: str | None) -> str:
    return f"{user}|{method}|{fp or '-'}"


def parse(lines: list[str]) -> tuple[list[dict], int]:
    """Accepted logins and the count of failed-attempt lines."""
    accepted, failed = [], 0
    for ln in lines:
        m = _ACCEPTED.search(ln)
        if m:
            # The fingerprint follows the match; an optional regex group would be
            # skipped silently and make every key look like the same identity.
            f = _FP.search(ln, m.end())
            fp = f.group(0) if f else None
            accepted.append({"user": m["user"], "method": m["method"], "fp": fp,
                             "src": m["src"], "id": identity(m["user"], m["method"], fp)})
        elif _FAILED.search(ln):
            failed += 1
    return accepted, failed


def read_journal(since_epoch: float) -> tuple[list[str] | None, str]:
    """(lines, read_state). ``None`` lines means we could not look."""
    cmd = ["journalctl", "-u", "ssh", "-u", "sshd", "--no-pager", "-o", "short-iso",
           "--since", f"@{int(since_epoch)}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:  # noqa: BLE001
        return None, f"could_not_look: {type(exc).__name__}"
    if r.returncode != 0:
        return None, f"could_not_look: journalctl rc={r.returncode}"
    return r.stdout.splitlines(), "read"


def _load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _short(fp: str | None) -> str:
    return (fp[:19] + "...") if fp else "none"


def run_ssh(state: dict, now: float, reader: Callable[[float], tuple[list[str] | None, str]],
            admit: Callable[..., bool], host: str) -> tuple[dict, list[str]]:
    """One pass. Returns (new ssh state, alert texts). Pure but for *reader*/*admit*."""
    s = dict(state or {})
    alerts: list[str] = []
    first = "known" not in s
    last = float(s.get("last_ts") or 0)
    since = now - FIRST_RUN_LOOKBACK_S if first else max(last, now - MAX_LOOKBACK_S)
    lines, read_state = reader(since)
    s["read_state"], s["checked_ts"] = read_state, now
    if lines is None:
        s["blind_runs"] = int(s.get("blind_runs") or 0) + 1
        if s["blind_runs"] >= BLIND_AFTER and admit(COOLDOWN_KIND, "ssh:blind", BLIND_COOLDOWN_S):
            alerts.append(f"[RED FLAG] security watch on {host} cannot read the SSH journal "
                          f"({s['blind_runs']} runs in a row: {read_state}). SSH logins are "
                          f"not being checked. Nothing was stopped.")
        return s, alerts
    s["blind_runs"] = 0
    accepted, _ = parse(lines)
    seen: dict[str, dict] = {}
    for a in accepted:
        seen.setdefault(a["id"], {**a, "n": 0})["n"] += 1
    s["window"] = {"since": since, "accepted": len(accepted), "identities": len(seen)}
    if first:
        s["known"] = sorted(seen)
        s["baseline_ts"] = now
        alerts.append(f"[INFO] security watch on {host}: SSH baseline recorded from the last "
                      f"{FIRST_RUN_LOOKBACK_S // 3600} h: {len(accepted)} logins, {len(seen)} "
                      f"identity(ies): " + "; ".join(
                          f"{v['user']}/{v['method']}/{_short(v['fp'])} x{v['n']}"
                          for v in seen.values()) +
                      ". Any other identity alerts from now on.")
    else:
        known = set(s.get("known") or [])
        for ident, v in seen.items():
            if ident in known:
                continue
            if admit(COOLDOWN_KIND, f"ssh:new_identity:{ident}", IDENTITY_COOLDOWN_S):
                alerts.append(f"[RED FLAG] SSH login on {host} with an identity NOT in the baseline: "
                              f"user={v['user']} method={v['method']} key={_short(v['fp'])} "
                              f"source={v['src']} ({v['n']} login(s) since the last check). "
                              f"If this is expected: scripts/ops/security_watch.py --trust-current. "
                              f"Nothing was blocked.")
    # Failure burst: always the trailing hour, independent of the scan cursor.
    # (The scan window above is 24 h on the first run and ~5 min afterwards, so it
    # is never the right population for an hourly rate: read the hour separately.)
    hour_lines, _hour_state = reader(now - 3600)
    if hour_lines is not None:
        _, failed = parse(hour_lines)
        s["failed_last_hour"] = failed
        if failed > FAIL_BURST_PER_HOUR and admit(
                COOLDOWN_KIND, "ssh:failure_burst", BURST_COOLDOWN_S,
                severity=failed // FAIL_BURST_PER_HOUR):
            alerts.append(f"[RED FLAG] SSH failed-login burst on {host}: {failed} in the last hour "
                          f"(alert above {FAIL_BURST_PER_HOUR}; measured normal max 588/h on "
                          f"2026-11-11). Nothing was blocked.")
    else:
        s["failed_last_hour"] = None        # could not look, not zero
    s["last_ts"] = now
    return s, alerts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print alerts; send nothing, write nothing")
    ap.add_argument("--trust-current", action="store_true",
                    help="re-record the SSH baseline from the last 24 h")
    args = ap.parse_args(argv)
    try:
        from src.runtime.alert_cooldown import cooldown_admits
        from src.utils.paths import runtime_logs_dir
        path = Path(runtime_logs_dir()) / STATE_NAME
        state = _load(path)
        if args.trust_current:
            state.pop("ssh", None)
        now = time.time()
        admit = (lambda *a, **k: True) if args.dry_run else cooldown_admits
        ssh, alerts = run_ssh(state.get("ssh") or {}, now, read_journal, admit, socket.gethostname())
        state["ssh"] = ssh
        for text in alerts:
            print(text)
            if args.dry_run:
                continue
            try:
                from src.runtime import telegram_channels
                telegram_channels.send("alert", text)
            except Exception as exc:  # noqa: BLE001
                print(f"security_watch: send failed: {type(exc).__name__}", file=sys.stderr)
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
        print(json.dumps({"ssh": {k: ssh.get(k) for k in
                                  ("read_state", "window", "failed_last_hour", "blind_runs")}}))
    except Exception as exc:  # noqa: BLE001
        print(f"security_watch: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
