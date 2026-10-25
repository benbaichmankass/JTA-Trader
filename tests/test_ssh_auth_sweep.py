"""ssh_auth_sweep: windowing, split-on-full, redaction, and coverage honesty."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.ops import ssh_auth_sweep as s

T0 = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
TRAINER, OTHER = "10.0.0.1", "10.9.9.9"


def _line(ts, ip, fp="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAXoek"):
    return f"{ts}+0000 h sshd[1]: Accepted publickey for ubuntu from {ip} port 5 ssh2: RSA SHA256:{fp}"


def _journal(events):
    """events: list of (datetime, ip). Mimics the relay: last CAP lines of the window."""
    def fetch(path):
        q = dict(p.split("=") for p in path.split("?")[1].split("&"))
        a, b = s.parse_ts(q["since"]), s.parse_ts(q["until"])
        ls = [_line(s.iso(t)[:-1], ip) for t, ip in events if a <= t < b]
        return {"available": True, "returncode": 0, "lines": ls[-s.CAP:]}
    return fetch


def test_finds_non_trainer_among_overflowing_trainer_noise():
    ev = [(T0 + timedelta(seconds=i), TRAINER) for i in range(3000)]  # > CAP in one window
    ev.append((T0 + timedelta(seconds=5), OTHER))  # buried at the HEAD: a plain tail pull loses it
    r = s.sweep(T0, T0 + timedelta(minutes=60), TRAINER, fetch=_journal(ev), window=timedelta(minutes=60))
    assert not r["unreadable"] and r["split"] >= 1
    assert r["total_accepts"] == 3001
    assert [a["key_last4"] for a in r["accepts"]] == ["Xoek"]


def test_output_has_no_raw_ip_or_full_fingerprint():
    r = s.sweep(T0, T0 + timedelta(minutes=5), TRAINER, fetch=_journal([(T0, OTHER)]))
    blob = repr(r)
    assert OTHER not in blob and "AAAAAAAA" not in blob and r["accepts"][0]["source"].startswith("other:")


def test_unreadable_window_is_reported_not_clean():
    def boom(path):
        raise RuntimeError("relay down")
    r = s.sweep(T0, T0 + timedelta(minutes=5), TRAINER, fetch=boom)
    assert r["unreadable"] and r["total_accepts"] == 0


def test_irreducible_full_window_is_unreadable():
    ev = [(T0, TRAINER)] * 2500  # all in one second: cannot be split further
    r = s.sweep(T0, T0 + timedelta(seconds=2), TRAINER, fetch=_journal(ev), window=timedelta(seconds=2))
    assert r["unreadable"]
