"""Mint a one-time passkey enrolment code and deliver it ONLY via the private SYSTEM ping.

Used by the Tier-1 ``passkey-enrol-code`` system-action (UI-UPGRADE-1-AUTH-CONFIG,
design §2a). Unlike ``python -m src.web.api.enrol_code`` this NEVER prints the
code: stdout/stderr (which the action posts to a PUBLIC issue comment) carry only
``sent, valid 15 min`` or a failure word.
"""
# wiring: scheduled-via-system-action - dispatched by the `passkey-enrol-code` action
# (scripts/ops/passkey_enrol_code_action.sh); not imported by the runtime.
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def main() -> int:
    from src.web.api import web_sessions

    try:
        code = web_sessions.issue_enrol_code()
    except web_sessions.SessionsUnavailable:
        print("auth_unavailable: WEB_SESSION_PEPPER is not configured")
        return 2
    except Exception as exc:  # noqa: BLE001 - class name only, never the message
        print(f"mint_failed: {type(exc).__name__}")
        return 1

    minutes = web_sessions.ENROL_CODE_TTL_SECONDS // 60
    body = (f"Passkey enrolment code: {code}\n"
            f"Single use, valid {minutes} min. Enter it on the sign-in screen after Google.")
    try:
        import send_ping

        send_ping.enqueue(body, priority="high", target="system")
    except Exception as exc:  # noqa: BLE001
        # The minted code is unreachable and expires unused; say so, leak nothing.
        print(f"ping_failed: {type(exc).__name__} (code discarded, expires in {minutes} min)")
        return 1
    print(f"sent, valid {minutes} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
