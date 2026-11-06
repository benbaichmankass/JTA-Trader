#!/usr/bin/env python3
"""Deliver GitHub-produced pending pings via POST /api/bot/alerts (WSD-S6A) instead of a commit.

Reads the rows a producer just appended to ``docs/claude/pending-pings.jsonl`` in THIS checkout
(rows not present in ``git show HEAD:<file>``) plus the digest receipt, and POSTs each to the VM
(``route: "ping"``). The VM delivers exactly as ``notify_on_pull`` would (see
``src/runtime/ping_ingest.py``).

RETRY WITH DIAGNOSIS, NEVER DROP, NEVER HALT: each POST is retried with backoff; every failure is
printed with its cause (no token / HTTP status + body head / network error). If any row is still
undelivered the script exits 0 with ``delivered=false`` and the workflow falls back to the legacy
commit-to-main path, so the ping and receipt still reach the VM through git-sync as before.

Stdlib only. Token: ``DASHBOARD_API_TOKEN`` (same bearer ``post_alert.sh`` uses).
Gates this adds or changes: none.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = os.environ.get("BOT_API_BASE", "https://ict-bot.duckdns.org").rstrip("/")
ATTEMPTS = 4
BACKOFF_S = (0, 5, 15, 45)


def new_rows(path: Path, ref: str = "HEAD") -> List[Dict[str, Any]]:
    """Rows in the working file that are not in the committed version."""
    if not path.exists():
        return []
    try:
        old = subprocess.run(["git", "show", f"{ref}:{path.as_posix()}"], capture_output=True,
                             text=True, check=True).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        old = []
    seen = {ln.strip() for ln in old if ln.strip()}
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip() and ln.strip() not in seen:
            out.append(json.loads(ln))
    return out


def post(doc: Dict[str, Any], token: str, sleep=time.sleep, opener=urllib.request.urlopen) -> Optional[str]:
    """POST once with retries. Returns None on success, else the final diagnosis."""
    diagnosis = "no attempt"
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    for i in range(ATTEMPTS):
        if BACKOFF_S[i]:
            sleep(BACKOFF_S[i])
        req = urllib.request.Request(f"{BASE}/api/bot/alerts", data=data, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with opener(req, timeout=20) as r:  # noqa: S310
                body = json.loads(r.read().decode("utf-8") or "{}")
            if body.get("recorded"):
                print(f"post_ping: delivered (attempt {i + 1}): {body}")
                return None
            diagnosis = f"HTTP 200 but no `recorded`: {str(body)[:200]}"
        except urllib.error.HTTPError as e:
            diagnosis = f"HTTP {e.code}: {e.read()[:200]!r}"
            if e.code in (400, 401, 403):   # retrying cannot fix a bad body / token
                print(f"post_ping: attempt {i + 1} {diagnosis} (not retryable)")
                return diagnosis
        except (urllib.error.URLError, OSError, ValueError) as e:
            diagnosis = f"network/parse error: {e!r}"
        print(f"post_ping: attempt {i + 1}/{ATTEMPTS} failed — {diagnosis}")
    return diagnosis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pending", default="docs/claude/pending-pings.jsonl")
    ap.add_argument("--receipt", default="docs/claude/work/WORK-DIGEST.json")
    a = ap.parse_args(argv)

    rows = new_rows(Path(a.pending))
    receipt = None
    rp = Path(a.receipt)
    if rp.exists():
        receipt = json.loads(rp.read_text(encoding="utf-8"))
    out = os.environ.get("GITHUB_OUTPUT")
    failures: List[str] = []
    token = os.environ.get("DASHBOARD_API_TOKEN", "")
    if not rows:
        failures.append("no new pending-pings row to deliver (producer wrote nothing)")
    elif not token:
        failures.append("DASHBOARD_API_TOKEN unset — cannot POST")
    else:
        for n, row in enumerate(rows):
            d = post({"kind": str(row.get("event") or "ping"), "route": "ping", "entry": row,
                      "receipt": receipt if n == len(rows) - 1 else None}, token)
            if d:
                failures.append(d)
    ok = not failures
    for f in failures:
        print(f"::warning::post_ping: {f} — falling back to the commit-to-main path")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"delivered={'true' if ok else 'false'}\n")
    print(f"post_ping: delivered={ok} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
