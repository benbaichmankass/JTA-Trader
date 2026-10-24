#!/usr/bin/env python3
"""Windowed sshd auth sweep of the live VM (ONHEALTH-0002, 2026-10-24).

``/api/diag/journalctl`` returns the LAST ``lines`` (max 2000) of the window it
is asked for, and the trainer VM alone logs ~400 accepted sessions an hour, so
one pull covers ~1.5 h. This walks ``[since, until)`` in small windows, splits
any window that comes back full, filters client-side, and reports COVERAGE so a
partial sweep can never read as clean.

Output carries no raw addresses or full fingerprints (public repo): a source is
``trainer`` / ``allowlisted`` / ``other:<4 hex of sha256>``, a key is its last
4 characters.

Usage: ssh_auth_sweep.py --since ISO --until ISO [--trainer-ip IP]   (or env TRAINER_VM_IP)
Exit 0 = full coverage, no non-allowlisted accept. 1 = non-allowlisted accepts
listed. 2 = coverage incomplete (a window could not be fully read) or usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CAP = 2000
MIN_WINDOW = timedelta(seconds=2)
_ACCEPT = re.compile(
    r"^(?P<ts>\S+) \S+ sshd\[\d+\]: Accepted (?P<method>\S+) for (?P<user>\S+) "
    r"from (?P<ip>\S+) port \d+ \S+: \S+ (?:SHA256:(?P<fp>\S+))?"
)


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(ip: str, trainer_ip: str, allow: set[str]) -> str:
    if ip == trainer_ip:
        return "trainer"
    if ip in allow:
        return "allowlisted"
    return "other:" + hashlib.sha256(ip.encode()).hexdigest()[:4]


def fetch_diag(path: str) -> dict:
    p = subprocess.run(["bash", "scripts/ops/diag_fetch.sh", path], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"diag_fetch rc={p.returncode}")
    return json.loads(p.stdout)


def sweep(since, until, trainer_ip, allow=frozenset(), window=timedelta(minutes=20), fetch=fetch_diag):
    """Return {accepts, total_accepts, windows, split, unreadable} for [since, until)."""
    res = {"accepts": [], "total_accepts": 0, "windows": 0, "split": 0, "unreadable": []}
    stack = []
    t = since
    while t < until:
        stack.append((t, min(t + window, until)))
        t += window
    stack.reverse()
    while stack:
        a, b = stack.pop()
        res["windows"] += 1
        try:
            d = fetch(f"journalctl?unit=ssh.service&since={iso(a)}&until={iso(b)}&lines={CAP}")
        except (RuntimeError, ValueError):  # relay failure or non-JSON body
            d = None
        if not d or not d.get("available") or d.get("returncode") not in (0, 1):
            res["unreadable"].append([iso(a), iso(b)])
            continue
        lines = d.get("lines", [])
        if len(lines) >= CAP:  # full => the tail was returned and the head is lost
            if b - a <= MIN_WINDOW:
                res["unreadable"].append([iso(a), iso(b)])
                continue
            mid = a + (b - a) / 2
            mid = mid.replace(microsecond=0)
            res["split"] += 1
            stack.append((mid, b))
            stack.append((a, mid))
            continue
        for line in lines:
            m = _ACCEPT.match(line)
            if not m:
                continue
            res["total_accepts"] += 1
            cls = classify(m["ip"], trainer_ip, set(allow))
            if cls not in ("trainer", "allowlisted"):
                res["accepts"].append({
                    "ts": m["ts"], "user": m["user"], "method": m["method"],
                    "source": cls, "key_last4": (m["fp"] or "")[-4:],
                })
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--trainer-ip", default=os.environ.get("TRAINER_VM_IP", ""))
    ap.add_argument("--allow-ip", action="append", default=[])
    ap.add_argument("--window-minutes", type=int, default=20)
    a = ap.parse_args(argv)
    if not a.trainer_ip:
        print("need --trainer-ip or TRAINER_VM_IP", file=sys.stderr)
        return 2
    r = sweep(parse_ts(a.since), parse_ts(a.until), a.trainer_ip, set(a.allow_ip),
              timedelta(minutes=a.window_minutes))
    print(json.dumps({k: v for k, v in r.items()}, indent=1))
    if r["unreadable"]:
        print(f"COVERAGE INCOMPLETE: {len(r['unreadable'])} of {r['windows']} windows unreadable (could_not_look)",
              file=sys.stderr)
        return 2
    return 1 if r["accepts"] else 0


if __name__ == "__main__":
    sys.exit(main())
