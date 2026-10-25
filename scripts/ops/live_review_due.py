#!/usr/bin/env python3
"""Live trade review gate client (LTR-1). Called hourly by the gate routine.

Fetches ``/api/diag/live_review_due`` through ``scripts/ops/diag_fetch.sh`` and
exits cheaply: ONE short line and a distinct exit code when nothing is due.

Exit codes (the gate keys on these, so "could not look" is never "nothing due"):
  0   something is due -- JSON of the due packages on stdout
  10  looked, nothing due -- one line on stdout, no JSON
  11  could not look (route said could_not_look, or the fetch failed) -- reason
      on stderr; the gate must NOT treat this as empty
  2   usage error

Use ``--from-file <json>`` to evaluate a saved payload (tests, replays).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FETCH = os.path.join(HERE, "diag_fetch.sh")


def classify(doc: object) -> tuple[int, str]:
    if not isinstance(doc, dict):
        return 11, "payload is not a JSON object"
    if doc.get("read_state") != "looked" or doc.get("due_count") is None:
        return 11, f"could_not_look: {doc.get('reason') or 'no reason given'}"
    if doc["due_count"] == 0:
        return 10, f"nothing due ({doc.get('open_count')} open)"
    return 0, f"{doc['due_count']} due"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-file", help="read the payload from a file instead of the route")
    args = ap.parse_args(argv)
    if args.from_file:
        try:
            with open(args.from_file, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"live_review_due: cannot read {args.from_file}: {exc}", file=sys.stderr)
            return 11
    else:
        proc = subprocess.run([FETCH, "live_review_due"], capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"live_review_due: fetch failed (diag_fetch.sh exit {proc.returncode}); "
                  "use the vm-diag relay", file=sys.stderr)
            return 11
        try:
            doc = json.loads(proc.stdout)
        except ValueError as exc:
            print(f"live_review_due: route returned non-JSON: {exc}", file=sys.stderr)
            return 11
    code, line = classify(doc)
    if code == 0:
        print(json.dumps(doc, indent=2, sort_keys=True))
    elif code == 10:
        print(line)
    else:
        print(f"live_review_due: {line}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
