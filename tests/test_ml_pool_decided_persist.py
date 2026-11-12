"""A decision close is decided ONCE across trader restarts (row ML-ENTRY-EQ-RESTART-REDECIDE, Tier 2).

The ml_entry_eq* decided memo used to live only in memory, so a restart within ``max_snapshot_age_h`` of a close re-decided it (journal 2026-11-11:
``pool_scored bar=2026-11-11T20:00`` from four processes, 21:11-22:22Z). Planted / clean pair:

* planted -- a restart after a close (memo dropped from memory, file kept): the builder re-emits nothing for that close, and a symbol the pool
  REFUSED at that close stays decided even if the restarted process would now score it a package (e.g. a new artifact).
* clean -- a NEW close after the restart decides normally (every symbol is evaluated, packages are emitted).
No new refusal is added: the only reason a symbol does not emit is ``already_decided_this_bar`` for a close it was already decided at."""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.runtime import ml_entry_eq_features as F
from src.runtime import ml_pool_scoring as PS
from src.units.strategies import ml_entry_eq as L
from tests.test_ml_entry_eq_full_pool import CFG, _snap

LEG = "ml_entry_eq_struct"


def _setup(monkeypatch, tmp_path, snap, now):
    p = tmp_path / "snap.json"
    F.write_snapshot(p, snap)
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(p))
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp(now)))
    leg = {"enabled": True, "pool_scored": True, "symbols": list(snap["symbols"]), "max_snapshot_age_h": 4.0, **CFG}
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda *a, **k: {LEG: leg})
    return leg


def _restart():
    """What a trader restart does to this module's state: the score cache and the in-memory memos are gone; the files on disk are not."""
    PS._CACHE.clear()
    PS.decided_set(LEG).forget_in_memory()
    PS.refused_set(LEG).forget_in_memory()


def _clean():
    PS._CACHE.clear()
    PS.decided_set(LEG).clear()
    PS.refused_set(LEG).clear()


def _run(B, snap):
    out = {}
    for s in snap["symbols"]:
        sig = B.ml_entry_eq_struct_signal_builder({"SYMBOL": s})
        out[s] = json.loads(json.dumps(sig, default=str))
    return out


def _emitted(out):
    return sorted(s for s, o in out.items() if '"side": "buy"' in json.dumps(o))


def test_restart_after_a_close_does_not_re_emit_and_a_new_close_decides(monkeypatch, tmp_path):
    from src.runtime import strategy_signal_builders as B
    snap = _snap("2026-11-05T20:00:00+00:00", n=40, seed=1)
    leg = _setup(monkeypatch, tmp_path, snap, "2026-11-05T20:05:00+00:00")
    _clean()
    first = _run(B, snap)
    res = PS.batch(LEG, leg, snap)
    want = sorted(s for s, v in res.items() if isinstance(v, dict))
    assert _emitted(first) == want and want, "the fixture must produce at least one package"
    assert PS.decided_path(LEG).exists()

    # PLANTED: restart 1h later (after the RTH close, inside max_snapshot_age_h) on the SAME close -> nothing re-emits, nothing is picked.
    _restart()
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-05T21:11:00+00:00")))
    cfg = {LEG: leg}
    assert PS.picks(cfg, legs=[LEG]) == []
    again = _run(B, snap)
    assert _emitted(again) == []
    assert all("already_decided_this_bar" in json.dumps(o) for o in again.values())

    # CLEAN: a NEW close after the restart decides normally (same population, every symbol evaluated, packages emitted).
    snap2 = _snap("2026-11-06T16:00:00+00:00", n=40, seed=1)
    _setup(monkeypatch, tmp_path, snap2, "2026-11-06T16:05:00+00:00")
    nxt = _run(B, snap2)
    assert _emitted(nxt) == want                       # same features -> same packages, at the new close
    assert not any("already_decided_this_bar" in json.dumps(o) for o in nxt.values())
    _clean()


def test_a_close_refused_before_a_restart_stays_decided_under_a_new_answer(monkeypatch, tmp_path):
    """The pool's refusals at a close are recorded (persisted) when the pool is scored, so a restarted process that would now score a package
    for that close -- a new artifact, say -- does not enter it late."""
    from src.runtime import strategy_signal_builders as B
    snap = _snap("2026-11-05T20:00:00+00:00", n=40, seed=1)
    leg = _setup(monkeypatch, tmp_path, snap, "2026-11-05T20:05:00+00:00")
    _clean()
    res = PS.batch(LEG, leg, snap)                      # the tick's picker scores the pool; refused symbols get no pass
    refused = sorted(s for s, v in res.items() if isinstance(v, str))
    assert refused
    assert all((s, snap["bar_close"]) in PS.refused_set(LEG) for s in refused)

    _restart()
    real = L.score_pool

    def _everything_is_a_package(vcfg, snp, syms, model=None):        # the restarted process's (new) answer
        out = real(vcfg, snp, syms, model)
        pkg = next(v for v in out.values() if isinstance(v, dict))
        return {s: dict(pkg, symbol=s) for s in out}
    monkeypatch.setattr(L, "score_pool", _everything_is_a_package)
    picks = PS.picks({LEG: leg}, legs=[LEG])
    assert not set(picks) & set(refused)
    out = {s: B.ml_entry_eq_struct_signal_builder({"SYMBOL": s}) for s in refused}
    assert all("already_decided_this_bar" in json.dumps(o, default=str) for o in out.values())
    _clean()


def test_memo_file_round_trip_prunes_old_closes_and_survives_a_bad_file(tmp_path, monkeypatch):
    monkeypatch.setenv(PS.DECIDED_DIR_ENV, str(tmp_path))
    m = PS.DecidedMemo("x")
    for i in range(PS.KEEP_CLOSES + 4):
        m.add(("SPY", f"2026-11-{i + 1:02d}T20:00:00+00:00"))
    assert len(m) == PS.KEEP_CLOSES
    m2 = PS.DecidedMemo("x")
    assert ("SPY", f"2026-11-{PS.KEEP_CLOSES + 4:02d}T20:00:00+00:00") in m2
    assert ("SPY", "2026-11-01T20:00:00+00:00") not in m2              # oldest closes pruned
    PS.decided_path("y").write_text("{not json")
    m3 = PS.DecidedMemo("y")
    assert ("SPY", "x") not in m3                                        # unreadable file: empty memo, no raise
    m3.add(("SPY", "2026-11-01T20:00:00+00:00"))
    assert ("SPY", "2026-11-01T20:00:00+00:00") in PS.DecidedMemo("y")   # and the next write repairs it
