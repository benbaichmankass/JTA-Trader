"""IB-MGC-INACTIVE-1125: per-leg placement backoff -- contained, never halted, ONE flag."""
from __future__ import annotations

from src.core import placement_backoff as pb


def _clock(monkeypatch, start=1000.0):
    now = [start]
    monkeypatch.setattr(pb, "_clock", lambda: now[0])
    return now


def test_grace_then_exponential_capped():
    assert [pb.delay_after(n) for n in (1, 2)] == [0.0, 0.0]
    assert pb.delay_after(3) == pb.BASE_DELAY_S
    assert pb.delay_after(4) == 2 * pb.BASE_DELAY_S
    assert pb.delay_after(50) == pb.MAX_DELAY_S


def test_one_flag_per_streak_and_retry_resumes(monkeypatch):
    now = _clock(monkeypatch)
    k = pb.key_for("ib_paper", "mgc_trend_1h", "mgc", "SHORT")
    assert k == ("ib_paper", "mgc_trend_1h", "MGC", "short")
    flags = []
    for _ in range(2):
        _, _, f = pb.record_failure(k, "Error 201")
        flags.append(f)
        assert pb.remaining_s(k) is None  # grace: next tick may go
    n, delay, f = pb.record_failure(k, "Error 201")
    flags.append(f)
    assert (n, delay) == (3, pb.BASE_DELAY_S)
    assert pb.remaining_s(k) == pb.BASE_DELAY_S
    now[0] += delay + 1
    assert pb.remaining_s(k) is None  # never halted: the leg is tried again
    _, _, f = pb.record_failure(k, "Error 201")
    flags.append(f)
    assert flags == [False, False, True, False]


def test_success_clears_and_new_streak_can_flag_again(monkeypatch):
    _clock(monkeypatch)
    k = pb.key_for("a", "s", "X", "long")
    for _ in range(3):
        pb.record_failure(k, "r")
    pb.clear(k)
    assert pb.failures(k) == 0 and pb.remaining_s(k) is None
    flags = [pb.record_failure(k, "r")[2] for _ in range(3)]
    assert flags == [False, False, True]


def test_keys_are_independent(monkeypatch):
    _clock(monkeypatch)
    a = pb.key_for("ib_paper", "mgc_trend_1h", "MGC", "short")
    b = pb.key_for("ib_paper", "mhg_pullback_1d", "MHG", "long")
    for _ in range(4):
        pb.record_failure(a, "r")
    assert pb.remaining_s(a) is not None
    assert pb.remaining_s(b) is None
