"""SL-ONLY structure exit (operator 2026-11-03, option B for ml_entry; record #22645 + the B choice).

Pins:
1. the declaration spellings, and that every full-mode declaration still parses byte-identically;
2. SL-only never proposes a TP, and its SL equals the full mode's SL on recorded bars (the SL path is shared);
3. ml_entry.monitor with sl_only: the structure SL and the ml_first_passage TP each have exactly ONE owner,
   a close from either side wins, and the time-stop close still short-circuits;
4. through the shared verdict interpreter (the one order_monitor._apply_update uses to build its single
   exchange-first modify), a merged tick carries one SL value (structure) and one TP value (revision);
5. full mode ("pivot=5", the 19 trend/pullback legs) is unchanged: the TP revision does not run and the
   structure verdict is returned as-is.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.runtime import structure_exit_live as sxl
from src.runtime.monitor_verdict import KIND_CLOSE, KIND_MODIFY, interpret_verdict
from src.runtime.tp_revision import TpRevision
from src.units.strategies import ml_entry

FIX = Path(__file__).parent / "fixtures" / "ADAUSDT_2h_2020-06-03_2026-10-15.csv"


@pytest.fixture(scope="module")
def bars4h() -> pd.DataFrame:
    df = pd.read_csv(FIX, nrows=6000)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    g = df.set_index("timestamp").resample("4h")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()}).dropna()
    return out.reset_index()


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path))


def _pkg(df, i, direction, spec, mult=2.5):
    entry = float(df["close"].iloc[i])
    atr = sxl._atr_at(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), i)
    sl = entry - mult * atr if direction == "long" else entry + mult * atr
    tp = entry * (1.099 if direction == "long" else 0.901)
    meta = {"atr": atr, "risk_per_unit": abs(entry - sl), "entry_time": str(df["timestamp"].iloc[i]),
            "timeframe": "4h", "structure_exit": spec}
    return {"order_package_id": f"p{i}", "strategy_name": "t", "symbol": "ADAUSDT",
            "direction": direction, "entry": entry, "sl": sl, "tp": tp, "meta": meta}


# --------------------------------------------------------------------------- 1. declaration
def test_sl_only_spellings_and_full_mode_byte_identical():
    full = {"pivot": 5, "buffer_atr": 0.25, "min_r": 1.0, "fvg": True}
    assert sxl.declared({"structure_exit": "pivot=5"}) == full            # no sl_only key at all
    assert sxl.declared({"structure_exit": {"pivot": 5}}) == full
    assert sxl.declared({"structure_exit": "pivot=5;sl_only"}) == {**full, "sl_only": True}
    assert sxl.declared({"structure_exit": " pivot=5 ; sl_only "}) == {**full, "sl_only": True}
    assert sxl.declared({"structure_exit": {"pivot": 5, "sl_only": True}}) == {**full, "sl_only": True}
    assert sxl.declared({"structure_exit": {"pivot": 5, "sl_only": "yes"}}) == full   # only a real True
    assert sxl.declared({"structure_exit": "pivot=5;bogus"}) is None       # unknown flag -> no move


# --------------------------------------------------------------------------- 2. no TP, same SL
def test_sl_only_never_proposes_tp_and_matches_full_mode_sl(bars4h):
    df = bars4h
    n_sl = n_full_tp = 0
    for i in range(300, 2500, 61):
        for direction in ("long", "short"):
            end = i + 60
            frame = df.iloc[: end + 1].reset_index(drop=True)
            full = sxl.structure_exit_verdict(_pkg(df, i, direction, "pivot=5")["meta"],
                                              _pkg(df, i, direction, "pivot=5"), frame, timeframe="", journal=False)
            slo_pkg = _pkg(df, i, direction, "pivot=5;sl_only")
            slo = sxl.structure_exit_verdict(slo_pkg["meta"], slo_pkg, frame, timeframe="", journal=False)
            if full and full.get("tp") is not None:
                n_full_tp += 1
            if slo is None:
                assert not (full and "sl" in full)
                continue
            assert "tp" not in slo and "tp_reason" not in slo
            if slo.get("action") == "close":
                assert full and full.get("action") == "close"
                continue
            n_sl += 1
            assert full is not None and full.get("sl") == slo["sl"]
            assert slo["structure_move"]["tp_after"] == slo["structure_move"]["tp_before"]
    assert n_sl > 0 and n_full_tp > 0, "probe saw no SL move or no full-mode TP: vacuous"


# --------------------------------------------------------------------------- 3. monitor merge
_SL_PKG = {"order_package_id": "p", "direction": "long", "entry": 100.0, "sl": 95.0, "tp": 110.0,
           "meta": {"structure_exit": "pivot=5;sl_only", "tp_revision": {"rule": "ml_first_passage"}}}


def _stub(monkeypatch, *, base=None, sx=None, rev=None):
    import src.units.strategies.claude_desk as desk
    monkeypatch.setattr(desk, "max_hold_verdict", lambda pkg, now: base)
    monkeypatch.setattr(ml_entry, "_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(ml_entry, "structure_verdict", lambda pkg, df: sx)
    monkeypatch.setattr(ml_entry, "tp_revision", lambda cfg, df, pkg: rev)


def test_sl_only_monitor_one_owner_per_side(monkeypatch):
    sx = {"sl": 97.0, "tp": 999.0, "tp_reason": "must be dropped",
          "structure_move": {"sl_before": 95.0, "sl_after": 97.0, "tp_before": 110.0, "tp_after": 999.0}}
    rev = TpRevision(tp=112.0, rule="ml_first_passage", reason="ml_first_passage: 4.0 ATR")
    _stub(monkeypatch, base={"sl": 1.0, "info": "x"}, sx=sx, rev=rev)
    v = ml_entry.monitor({}, None, _SL_PKG)
    assert v["sl"] == 97.0                       # structure owns the SL (base's stray sl dropped)
    assert v["tp"] == 112.0 and v["tp_reason"].startswith("ml_first_passage")   # revision owns the TP
    assert v["structure_move"]["tp_after"] == 110.0                              # journal: TP not moved by structure
    d = interpret_verdict(v, current_sl=95.0, current_tp=110.0)
    assert d.kind == KIND_MODIFY and d.sl == 97.0 and d.tp == 112.0              # ONE modify, one value per side


def test_sl_only_monitor_each_side_alone(monkeypatch):
    rev = TpRevision(tp=112.0, rule="ml_first_passage", reason="ml_first_passage: r")
    _stub(monkeypatch, sx=None, rev=rev)
    assert ml_entry.monitor({}, None, _SL_PKG) == {"tp": 112.0, "tp_reason": "ml_first_passage: r"}
    _stub(monkeypatch, sx={"sl": 97.0, "structure_move": {"tp_before": 110.0}}, rev=None)
    v = ml_entry.monitor({}, None, _SL_PKG)
    assert v["sl"] == 97.0 and "tp" not in v
    _stub(monkeypatch, sx=None, rev=None)
    assert ml_entry.monitor({}, None, _SL_PKG) is None


def test_sl_only_close_wins(monkeypatch):
    rev = TpRevision(tp=112.0, rule="ml_first_passage", reason="r")
    close = {"action": "close", "reason": sxl.REASON_SL_CROSS, "exit_price": 96.0}
    _stub(monkeypatch, sx=close, rev=rev)
    v = ml_entry.monitor({}, None, _SL_PKG)
    assert v == close and interpret_verdict(v, current_sl=95.0, current_tp=110.0).kind == KIND_CLOSE
    tstop = {"action": "close", "reason": "max_hold"}
    _stub(monkeypatch, base=tstop, sx={"sl": 97.0}, rev=rev)
    assert ml_entry.monitor({}, None, _SL_PKG) == tstop


def test_sl_only_revision_runs(monkeypatch):
    calls = []
    _stub(monkeypatch, sx={"sl": 97.0})
    monkeypatch.setattr(ml_entry, "tp_revision", lambda cfg, df, pkg: calls.append(1))
    ml_entry.monitor({}, None, _SL_PKG)
    assert calls == [1]


# --------------------------------------------------------------------------- 5. full mode unchanged
def test_full_mode_unchanged_revision_does_not_run(monkeypatch):
    pkg = {**_SL_PKG, "meta": {**_SL_PKG["meta"], "structure_exit": "pivot=5"}}
    sx = {"sl": 97.0, "tp": 120.0, "tp_reason": "structure_exit: level"}
    _stub(monkeypatch, sx=sx)
    monkeypatch.setattr(ml_entry, "tp_revision", lambda *a: pytest.fail("revision must not run in full mode"))
    assert ml_entry.monitor({}, None, pkg) is sx


def test_undeclared_unchanged(monkeypatch):
    rev = TpRevision(tp=112.0, rule="ml_first_passage", reason="r")
    _stub(monkeypatch, sx=ml_entry._NOT_DECLARED, rev=rev)
    pkg = {**_SL_PKG, "meta": {"tp_revision": {"rule": "ml_first_passage"}}}
    assert ml_entry.monitor({}, None, pkg) == {"tp": 112.0, "tp_reason": "r"}
