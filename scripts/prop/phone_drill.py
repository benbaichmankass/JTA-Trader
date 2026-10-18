#!/usr/bin/env python3
"""Request ONE phone rehearsal drill — the ``phone-drill`` system-action's CLI (PHONE-EXEC-OBSERVABLE-1018).

The drill (``src.prop.phone_drill``) makes the phone executor run the full stop-amend flow on its real open
position up to the final Confirm, then cancel and close the sheet, reporting pass/fail per step with a capture of
each step. It changes no order: the app never confirms in a drill and the denylist refuses every close / cancel
control. Three consecutive passes arm the live sheet edit (the operator's "done when"); a fail resets the streak.

Must run where ``trade_journal.db`` lives (the live VM, with the runtime data-dir env loaded): the request file sits
beside the journal, where the web API serves ``GET /phone/pending`` from, which is why it is dispatched through the
system-action rather than from a sandbox session. Idempotent: a second request while one is outstanding returns
the existing one.

Usage:
    python3 scripts/prop/phone_drill.py --request --account breakout_2 [--source <who>] [--note <text>]
    python3 scripts/prop/phone_drill.py --status --account breakout_2

Exit 0 and a JSON line on success; 1 on a refusal (account not a phone_accounts entry).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv=None) -> int:
    from src.prop.phone_drill import main as _main
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
