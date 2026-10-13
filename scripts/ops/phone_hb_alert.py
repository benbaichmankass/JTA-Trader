# wiring: called from scripts/ops/work_digest_now.py::run (hourly deploy/ict-work-digest.timer carrier, no unit of
# its own -- the operator's 2026-10-04 one-carrier decision). Tests: tests/test_phone_hb_alert.py.
"""Standalone SYSTEM-channel alert for the Breakout phone executor's heartbeat (PHONE-KEEPALIVE).

WHY: ``phone_hb_breakout_2`` (scripts/ops/prop_silence.py) already detected the 2026-10-13 gap -- the work report
printed it as breached (the 🔕 there is the glyph for "breached", NOT a mute: nothing in this repo mutes a probe).
But its only delivery was a line inside the collapsed "Manager watch" section of the hourly MANAGER-channel digest, so
the operator was never *alerted*. This sends the breach as its own message on the system bot.

SEMANTICS (NO-HALT doctrine: report, never stop anything): edge-triggered, ONE alert per outage and ONE recovery
message. ``unknown`` (could not look) neither alerts nor clears. A failed send leaves the state unchanged, so the
next run retries rather than latching the alert out. Detection latency is the carrier's: up to ~1 h + the 10-min
threshold. The phone's own watchdog (Liveness.kt) is what recovers; this tells the operator it happened.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE = REPO_ROOT / "runtime_logs" / "phone_hb_alert_state.json"


def plan(probe: dict, state: dict, now: datetime) -> tuple[list[tuple[str, str]], dict]:
    """Pure. ``([(priority, body)], new_state)``."""
    status = probe.get("status")
    was = bool(state.get("breached"))
    if status == "breached" and not was:
        body = (f"🚨 Phone executor is silent — {probe.get('detail')}. No Breakout orders can be placed until it is "
                f"back. Its watchdog should restart it; if it does not, open the app on the phone.")
        return [("urgent", body)], {"breached": True, "since": now.isoformat(), "alerted_at": now.isoformat()}
    if status == "ok" and was:
        body = f"✅ Phone executor heartbeat is back — {probe.get('detail')} (silent since {state.get('since', '?')})."
        return [("normal", body)], {"breached": False, "cleared_at": now.isoformat()}
    return [], dict(state)


WATCHDOG = REPO_ROOT / "scripts" / "research" / "research_watchdog.py"


def watchdog_has_open_phone_incident() -> bool:
    """True ONLY when the research watchdog (15-min cadence, PR #17912) reports an OPEN ``phone_heartbeat`` incident, i.e.
    it already told the operator: one incident, one Telegram. Anything else -- script not merged yet, exit 2
    (could_not_look), timeout, unparseable output -- is False, so this alert still sends."""
    if not WATCHDOG.exists():
        return False
    try:
        r = subprocess.run([sys.executable, str(WATCHDOG), "--open-incidents"], capture_output=True, text=True,
                           timeout=60, cwd=REPO_ROOT)
        if r.returncode != 0:
            return False
        d = json.loads(r.stdout.strip().splitlines()[-1])
        return d.get("read_state") == "measured" and "phone_heartbeat" in (d.get("open") or [])
    except Exception:  # noqa: BLE001 -- could not look == send
        return False


def run(now: datetime | None = None, probe: dict | None = None, state_path: Path = STATE,
        send: Callable[..., Any] | None = None,
        watchdog_open: Callable[[], bool] = watchdog_has_open_phone_incident) -> list[str]:
    """Probe, plan, send. Never raises (a broken alert must not take the digest down). Returns what was sent."""
    now = now or datetime.now(timezone.utc)
    sent: list[str] = []
    try:
        if probe is None:
            from scripts.ops import prop_silence  # noqa: PLC0415
            probe = prop_silence.probe_phone_heartbeat(now)
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {}
        msgs, new = plan(probe, state, now)
        if send is None:
            from send_ping import enqueue as send  # noqa: PLC0415
        # ONE Telegram per incident: if the watchdog already owns this outage, stay silent for its alert AND its recovery
        # (it sends its own); the state still advances so this never re-fires for the same outage.
        if msgs and new.get("breached") and not state.get("breached"):
            new["suppressed"] = bool(watchdog_open())
        elif msgs and not new.get("breached") and state.get("suppressed"):
            msgs = []
        for pri, body in msgs:
            if new.get("suppressed") and new.get("breached"):
                break
            send(body, priority=pri, target="system")
            sent.append(body)
        if new != state:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(new))
    except Exception as exc:  # noqa: BLE001 -- see docstring
        print(f"phone-hb-alert: FAILED ({type(exc).__name__}: {exc}); state unchanged, retried next run")
    return sent


if __name__ == "__main__":
    out = run()
    print("phone-hb-alert:", f"{len(out)} message(s) sent" if out else "nothing to send")
    sys.exit(0)
