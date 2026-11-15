#!/usr/bin/env python3
"""Ask the system to set a VM-executed prop ticket's TP and/or SL (PROP-BRACKET-APPLY, operator 2026-11-11).

Dry-run unless ``--apply``. Thin CLI over :func:`src.prop.bracket_request.request_bracket`: it records the request
on the ticket and the account's executor applies it through its own amend code. Exit: 0 queued / dry-run ok,
5 refused (the detail says why), 1 write failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.prop.bracket_request import R_FAILED, R_REFUSED, request_bracket  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--account", required=True)
    ap.add_argument("--ticket-id", required=True)
    ap.add_argument("--tp", type=float)
    ap.add_argument("--sl", type=float)
    ap.add_argument("--clear-tp", action="store_true", help="remove a TP pin")
    ap.add_argument("--reason", default="")
    ap.add_argument("--apply", action="store_true", help="write the request (default: dry run)")
    a = ap.parse_args(argv)
    out = request_bracket(a.ticket_id, account_id=a.account, tp=a.tp, sl=a.sl, clear_tp=a.clear_tp,
                          reason=a.reason, apply=a.apply)
    print(json.dumps(out, indent=2, default=str))
    return 5 if out["result"] == R_REFUSED else 1 if out["result"] == R_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
