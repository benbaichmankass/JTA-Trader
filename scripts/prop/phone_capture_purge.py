#!/usr/bin/env python3
"""Delete phone step captures older than 7 days (PHONE-EXEC-OBSERVABLE-1018; operator: "auto-deleted after 7 days").

Fired daily by ``deploy/ict-phone-capture-purge.timer`` on the live trader box, where the captures live
(``<trade_journal.db dir>/phone_captures/``). The same purge also runs opportunistically on every capture the
phone posts (``src.prop.phone_captures.maybe_purge``), so the TTL holds with or without this timer. Read-only
on everything but the capture directories; prints the purge result as one JSON line.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv=None) -> int:
    from src.prop.phone_captures import main as _main
    return _main(["--purge"] + list(argv or []))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
