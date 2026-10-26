#!/usr/bin/env python3
"""Live-review apply AUTOFLOW (LTR-APPLY-AUTOFLOW option a): landed row -> live-review-apply.

The operator, 2026-10-26 09:35Z popup, verbatim: "1 for now but I want us to
figure out how to create an automated flow with minimum latency". Today a
landed ``tighten_sl`` row waits for a manager wake before anyone files the
``live-review-apply`` system-action. This removes that hop:
``.github/workflows/live-review-autoflow.yml`` runs on every push to ``main``
that touches ``comms/live_review/reviews.jsonl`` and calls this script.

1. **New rows only.** The review_ids at ``--after`` minus those at ``--before``.
   A ``--before`` git cannot resolve (a zero sha, a force-push) falls back to
   ``--after~1``, so an unknown base can never re-dispatch the whole log.
2. **Qualifying = the dispatcher's own clauses.** Each new row goes through
   ``live_review_dispatch.check_row`` (the same function the VM runs) against the
   outcome table committed at ``--after``. This is a pre-filter, not a gate: the
   VM re-runs every check, ``approve_amend`` decides per account, and
   ``dispatch_state.json`` makes a repeat review_id a refused duplicate.
3. **Wait for the VM's checkout.** The dispatcher reads the row at the VM's
   ``HEAD`` (git-sync, ~5 min). ``--vm-sha-file`` / the workflow polls
   ``/api/diag/version`` until ``git_sha_on_disk`` contains ``--after``.

Prints one review_id per line on stdout for the workflow to file; reasons on
stderr. Exit 0 always on a clean evaluation (an empty list is a real answer);
2 on a usage or git error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
import live_review_dispatch as lrd  # noqa: E402  -- the ONE definition of the mandate clauses


def _show(ref: str, path: str) -> Optional[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _resolves(ref: str) -> bool:
    if not ref or set(ref) == {"0"}:
        return False
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          capture_output=True).returncode == 0


def rows(text: Optional[str]) -> List[Dict[str, Any]]:
    out = []
    for line in (text or "").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("review_id"):
            out.append(r)
    return out


def qualifying(before_text: Optional[str], after_text: Optional[str],
               evidence_for) -> Tuple[List[str], List[str]]:
    """(review_ids to dispatch, skip lines). Pure given ``evidence_for(path)``."""
    old = {r["review_id"] for r in rows(before_text)}
    go, skip = [], []
    for r in rows(after_text):
        rid = r["review_id"]
        if rid in old:
            continue
        ev = r.get("outcome_table_source")
        _, refusal = lrd.check_row(r, evidence_for(ev) if ev else None)
        if refusal:
            skip.append(f"{rid}: {refusal}")
        else:
            go.append(rid)
    return go, skip


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    a = ap.parse_args(argv)
    if not _resolves(a.after):
        print(f"live_review_autoflow: --after {a.after} does not resolve", file=sys.stderr)
        return 2
    before = a.before if _resolves(a.before) else f"{a.after}~1"
    go, skip = qualifying(_show(before, lrd.REVIEWS_PATH), _show(a.after, lrd.REVIEWS_PATH),
                          lambda p: _show(a.after, p))
    for s in skip:
        print(f"skip {s}", file=sys.stderr)
    for rid in go:
        print(rid)
    print(f"live_review_autoflow: {len(go)} to dispatch, {len(skip)} new row(s) not qualifying "
          f"(base {before})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
