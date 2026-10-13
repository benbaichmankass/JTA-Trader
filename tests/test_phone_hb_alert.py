"""PHONE-KEEPALIVE: the phone heartbeat alert is edge-triggered, one alert per outage and one recovery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.ops import phone_hb_alert as h
from scripts.ops import prop_silence as ps

NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
BAD = {"status": "breached", "detail": "breakout_2: last phone heartbeat 145 min ago"}
GOOD = {"status": "ok", "detail": "breakout_2: last phone heartbeat 1 min ago"}
UNK = {"status": "unknown", "detail": "?"}


def test_breach_alerts_once_urgent_then_is_quiet():
    m, st = h.plan(BAD, {}, NOW)
    assert len(m) == 1 and m[0][0] == "urgent" and "145 min" in m[0][1] and st["breached"]
    assert h.plan(BAD, st, NOW + timedelta(hours=30))[0] == []   # one alert per outage, no re-alert


def test_unknown_neither_alerts_nor_clears():
    assert h.plan(UNK, {}, NOW)[0] == []
    m, st = h.plan(UNK, {"breached": True, "since": "x"}, NOW)
    assert m == [] and st["breached"] is True


def test_recovery_sends_one_message_then_rearms():
    _, st = h.plan(BAD, {}, NOW)
    m, st2 = h.plan(GOOD, st, NOW + timedelta(minutes=30))
    assert len(m) == 1 and m[0][1].startswith("✅") and st2["breached"] is False
    assert h.plan(GOOD, st2, NOW)[0] == []
    assert len(h.plan(BAD, st2, NOW)[0]) == 1                      # a new outage alerts again


def test_run_sends_on_system_target_and_failed_send_keeps_state(tmp_path):
    calls = []
    sp = tmp_path / "s.json"
    out = h.run(NOW, BAD, sp, lambda body, priority, target: calls.append((priority, target)))
    assert calls == [("urgent", "system")] and len(out) == 1 and sp.exists()

    sp2 = tmp_path / "s2.json"
    def boom(*a, **k): raise OSError("inbox down")
    assert h.run(NOW, BAD, sp2, boom) == [] and not sp2.exists()   # retried next run, not latched out


def test_probe_stale_heartbeat_is_breached_end_to_end():
    old = (NOW - timedelta(minutes=145)).isoformat()
    p = ps.probe_phone_heartbeat(NOW, lambda _p: ("read", {"phone_heartbeat": {"at": old}}), lambda _a: "live")
    assert p["status"] == "breached" and p["priority"] == "urgent"
    assert h.plan(p, {}, NOW)[0][0][0] == "urgent"
