"""Print a one-time passkey enrolment code (UI-UPGRADE-1-AUTH, design §2a).

Run on the web-api host (the future Tier-1 ``passkey-enrol-code`` system-action
wraps this and pings the code to the private SYSTEM chat)::

    python -m src.web.api.enrol_code

Needs ``WEB_SESSION_PEPPER`` (codes are stored hashed). The code is valid for
15 minutes and single use; it is printed once and never logged.
"""
from __future__ import annotations

import sys

from src.web.api import web_sessions


def main() -> int:
    try:
        code = web_sessions.issue_enrol_code()
    except web_sessions.SessionsUnavailable:
        print("auth_unavailable", file=sys.stderr)
        return 2
    print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
