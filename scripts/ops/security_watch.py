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

Detector ``files`` (row SEC-DETECTORS, D3): sha256 of every watched file, compared
with the previous run. Watched: ``authorized_keys``/``authorized_keys2`` of every
account with a home under /home plus /root, /etc/sudoers and /etc/sudoers.d/*,
regular files under /etc/systemd/system (units and drop-ins; ``*.wants`` symlinks
are skipped, an enable needs a unit file and that file is watched), /etc/crontab,
/etc/cron.d/* and /var/spool/cron/crontabs/*.

* ``changed`` / ``added`` / ``removed``: ONE alert per (path, new hash), naming the
  PATH only, never the content. The baseline then moves on, so a change alerts once.
* EXPECTED, silent: a file under /etc/systemd/system whose bytes equal
  ``deploy/<same name>`` in this checkout, or a drop-in (``*.d/*.conf``) whose bytes
  equal any file under ``deploy/``. That is what ``scripts/install_systemd_units.sh``
  writes (plain ``cp``), so a deploy never alerts. A removed unit is counted, not
  alerted (deploys retire units); a removed key, sudoers or cron file alerts.
* Root-only paths are read with ``sudo -n``. A path that cannot be read keeps its
  previous hash (unreadable is not "removed") and is counted in ``unreadable``; when
  that set grows, ONE alert says which paths are not being checked.

State: ``runtime_logs/security_watch_state.json`` (on the VM, never committed).
Run by ``ict-security-watch.timer`` every 5 min on the live VM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


# ---------------------------------------------------------------------------
# Detector D3: file integrity
# ---------------------------------------------------------------------------

FILES_COOLDOWN_S = 24 * 3600
FILES_BLIND_COOLDOWN_S = 24 * 3600
_SYSTEMD_DIR = "/etc/systemd/system"
_UNIT_SUFFIXES = (".service", ".timer", ".socket", ".path", ".mount", ".target", ".conf")


def _sudo(args: list[str]) -> bytes | None:
    try:
        r = subprocess.run(["sudo", "-n", *args], capture_output=True, timeout=30, check=False)
    except Exception:  # noqa: BLE001
        return None
    return r.stdout if r.returncode == 0 else None


def read_file(path: str) -> bytes | None:
    """File bytes, via ``sudo -n cat`` when the service user cannot read it."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except PermissionError:
        return _sudo(["cat", "--", path])
    except OSError:
        return None


def list_files(directory: str) -> list[str] | None:
    """Regular files directly in *directory* ([] if absent, None if unlistable)."""
    if not os.path.isdir(directory):
        return []
    try:
        return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                      if os.path.isfile(os.path.join(directory, n))
                      and not os.path.islink(os.path.join(directory, n)))
    except PermissionError:
        out = _sudo(["find", directory, "-maxdepth", "1", "-type", "f", "-print0"])
        if out is None:
            return None
        return sorted(p for p in out.decode("utf-8", "replace").split("\0") if p)


def watched_paths(lister: Callable[[str], list[str] | None] = list_files,
                  home_root: str = "/home") -> tuple[dict[str, str], list[str]]:
    """{path: category} to hash, and the directories that could not be listed."""
    paths: dict[str, str] = {}
    blind_dirs: list[str] = []
    homes = ["/root"]
    try:
        homes += sorted(os.path.join(home_root, d) for d in os.listdir(home_root))
    except OSError:
        blind_dirs.append(home_root)
    for h in homes:
        for name in ("authorized_keys", "authorized_keys2"):
            paths[os.path.join(h, ".ssh", name)] = "ssh_keys"
    paths["/etc/sudoers"] = "sudoers"
    paths["/etc/crontab"] = "cron"
    for d, cat in (("/etc/sudoers.d", "sudoers"), ("/etc/cron.d", "cron"),
                   ("/var/spool/cron/crontabs", "cron")):
        listed = lister(d)
        if listed is None:
            blind_dirs.append(d)
            continue
        for p in listed:
            paths[p] = cat
    for dirpath, dirnames, filenames in os.walk(_SYSTEMD_DIR):
        dirnames[:] = [x for x in dirnames if not x.endswith((".wants", ".requires"))]
        for n in filenames:
            p = os.path.join(dirpath, n)
            if n.endswith(_UNIT_SUFFIXES) and not os.path.islink(p):
                paths[p] = "systemd"
    return paths, blind_dirs


def deploy_index(deploy_dir: Path) -> tuple[dict[str, str], set[str]]:
    """({file name: sha256} for top-level deploy units, {sha256 of every deploy file})."""
    by_name: dict[str, str] = {}
    every: set[str] = set()
    if not deploy_dir.is_dir():
        return by_name, every
    for p in deploy_dir.rglob("*"):
        if p.is_file():
            try:
                h = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
            every.add(h)
            if p.parent == deploy_dir:
                by_name[p.name] = h
    return by_name, every


def _expected_systemd(path: str, digest: str, deploy: tuple[dict[str, str], set[str]]) -> bool:
    by_name, every = deploy
    name = os.path.basename(path)
    if by_name.get(name) == digest:
        return True
    return os.path.basename(os.path.dirname(path)).endswith(".d") and digest in every


def run_files(state: dict, now: float, host: str,
              admit: Callable[..., bool],
              collect: Callable[[], tuple[dict[str, str], list[str]]] = watched_paths,
              reader: Callable[[str], bytes | None] = read_file,
              deploy: tuple[dict[str, str], set[str]] | None = None) -> tuple[dict, list[str]]:
    """One pass of D3. Returns (new files state, alert texts)."""
    s = dict(state or {})
    alerts: list[str] = []
    first = "hashes" not in s
    old: dict[str, str] = dict(s.get("hashes") or {})
    deploy = deploy if deploy is not None else deploy_index(REPO_ROOT / "deploy")
    paths, blind_dirs = collect()
    new: dict[str, str] = {}
    unreadable: list[str] = list(blind_dirs)
    for p in sorted(paths):
        data = reader(p)
        if data is None:
            if os.path.lexists(p):
                unreadable.append(p)
                if p in old:
                    new[p] = old[p]          # cannot look: keep, never "removed"
            continue
        new[p] = hashlib.sha256(data).hexdigest()
    # A blind directory hides its files: keep their old hashes too.
    for p, h in old.items():
        if p not in new and any(p.startswith(d.rstrip("/") + "/") for d in blind_dirs):
            new[p] = h
    expected = changed = 0
    if not first:
        for p in sorted(set(old) | set(new)):
            o, n = old.get(p), new.get(p)
            if o == n:
                continue
            cat = paths.get(p) or ("systemd" if p.startswith(_SYSTEMD_DIR + "/") else "file")
            if n is None:
                if cat == "systemd":
                    expected += 1             # deploys retire units
                    continue
                what = "REMOVED"
            elif cat == "systemd" and _expected_systemd(p, n, deploy):
                expected += 1
                continue
            else:
                what = "ADDED" if o is None else "CHANGED"
            changed += 1
            if admit(COOLDOWN_KIND, f"files:{p}:{n or 'gone'}", FILES_COOLDOWN_S):
                alerts.append(f"[RED FLAG] {cat} file {what} on {host}: {p} "
                              f"(not a deploy/ copy). Content is not shown. "
                              f"Check who changed it. Nothing was stopped.")
    prev_blind = set(s.get("unreadable") or [])
    if set(unreadable) - prev_blind and admit(
            COOLDOWN_KIND, "files:blind:" + ",".join(sorted(unreadable)), FILES_BLIND_COOLDOWN_S):
        alerts.append(f"[RED FLAG] security watch on {host} cannot read {len(unreadable)} "
                      f"watched path(s), so they are not being checked: "
                      + ", ".join(sorted(unreadable)[:10])
                      + (" ..." if len(unreadable) > 10 else "")
                      + ". Likely missing passwordless sudo for cat/find. Nothing was stopped.")
    if first:
        cats: dict[str, int] = {}
        for p in new:
            cats[paths.get(p, "file")] = cats.get(paths.get(p, "file"), 0) + 1
        alerts.append(f"[INFO] security watch on {host}: file baseline recorded: "
                      + ", ".join(f"{k}={v}" for k, v in sorted(cats.items()))
                      + f"; unreadable={len(unreadable)}. Any change that is not a deploy/ "
                        f"copy alerts from now on.")
    s.update({"hashes": new, "unreadable": sorted(unreadable), "checked_ts": now,
              "last": {"watched": len(new), "changed": changed, "expected": expected,
                       "unreadable": len(unreadable)}})
    if first:
        s["baseline_ts"] = now
    return s, alerts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print alerts; send nothing, write nothing")
    ap.add_argument("--trust-current", action="store_true",
                    help="re-record the SSH baseline from the last 24 h")
    ap.add_argument("--trust-current-files", action="store_true",
                    help="re-record the file-integrity baseline (D3)")
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
        host = socket.gethostname()
        ssh, alerts = run_ssh(state.get("ssh") or {}, now, read_journal, admit, host)
        state["ssh"] = ssh
        if args.trust_current_files:
            state.pop("files", None)
        try:
            files, file_alerts = run_files(state.get("files") or {}, now, host, admit)
            state["files"] = files
            alerts += file_alerts
        except Exception as exc:  # noqa: BLE001  # one detector failing never stops the other
            print(f"security_watch: files detector failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
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
                                  ("read_state", "window", "failed_last_hour", "blind_runs")},
                          "files": (state.get("files") or {}).get("last")}))
    except Exception as exc:  # noqa: BLE001
        print(f"security_watch: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
